"""
Feishu / Lark Platform Channel for GroupConnect.
Connects Feishu Open Platform bot API & Webhook callback server to core agent gateway.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.feishu")


@register_channel(
    name="feishu",
    display_name="Feishu / Lark (飞书)",
    aliases=["lark"],
    fields=[
        ChannelField(key="feishu_app_id", label="Feishu App ID (cli_...)", is_secret=False),
        ChannelField(key="feishu_app_secret", label="Feishu App Secret", is_secret=True),
        ChannelField(key="webhook_port", label="Webhook listening port", default=8088, is_int=True)
    ]
)
class FeishuChannel(BaseChannel):
    """Channel adapter for Feishu (Lark) Open Platform with built-in Webhook listener."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.app_id = config.raw.get("feishu_app_id") or config.raw.get("app_id", "")
        self.app_secret = config.raw.get("feishu_app_secret") or config.raw.get("app_secret", "")
        self.verification_token = config.raw.get("feishu_verification_token", "")
        self.port = int(config.raw.get("webhook_port", config.raw.get("port", 8088)))
        self.api_base = config.raw.get("feishu_api_base", "https://open.feishu.cn")
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
        self.server = None
        self.is_running = False

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
        token = await self.get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}

        url = f"{self.api_base}/open-apis/im/v1/messages?receive_id_type=chat_id"
        payload = {
            "receive_id": str(chat_id),
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)
        }

        resp = await self.client.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get("code") == 0:
            return data["data"]["message_id"]
        logger.error(f"[Feishu] Send message failed: {data}")
        return None

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        pass

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

    async def _handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles inbound Feishu Webhook HTTP callbacks (URL verification & events)."""
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            headers = {}
            content_length = 0
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                header_str = line.decode("utf-8", errors="replace").strip()
                if ":" in header_str:
                    k, v = header_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        content_length = int(v.strip())

            body_bytes = await reader.readexactly(content_length) if content_length > 0 else b""
            body_str = body_bytes.decode("utf-8", errors="replace")

            if not body_str:
                response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
                writer.write(response)
                await writer.drain()
                writer.close()
                return

            try:
                event_data = json.loads(body_str)
            except json.JSONDecodeError:
                response = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
                writer.write(response)
                await writer.drain()
                writer.close()
                return

            # 1. Feishu URL Challenge Verification
            if event_data.get("type") == "url_verification" and "challenge" in event_data:
                resp_payload = json.dumps({"challenge": event_data["challenge"]}).encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json; charset=utf-8\r\n"
                    + f"Content-Length: {len(resp_payload)}\r\n\r\n".encode("utf-8")
                    + resp_payload
                )
                writer.write(response)
                await writer.drain()
                writer.close()
                return

            # Acknowledge HTTP 200 immediately
            response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
            writer.write(response)
            await writer.drain()
            writer.close()

            # 2. Process Feishu Message Event (im.message.receive_v1)
            header = event_data.get("header", {})
            if header.get("event_type") == "im.message.receive_v1":
                event = event_data.get("event", {})
                msg = event.get("message", {})
                sender = event.get("sender", {})
                sender_id = sender.get("sender_id", {})

                chat_id = msg.get("chat_id")
                chat_type = msg.get("chat_type", "group")  # 'p2p' or 'group'
                if chat_type == "p2p":
                    chat_type = "private"

                # Parse message content
                raw_content = msg.get("content", "{}")
                try:
                    content_json = json.loads(raw_content)
                    text = content_json.get("text", "")
                except Exception:
                    text = raw_content

                mentions = msg.get("mentions", [])
                is_mentioned = any(m.get("name") == self.bot_name or m.get("key") == "@_all" for m in mentions)
                is_triggered = (chat_type == "private") or is_mentioned or (f"@{self.bot_username}" in text)

                inbound = InboundMessage(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    msg_id=msg.get("message_id"),
                    sender_name=sender_id.get("user_id", "feishu_user"),
                    from_user={"id": sender_id.get("open_id") or sender_id.get("user_id"), "username": sender_id.get("user_id")},
                    text=text,
                    is_triggered=is_triggered
                )
                asyncio.create_task(self.handler(inbound))

        except Exception as e:
            logger.error(f"[Feishu] Error handling webhook request: {e}", exc_info=True)

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Feishu Webhook Server on port {self.port} (App ID: {self.app_id})...")
        self.server = await asyncio.start_server(self._handle_http_client, "0.0.0.0", self.port)
        async with self.server:
            await self.server.serve_forever()
