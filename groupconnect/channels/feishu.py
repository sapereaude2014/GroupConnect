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
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)
        }
        if reply_to_msg_id:
            payload["reply_in_thread"] = False

        resp = await self.client.post(url, headers=headers, json=payload)
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
        """Builds the SDK event dispatcher with the message-receive handler."""
        # NOTE: In lark-oapi >=1.4, register_* methods live on the builder
        # (returning self for chaining), not on the built handler object.

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
