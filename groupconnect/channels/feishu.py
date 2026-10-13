"""
Feishu / Lark Platform Channel for GroupConnect.
Uses the official lark-oapi SDK long-connection (WebSocket) client to receive
messages without requiring a public webhook endpoint.
"""

import asyncio
import json
import logging
import time
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

    # Long replies go as a single collapsible card: short summary directly
    # readable, full text inside a native collapsed panel (per-user local
    # expand/collapse, default collapsed — no topics created, no shared
    # expanded state). Hard-coded (summary 60 chars / trigger 100 chars
    # shared with the Telegram auto-Telegraph flow). Replies to messages that
    # live inside a topic stay inside that same topic.
    THREAD_THRESHOLD = AUTO_TELEGRAPH_THRESHOLD

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
        # message_id -> topic root (root_id / thread_id), so replies to
        # in-topic messages stay in-topic. Entries are recorded on inbound
        # messages, so the mapping always covers the message being replied to
        # regardless of restarts.
        self._msg_threads: Dict[str, str] = {}
        self._msg_threads_limit = 2000

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

    def _exceeds_threshold(self, text: str) -> bool:
        """True when text (excluding blockquotes) exceeds the thread threshold.
        Mirrors the Telegram auto-Telegraph measurement logic."""
        if not text or self.THREAD_THRESHOLD <= 0:
            return False
        return len(_strip_blockquotes(text)) > self.THREAD_THRESHOLD



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
        # Reply inside the same topic when the user's message lives in one:
        # topic conversations stay in the topic instead of leaking to the main
        # stream.
        thread_id = self._msg_threads.get(str(reply_to_msg_id)) if reply_to_msg_id else None
        if thread_id:
            return await self._send_reply_in_thread(chat_id, text, headers, reply_to_msg_id)

        # Always render as markdown card for consistent rendering.
        # Over-threshold replies go as a single collapsible card: short
        # summary directly readable, full text inside a native collapsed
        # panel (per-user local expand/collapse, default collapsed).
        if self._exceeds_threshold(text):
            return await self._send_collapsible_reply(chat_id, text, headers)
        card = self._markdown_to_card(text)
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False)
        }

        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
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

    async def _send_full_card(
        self,
        chat_id: Union[int, str],
        text: str,
        headers: Dict[str, str],
    ) -> Optional[Union[int, str]]:
        """Sends the full text as a regular card in the main stream."""
        url = f"{self.api_base}/open-apis/im/v1/messages?receive_id_type=chat_id"
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "interactive",
            "content": json.dumps(self._markdown_to_card(text), ensure_ascii=False),
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["message_id"]
        logger.error(f"[Feishu] Full-card send failed: {data}")
        return None

    def _index_topic_root(self, msg) -> None:
        """Records msg -> its topic root, so a later reply to this message
        is routed back into the same topic. Feishu marks in-topic messages
        with a non-empty root_id (reply-in-thread topics in normal chats) or
        thread_id (topic-group chats); other platforms' thread_id-style
        attributes are absent on Feishu messages."""
        topic_root = getattr(msg, "root_id", None) or getattr(msg, "thread_id", None)
        if topic_root:
            self._msg_threads[str(msg.message_id)] = str(topic_root)
            if len(self._msg_threads) > self._msg_threads_limit:
                self._msg_threads.pop(next(iter(self._msg_threads)))

    async def _send_reply_in_thread(
        self,
        chat_id: Union[int, str],
        text: str,
        headers: Dict[str, str],
        reply_to_msg_id: Union[int, str],
    ) -> Optional[Union[int, str]]:
        """Replies inside an existing topic via the reply API: replying to
        an in-topic message automatically lands in that topic. The topic
        itself is already the fold layer, so the full text is delivered as-is
        (no summary/thread nesting). Falls back to plain text if the card is
        rejected."""
        url = f"{self.api_base}/open-apis/im/v1/messages/{reply_to_msg_id}/reply"
        payload = {
            "msg_type": "interactive",
            "content": json.dumps(self._markdown_to_card(text), ensure_ascii=False),
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["message_id"]
        logger.warning(f"[Feishu] Topic reply failed ({data.get('msg')}); falling back to plain text")
        fallback = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        resp = await self.client.post(url, headers=headers, json=fallback)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["message_id"]
        logger.error(f"[Feishu] Thread reply failed: {data}")
        return None

    def _collapsible_card(self, text: str, summary: str) -> dict:
        """Single-card long reply: short summary readable directly, full text
        inside a native collapsible_panel that defaults to collapsed. The
        panel's expand/collapse is a local per-user client behavior, so no
        topics are created and no shared expanded state exists."""
        elements = []
        if summary:
            elements.append({"tag": "markdown", "text_align": "left", "content": summary + " ……"})
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "background_color": "grey",
            "header": {
                "title": {"tag": "markdown", "content": "**展开全文**"},
                "vertical_align": "center",
                "icon": {
                    "tag": "standard_icon",
                    "token": "down-small-ccm_outlined",
                    "color": "grey",
                    "size": "16px 16px",
                },
                "icon_position": "right",
                "icon_expanded_angle": -180,
            },
            "border": {"color": "grey", "corner_radius": "5px"},
            "vertical_spacing": "8px",
            "padding": "8px",
            "elements": FeishuChannel._markdown_body_elements(text),
        })
        return FeishuChannel._card_shell(elements)

    async def _send_collapsible_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        headers: Dict[str, str],
    ) -> Optional[Union[int, str]]:
        """Over-threshold reply as a single card: short summary directly
        readable, full text inside a native collapsed collapsible_panel.
        Expand/collapse is local per user and defaults to collapsed, so long
        replies never create topics nor leave shared expanded residue.
        Fallback chain: collapsible card fails -> full card in the stream;
        full card fails -> plain text so the reply is never lost."""
        url = f"{self.api_base}/open-apis/im/v1/messages?receive_id_type=chat_id"
        summary = extract_first_paragraph(text)
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "interactive",
            "content": json.dumps(self._collapsible_card(text, summary), ensure_ascii=False),
        }
        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["message_id"]
        logger.warning(f"[Feishu] Collapsible card send failed ({data.get('msg')}); falling back to full card")
        msg_id = await self._send_full_card(chat_id, text, headers)
        if msg_id:
            return msg_id
        fallback = {
            "receive_id": str(chat_id),
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
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

    async def _download_resource(
        self,
        message_id: str,
        file_key: str,
        resource_type: str,
        dest_filename: str
    ) -> Optional[str]:
        try:
            safe_filename = os.path.basename(dest_filename)
            local_path = os.path.join(self.config.attachments_dir, safe_filename)
            if os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
                logger.debug(f"[Feishu] Attachment already exists locally: {local_path}")
                return local_path

            token = await self.get_tenant_access_token()
            url = f"{self.api_base}/open-apis/im/v1/messages/{message_id}/resources/{file_key}?type={resource_type}"
            headers = {"Authorization": f"Bearer {token}"}
            resp = await self.client.get(url, headers=headers, timeout=60.0)
            if resp.status_code == 200:
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"[Feishu] Successfully downloaded attachment to {local_path} ({len(resp.content)} bytes)")
                return local_path
            logger.error(f"[Feishu] Failed to download resource {file_key} (status {resp.status_code}): {resp.text}")
            return None
        except Exception as e:
            logger.error(f"[Feishu] Error downloading resource {file_key}: {e}", exc_info=True)
            return None

    def _build_event_handler(self):
        """Builds the SDK event dispatcher with the message-receive handler."""

        async def _handle_inbound_async(msg, sender):
            try:
                sender_id = sender.sender_id

                chat_id = msg.chat_id
                chat_type = msg.chat_type or "group"
                if chat_type == "p2p":
                    chat_type = "private"

                # Remember which topic a message belongs to, so replies to it
                # stay inside the same topic instead of leaking to the main
                # stream.
                self._index_topic_root(msg)

                msg_type = getattr(msg, "message_type", None) or getattr(msg, "msg_type", "text")
                create_time = getattr(msg, "create_time", None) or str(int(time.time() * 1000))

                raw_content = msg.content or "{}"
                content_json = {}
                try:
                    content_json = json.loads(raw_content)
                except Exception:
                    pass

                text = ""
                attachments = []

                if msg_type == "text":
                    text = content_json.get("text", "") if isinstance(content_json, dict) else raw_content
                elif msg_type == "file":
                    file_key = content_json.get("file_key")
                    file_name = content_json.get("file_name", "file")
                    if file_key:
                        fname = f"{create_time}_{chat_id}_{msg.message_id}_{file_name}"
                        local_path = await self._download_resource(msg.message_id, file_key, "file", fname)
                        if local_path:
                            attachments.append({"type": "document", "path": local_path, "name": file_name})
                            text = f"[Document Attachment: {file_name}]"
                elif msg_type == "image":
                    image_key = content_json.get("image_key")
                    if image_key:
                        fname = f"{create_time}_{chat_id}_{msg.message_id}_{image_key}.jpg"
                        local_path = await self._download_resource(msg.message_id, image_key, "image", fname)
                        if local_path:
                            attachments.append({"type": "photo", "path": local_path, "name": fname})
                            text = "[Photo Attachment]"
                elif msg_type == "audio":
                    file_key = content_json.get("file_key")
                    if file_key:
                        fname = f"{create_time}_{chat_id}_{msg.message_id}_audio.opus"
                        local_path = await self._download_resource(msg.message_id, file_key, "file", fname)
                        if local_path:
                            attachments.append({"type": "voice", "path": local_path, "name": fname})
                            text = "[Voice Audio Attachment]"
                elif msg_type == "media":
                    file_key = content_json.get("file_key")
                    file_name = content_json.get("file_name", "video.mp4")
                    if file_key:
                        fname = f"{create_time}_{chat_id}_{msg.message_id}_{file_name}"
                        local_path = await self._download_resource(msg.message_id, file_key, "file", fname)
                        if local_path:
                            attachments.append({"type": "video", "path": local_path, "name": file_name})
                            text = f"[Video Attachment: {file_name}]"
                elif msg_type == "post":
                    post_text_parts = []
                    if isinstance(content_json, dict):
                        for lang, post_data in content_json.items():
                            if isinstance(post_data, dict):
                                title = post_data.get("title", "")
                                if title:
                                    post_text_parts.append(title)
                                for paragraph in post_data.get("content", []):
                                    p_text = "".join(elem.get("text", "") for elem in paragraph if isinstance(elem, dict) and elem.get("tag") == "text")
                                    if p_text:
                                        post_text_parts.append(p_text)
                    text = "\n".join(post_text_parts) if post_text_parts else raw_content
                else:
                    text = content_json.get("text", "") if isinstance(content_json, dict) else raw_content

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
                    attachments=attachments,
                )
                await self.handler(inbound)
            except Exception as e:
                logger.error(f"[Feishu] Error processing inbound message: {e}", exc_info=True)

        def _on_message_receive(data):
            try:
                event = data.event
                msg = event.message
                sender = event.sender
                asyncio.get_event_loop().create_task(_handle_inbound_async(msg, sender))
            except Exception as e:
                logger.error(f"[Feishu] Error dispatching message event: {e}", exc_info=True)


        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(_on_message_receive)
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
