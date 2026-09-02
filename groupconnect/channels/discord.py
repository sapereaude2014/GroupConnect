"""
Discord Platform Channel for GroupConnect.
Connects Discord Bot API (REST & Gateway/Webhook) to core agent gateway.
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

logger = logging.getLogger("groupconnect.channel.discord")


@register_channel(
    name="discord",
    display_name="Discord",
    aliases=["dc"],
    fields=[
        ChannelField(key="discord_bot_token", label="Discord Bot Token", is_secret=True),
        ChannelField(key="bot_username", label="Bot Client ID / Username", default="discord_bot"),
        ChannelField(key="webhook_port", label="Webhook listening port", default=8090, is_int=True)
    ]
)
class DiscordChannel(BaseChannel):
    """Channel adapter for Discord Bot API."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.bot_token = config.raw.get("discord_bot_token") or config.raw.get("bot_token", "")
        self.api_base = "https://discord.com/api/v10"
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name
        self.port = int(config.raw.get("webhook_port", config.raw.get("port", 8090)))

        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "Authorization": f"Bot {self.bot_token}",
                "Content-Type": "application/json"
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
        url = f"{self.api_base}/channels/{chat_id}/messages"
        payload = {"content": text}
        if reply_to_msg_id:
            payload["message_reference"] = {"message_id": str(reply_to_msg_id)}

        resp = await self.client.post(url, json=payload)
        data = resp.json()
        if resp.status_code in (200, 201):
            return data.get("id")
        logger.error(f"[Discord] Send message failed ({resp.status_code}): {data}")
        return None

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        try:
            url = f"{self.api_base}/channels/{chat_id}/typing"
            await self.client.post(url)
        except Exception as e:
            logger.debug(f"[Discord] Typing indicator error: {e}")

    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        try:
            url = f"{self.api_base}/users/@me/guilds/{chat_id}"
            resp = await self.client.delete(url)
            return resp.status_code == 204
        except Exception as e:
            logger.warning(f"[Discord] Failed to leave guild {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_id: Union[int, str], user_id: Union[int, str]) -> bool:
        try:
            url = f"{self.api_base}/guilds/{group_id}/members/{user_id}"
            resp = await self.client.get(url)
            return resp.status_code == 200
        except Exception as e:
            logger.warning(f"[Discord] Error checking guild membership: {e}")
            return False

    async def _handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles inbound Discord Interactions / Webhook events."""
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

            data = json.loads(body_str)

            # Discord PING (Type 1)
            if data.get("type") == 1:
                resp_bytes = json.dumps({"type": 1}).encode("utf-8")
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    + f"Content-Length: {len(resp_bytes)}\r\n\r\n".encode("utf-8")
                    + resp_bytes
                )
                await writer.drain()
                writer.close()
                return

            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()

            # Process Message Event
            msg = data.get("message") or data
            author = msg.get("author", {})
            if author.get("bot"):
                return

            text = msg.get("content", "")
            chat_id = msg.get("channel_id")
            guild_id = msg.get("guild_id")
            is_group = bool(guild_id)

            is_triggered = (not is_group) or (f"<@{self.bot_username}>" in text) or (f"@{self.bot_username}" in text)

            inbound = InboundMessage(
                chat_id=chat_id,
                chat_type="group" if is_group else "private",
                msg_id=msg.get("id", str(int(time.time() * 1000))),
                sender_name=author.get("username", "discord_user"),
                from_user={"id": author.get("id"), "username": author.get("username")},
                text=text,
                is_triggered=is_triggered
            )
            asyncio.create_task(self.handler(inbound))

        except Exception as e:
            logger.error(f"[Discord] Error handling webhook: {e}", exc_info=True)

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Discord Channel on port {self.port}...")
        self.server = await asyncio.start_server(self._handle_http_client, "0.0.0.0", self.port)
        async with self.server:
            await self.server.serve_forever()
