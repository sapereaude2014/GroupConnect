"""
Feishu / Lark Platform Channel for GroupConnect.
Uses the official lark-oapi SDK long-connection (WebSocket) client to receive
messages without requiring a public webhook endpoint.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, Optional, Union

import os
import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.channels.extensions.telegraph import (
    AUTO_TELEGRAPH_THRESHOLD,
    extract_first_paragraph,
    _strip_blockquotes,
)
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.feishu")

_FEISHU_FILE_TYPE_MAP = {
    ".pdf": "pdf", ".doc": "doc", ".docx": "doc",
    ".xls": "stream", ".xlsx": "stream", ".ppt": "stream", ".pptx": "stream",
    ".txt": "stream", ".md": "stream", ".csv": "stream",
    ".zip": "stream", ".rar": "stream", ".7z": "stream",
    ".mp4": "mp4", ".mov": "mp4",
    ".mp3": "opus", ".m4a": "opus", ".wav": "opus", ".aac": "opus",
}

def _feishu_file_type(ext: str) -> str:
    return _FEISHU_FILE_TYPE_MAP.get(ext, "stream")

try:
    import lark_oapi as lark
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
        CallBackCard,
        CallBackToast,
    )
    _HAS_LARK_SDK = True
except ImportError:
    _HAS_LARK_SDK = False
    logger.warning("lark-oapi not installed; Feishu long-connection mode unavailable")


@register_channel(
    name="feishu",
    display_name="Feishu / Lark (飞书)",
    aliases=["lark"],
    fields=[
        ChannelField(key="feishu_app_id", label="Feishu App ID (cli_...)", is_secret=False),
        ChannelField(key="feishu_app_secret", label="Feishu App Secret", is_secret=True),
    ]
)
class FeishuChannel(BaseChannel):
    """Channel adapter for Feishu (Lark) Open Platform using SDK long-connection."""

    # Long replies fold into a summary + expand-button card (the Feishu
    # counterpart of the Telegram auto-Telegraph flow). Same threshold.
    FOLD_THRESHOLD = AUTO_TELEGRAPH_THRESHOLD

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        co = config.channel_options
        self.app_id = co.get("feishu_app_id") or config.raw.get("feishu_app_id") or config.raw.get("app_id", "")
        self.app_secret = co.get("feishu_app_secret") or config.raw.get("feishu_app_secret") or config.raw.get("app_secret", "")
        self.api_base = config.raw.get("feishu_api_base", "https://open.feishu.cn")
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
        self._ws_client = None
        self.is_running = False
        self._last_user_msg_ids: Dict[str, str] = {}  # chat_id -> last user message_id
        self._typing_reactions: Dict[str, tuple] = {}  # chat_id -> (message_id, reaction_id)
        self._fold_cache: Dict[str, Dict[str, str]] = {}  # token -> {"full":..., "summary":...}
        self._fold_cache_limit = 200

    async def get_tenant_access_token(self) -> str:
        """Retrieves and caches Feishu tenant_access_token."""
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        url = f"{self.api_base}/open-apis/auth/v3/tenant_access_token/internal"
        resp = await self.client.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret})
        data = resp.json()
        if data.get("code") == 0:
            self._token = data.get("tenant_access_token")
            self._token_expires_at = now + data.get("expire", 7200)
            return self._token
        raise RuntimeError(f"Failed to get Feishu tenant_access_token: {data}")

    @staticmethod
    def _has_markdown(text: str) -> bool:
        """Detects whether the text contains Markdown formatting that Feishu
        text messages cannot render (warrants an interactive card)."""
        import re
        # Bold / italic / strikethrough
        if re.search(r"\*\*[^*]+\*\*|__[^_]+__|~~[^~]+~~", text):
            return True
        # Headers (# / ## / ###) at line start
        if re.search(r"^#{1,4}\s+\S", text, re.MULTILINE):
            return True
        # Code fences
        if "```" in text:
            return True
        # Lists (- item / 1. item)
        if re.search(r"^\s*[-*]\s+\S|^\s*\d+\.\s+\S", text, re.MULTILINE):
            return True
        # Tables
        if re.search(r"^\|.+\|$", text, re.MULTILINE):
            return True
        # Blockquotes
        if re.search(r"^>\s+\S", text, re.MULTILINE):
            return True
        return False

    @staticmethod
    def _markdown_body_elements(text: str) -> list:
        """Builds schema 2.0 markdown body elements, splitting content over
        ~28KB on paragraph boundaries to stay within the card size limit."""
        MAX_ELEMENT_CHARS = 28000
        if len(text) <= MAX_ELEMENT_CHARS:
            return [{"tag": "markdown", "content": text}] if text.strip() else []
        elements = []
        remaining = text
        while remaining:
            if len(remaining) <= MAX_ELEMENT_CHARS:
                elements.append({"tag": "markdown", "content": remaining})
                break
            # Prefer splitting at a paragraph boundary, then a line break
            cut = remaining.rfind("\n\n", 0, MAX_ELEMENT_CHARS)
            if cut <= 0:
                cut = remaining.rfind("\n", 0, MAX_ELEMENT_CHARS)
            if cut <= 0:
                cut = MAX_ELEMENT_CHARS
            elements.append({"tag": "markdown", "content": remaining[:cut]})
            remaining = remaining[cut:].lstrip("\n")
        return elements

    @staticmethod
    def _card_shell(elements: list) -> dict:
        return {
            "schema": "2.0",
            "config": {"wide_screen_mode": True, "enable_forward": True},
            "body": {"elements": elements},
        }

    @staticmethod
    def _markdown_to_card(text: str) -> dict:
        """Wraps Markdown text in a Feishu interactive card (JSON 2.0).

        Card 2.0's markdown component natively renders headers, tables,
        lists, code blocks, quotes, and inline code, so the text passes
        through unchanged.
        """
        elements = FeishuChannel._markdown_body_elements(text)
        if not elements:
            elements = [{"tag": "markdown", "content": text}]
        return FeishuChannel._card_shell(elements)

    @staticmethod
    def _fold_button(action: str, token: str, label: str, btn_type: str) -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "size": "small",
            "behaviors": [{"type": "callback", "value": {"action": action, "token": token}}],
        }

    def _should_fold(self, text: str) -> bool:
        """True when text (excluding blockquotes) exceeds FOLD_THRESHOLD.
        Mirrors the Telegram auto-Telegraph measurement logic."""
        if not text or self.FOLD_THRESHOLD <= 0:
            return False
        return len(_strip_blockquotes(text)) > self.FOLD_THRESHOLD

    def _folded_card(self, summary: str, token: str) -> dict:
        content = summary if summary else "📄 内容较长，点击下方按钮展开全文。"
        elements = [
            {"tag": "markdown", "content": content},
            self._fold_button("expand", token, "📖 展开全文", "primary"),
        ]
        return self._card_shell(elements)

    def _expanded_card(self, full_text: str, token: str) -> dict:
        elements = self._markdown_body_elements(full_text)
        if not elements:
            elements = [{"tag": "markdown", "content": full_text}]
        elements.append(self._fold_button("collapse", token, "收起", "default"))
        return self._card_shell(elements)

    def _cache_fold(self, token: str, full_text: str, summary: str) -> None:
        if len(self._fold_cache) >= self._fold_cache_limit:
            self._fold_cache.pop(next(iter(self._fold_cache)))
        self._fold_cache[token] = {"full": full_text, "summary": summary}

    async def send_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        # Remove the typing reaction if one exists for this chat
        reaction_info = self._typing_reactions.pop(str(chat_id), None)
        if reaction_info:
            msg_id, reaction_id = reaction_info
            await self._remove_reaction(msg_id, reaction_id)

        token = await self.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

        url = f"{self.api_base}/open-apis/im/v1/messages?receive_id_type=chat_id"
        # Always render as interactive card for consistent markdown rendering.
        # Over-threshold replies fold into summary + expand button (telegraph-style).
        folded_token = None
        if self._should_fold(text):
            folded_token = uuid.uuid4().hex[:16]
            summary = extract_first_paragraph(text)
            card = self._folded_card(summary, folded_token)
        else:
            card = self._markdown_to_card(text)
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False)
        }
        if reply_to_msg_id:
            payload["reply_in_thread"] = False

        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
            if folded_token:
                self._cache_fold(folded_token, text, summary)
            return data["data"]["message_id"]
        # Card send failed; degrade to plain text so the reply is not lost
        if payload["msg_type"] == "interactive":
            logger.warning(f"[Feishu] Card send failed ({data.get('msg')}); falling back to text")
            fallback = {
                "receive_id": str(chat_id),
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False)
            }
            resp = await self.client.post(url, headers=headers, json=fallback)
            data = resp.json()
            if data.get("code") == 0:
                return data["data"]["message_id"]
        logger.error(f"[Feishu] Send message failed: {data}")
        return None

    async def _add_reaction(self, message_id: str, emoji_type: str = "OnIt") -> Optional[str]:
        """Adds a reaction to a message; returns the reaction_id for later removal."""
        try:
            token = await self.get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
            url = f"{self.api_base}/open-apis/im/v1/messages/{message_id}/reactions"
            resp = await self.client.post(url, headers=headers, json={"reaction_type": {"emoji_type": emoji_type}})
            data = resp.json()
            if data.get("code") == 0:
                return data["data"]["reaction_id"]
            logger.debug(f"[Feishu] Add reaction failed: {data}")
        except Exception as e:
            logger.debug(f"[Feishu] Failed to add reaction: {e}")
        return None

    async def _remove_reaction(self, message_id: str, reaction_id: str) -> None:
        """Removes a reaction from a message."""
        try:
            token = await self.get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{self.api_base}/open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}"
            await self.client.delete(url, headers=headers)
        except Exception as e:
            logger.debug(f"[Feishu] Failed to remove reaction {reaction_id}: {e}")

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        """Adds a 'processing' reaction to the user's last message on first call;
        subsequent calls are no-ops until send_reply removes the reaction."""
        cid = str(chat_id)
        if cid in self._typing_reactions:
            return
        msg_id = self._last_user_msg_ids.get(cid)
        if not msg_id:
            return
        reaction_id = await self._add_reaction(msg_id)
        if reaction_id:
            self._typing_reactions[cid] = (msg_id, reaction_id)

    async def send_file(
        self,
        chat_id: Union[int, str],
        file_path: str,
        caption: Optional[str] = None,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        """Sends a file to a Feishu chat. Images use the image API;
        other files use the file API."""
        if not os.path.isfile(file_path):
            logger.warning(f"[Feishu] send_file: file not found: {file_path}")
            return None

        file_size = os.path.getsize(file_path)
        if file_size > 30 * 1024 * 1024:
            logger.warning(f"[Feishu] File {file_path} ({file_size} bytes) exceeds 30MB limit")
            await self.send_reply(chat_id, f"文件超过飞书 30MB 限制，无法上传：{os.path.basename(file_path)}")
            return None

        token = await self.get_tenant_access_token()
        ext = os.path.splitext(file_path)[1].lower()
        filename = os.path.basename(file_path)

        try:
            if ext in (".png", ".jpg", ".jpeg", ".webp"):
                # Upload as image
                upload_url = f"{self.api_base}/open-apis/im/v1/images"
                with open(file_path, "rb") as f:
                    resp = await self.client.post(
                        upload_url,
                        headers={"Authorization": f"Bearer {token}"},
                        data={"image_type": "message"},
                        files={"image": (filename, f)},
                        timeout=60.0,
                    )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"[Feishu] Image upload failed: {data}")
                    return None
                msg_type = "image"
                content = json.dumps({"image_key": data["data"]["image_key"]})
            else:
                # Upload as file
                upload_url = f"{self.api_base}/open-apis/im/v1/files"
                with open(file_path, "rb") as f:
                    resp = await self.client.post(
                        upload_url,
                        headers={"Authorization": f"Bearer {token}"},
                        data={"file_type": _feishu_file_type(ext), "file_name": filename},
                        files={"file": (filename, f)},
                        timeout=60.0,
                    )
                data = resp.json()
                if data.get("code") != 0:
                    logger.error(f"[Feishu] File upload failed: {data}")
                    return None
                msg_type = "file"
                content = json.dumps({"file_key": data["data"]["file_key"]})

            # Send the message with the uploaded media
            msg_url = f"{self.api_base}/open-apis/im/v1/messages?receive_id_type=chat_id"
            payload = {
                "receive_id": str(chat_id),
                "msg_type": msg_type,
                "content": content,
            }
            resp = await self.client.post(
                msg_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                json=payload,
            )
            data = resp.json()
            if data.get("code") == 0:
                return data["data"]["message_id"]
            logger.error(f"[Feishu] Send file message failed: {data}")
            return None
        except Exception as e:
            logger.error(f"[Feishu] send_file error: {e}", exc_info=True)
            return None

    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        try:
            token = await self.get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{self.api_base}/open-apis/im/v1/chats/{chat_id}/leave"
            resp = await self.client.post(url, headers=headers)
            data = resp.json()
            return data.get("code") == 0
        except Exception as e:
            logger.warning(f"[Feishu] Failed to leave chat {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_id: Union[int, str], user_id: Union[int, str]) -> bool:
        try:
            token = await self.get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            url = f"{self.api_base}/open-apis/im/v1/chats/{group_id}/members"
            resp = await self.client.get(url, headers=headers)
            data = resp.json()
            if data.get("code") == 0:
                items = data.get("data", {}).get("items", [])
                for member in items:
                    if str(member.get("member_id")) == str(user_id) or str(member.get("name")) == str(user_id):
                        return True
            return False
        except Exception as e:
            logger.warning(f"[Feishu] Failed to check user membership: {e}")
            return False

    def _build_event_handler(self):
        """Builds the SDK event dispatcher with the message-receive handler
        and the card-action handler (fold expand/collapse buttons)."""
        # NOTE: In lark-oapi >=1.4, register_* methods live on the builder
        # (returning self for chaining), not on the built handler object.

        def _on_card_action(data):
            """Handles fold-card button clicks. Returns a response that
            updates the card in place (no separate PATCH call needed)."""
            try:
                if not _HAS_LARK_SDK:
                    return None
                ev = getattr(data, "event", None)
                action = getattr(ev, "action", None) if ev else None
                value = getattr(action, "value", None) if action else None
                if not isinstance(value, dict):
                    return None
                act = str(value.get("action", ""))
                token = str(value.get("token", ""))
                entry = self._fold_cache.get(token)
                if not entry:
                    toast = CallBackToast()
                    toast.type = "info"
                    toast.content = "内容已失效"
                    resp = P2CardActionTriggerResponse()
                    resp.toast = toast
                    return resp
                if act == "expand":
                    card = self._expanded_card(entry["full"], token)
                elif act == "collapse":
                    card = self._folded_card(entry["summary"], token)
                else:
                    return None
                cb_card = CallBackCard()
                cb_card.type = "raw"
                cb_card.data = card
                resp = P2CardActionTriggerResponse()
                resp.card = cb_card
                return resp
            except Exception as e:
                logger.error(f"[Feishu] Card action error: {e}", exc_info=True)
                return None

        def _on_message_receive(data):
            try:
                event = data.event
                msg = event.message
                sender = event.sender
                sender_id = sender.sender_id

                chat_id = msg.chat_id
                chat_type = msg.chat_type or "group"
                if chat_type == "p2p":
                    chat_type = "private"

                raw_content = msg.content or "{}"
                try:
                    content_json = json.loads(raw_content)
                    text = content_json.get("text", "")
                except Exception:
                    text = raw_content

                mentions = msg.mentions or []
                is_mentioned = any(m.name == self.bot_name or m.key == "@_all" for m in mentions)
                is_triggered = (chat_type == "private") or is_mentioned or (f"@{self.bot_username}" in text)

                # Track last user message_id per chat for typing reactions
                self._last_user_msg_ids[chat_id] = msg.message_id

                inbound = InboundMessage(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    msg_id=msg.message_id,
                    sender_name=sender_id.user_id or sender_id.open_id or "feishu_user",
                    from_user={
                        "id": sender_id.open_id or sender_id.user_id or "",
                        "username": sender_id.user_id or "",
                        "is_bot": False,
                    },
                    text=text,
                    is_triggered=is_triggered,
                )
                asyncio.get_event_loop().create_task(self.handler(inbound))
            except Exception as e:
                logger.error(f"[Feishu] Error processing message event: {e}", exc_info=True)

        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message_receive)
            .register_p2_card_action_trigger(_on_card_action)
            .build()
        )
        return event_handler

    async def start(self) -> None:
        if not _HAS_LARK_SDK:
            raise RuntimeError("lark-oapi SDK not installed. Run: pip install lark-oapi")

        self.is_running = True
        event_handler = self._build_event_handler()
        self._ws_client = lark.ws.Client(
            app_id=self.app_id,
            app_secret=self.app_secret,
            event_handler=event_handler,
            auto_reconnect=True,
            log_level=lark.LogLevel.INFO,
        )
        logger.info(f"Starting Feishu long-connection client (App ID: {self.app_id})...")
        # SDK's start() is blocking (sync), run it in a thread
        await asyncio.get_event_loop().run_in_executor(None, self._ws_client.start)

    async def stop(self) -> None:
        self.is_running = False
        await self.client.aclose()
