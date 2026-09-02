"""
Slack Platform Channel for GroupConnect.
Connects Slack Web API & Events API webhook listener to core agent gateway.
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

logger = logging.getLogger("groupconnect.channel.slack")


@register_channel(
    name="slack",
    display_name="Slack",
    aliases=[],
    fields=[
        ChannelField(key="slack_bot_token", label="Slack Bot User OAuth Token (xoxb-...)", is_secret=True),
        ChannelField(key="bot_username", label="Slack Bot User ID / Name", default="slack_bot"),
        ChannelField(key="webhook_port", label="Webhook listening port", default=8091, is_int=True)
    ]
)
class SlackChannel(BaseChannel):
    """Channel adapter for Slack Web API and Events API."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.bot_token = config.raw.get("slack_bot_token") or config.raw.get("bot_token", "")
        self.api_base = "https://slack.com/api"
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name
        self.port = int(config.raw.get("webhook_port", config.raw.get("port", 8091)))

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {self.bot_token}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )
        self.server = None
        self.is_running = False

    async def send_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        url = f"{self.api_base}/chat.postMessage"
        payload = {
            "channel": str(chat_id),
            "text": text
        }
        if reply_to_msg_id:
            payload["thread_ts"] = str(reply_to_msg_id)

        resp = await self.client.post(url, json=payload)
        data = resp.json()
        if data.get("ok"):
            return data.get("ts")
        logger.error(f"[Slack] Send message failed: {data}")
        return None

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        pass

    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        try:
            url = f"{self.api_base}/conversations.leave"
            resp = await self.client.post(url, json={"channel": str(chat_id)})
            data = resp.json()
            return bool(data.get("ok"))
        except Exception as e:
            logger.warning(f"[Slack] Failed to leave channel {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_id: Union[int, str], user_id: Union[int, str]) -> bool:
        try:
            url = f"{self.api_base}/conversations.members"
            resp = await self.client.get(url, params={"channel": str(group_id)})
            data = resp.json()
            if data.get("ok"):
                members = data.get("members", [])
                return str(user_id) in [str(m) for m in members]
            return False
        except Exception as e:
            logger.warning(f"[Slack] Failed to check channel membership: {e}")
            return False

    async def _handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles inbound Slack Events API Webhook callbacks (URL verification & events)."""
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
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                writer.close()
                return

            event_data = json.loads(body_str)

            # 1. Slack URL Challenge Verification
            if event_data.get("type") == "url_verification" and "challenge" in event_data:
                resp_payload = json.dumps({"challenge": event_data["challenge"]}).encode("utf-8")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
                    + f"Content-Length: {len(resp_payload)}\r\n\r\n".encode("utf-8")
                    + resp_payload
                )
                await writer.drain()
                writer.close()
                return

            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()

            # 2. Process Event Callback
            if event_data.get("type") == "event_callback":
                event = event_data.get("event", {})
                if event.get("bot_id") or event.get("subtype") == "bot_message":
                    return

                chat_id = event.get("channel")
                channel_type = event.get("channel_type", "channel")
                user_id = event.get("user", "slack_user")
                text = event.get("text", "")
                is_group = channel_type in ("channel", "group")

                is_triggered = (not is_group) or (f"<@{self.bot_username}>" in text) or (f"@{self.bot_username}" in text) or (event.get("type") == "app_mention")

                inbound = InboundMessage(
                    chat_id=chat_id,
                    chat_type="group" if is_group else "private",
                    msg_id=event.get("ts", str(int(time.time() * 1000))),
                    sender_name=user_id,
                    from_user={"id": user_id, "username": user_id},
                    text=text,
                    is_triggered=is_triggered
                )
                asyncio.create_task(self.handler(inbound))

        except Exception as e:
            logger.error(f"[Slack] Error handling webhook: {e}", exc_info=True)

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Slack Events Webhook Server on port {self.port}...")
        self.server = await asyncio.start_server(self._handle_http_client, "0.0.0.0", self.port)
        async with self.server:
            await self.server.serve_forever()
