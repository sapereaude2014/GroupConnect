"""
WeCom (WeChat Work / 企业微信) Platform Channel for GroupConnect.
Supports Enterprise Self-Built App API and Webhook callback listener.
"""

import asyncio
import json
import logging
import os
import re
import time
import urllib.parse
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.wecom")


@register_channel(
    name="wecom",
    display_name="WeCom (企业微信)",
    aliases=["wechat", "wework", "weixin"],
    fields=[
        ChannelField(key="wecom_corp_id", label="WeCom Corp ID (ww...)", is_secret=False),
        ChannelField(key="wecom_corp_secret", label="WeCom App Secret", is_secret=True),
        ChannelField(key="wecom_agent_id", label="WeCom Agent ID [e.g. 1000002]", default="1000002"),
        ChannelField(key="webhook_port", label="Webhook listening port", default=8089, is_int=True)
    ]
)
class WeComChannel(BaseChannel):
    """Channel adapter for WeCom (Enterprise WeChat) with built-in Webhook receiver."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.corp_id = config.raw.get("wecom_corp_id") or config.raw.get("corp_id", "")
        self.corp_secret = config.raw.get("wecom_corp_secret") or config.raw.get("corp_secret", "")
        self.agent_id = config.raw.get("wecom_agent_id") or config.raw.get("agent_id", "")
        self.port = int(config.raw.get("webhook_port", config.raw.get("port", 8089)))
        self.api_base = config.raw.get("wecom_api_base", "https://qyapi.weixin.qq.com")
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
        self.server = None
        self.is_running = False

    async def get_access_token(self) -> str:
        """Retrieves and caches WeCom access_token."""
        now = time.time()
        if self._token and now < self._token_expires_at - 60:
            return self._token

        url = f"{self.api_base}/cgi-bin/gettoken?corpid={self.corp_id}&corpsecret={self.corp_secret}"
        resp = await self.client.get(url)
        data = resp.json()
        if data.get("errcode") == 0:
            self._token = data.get("access_token")
            self._token_expires_at = now + data.get("expires_in", 7200)
            return self._token
        raise RuntimeError(f"Failed to get WeCom access_token: {data}")

    async def send_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        token = await self.get_access_token()
        url = f"{self.api_base}/cgi-bin/message/send?access_token={token}"

        cid_str = str(chat_id)
        payload = {
            "msgtype": "text",
            "agentid": self.agent_id,
            "text": {"content": text},
            "safe": 0
        }

        if cid_str.startswith("wrk") or cid_str.startswith("chat"):
            payload["chatid"] = cid_str
        else:
            payload["touser"] = cid_str

        resp = await self.client.post(url, json=payload)
        data = resp.json()
        if data.get("errcode") == 0:
            return data.get("msgid", str(int(time.time() * 1000)))
        logger.error(f"[WeCom] Send message failed: {data}")
        return None

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        pass

    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        try:
            token = await self.get_access_token()
            url = f"{self.api_base}/cgi-bin/appchat/update?access_token={token}"
            payload = {
                "chatid": str(chat_id),
                "del_user_list": [str(self.bot_username)]
            }
            resp = await self.client.post(url, json=payload)
            data = resp.json()
            return data.get("errcode") == 0
        except Exception as e:
            logger.warning(f"[WeCom] Failed to leave chat {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_id: Union[int, str], user_id: Union[int, str]) -> bool:
        try:
            token = await self.get_access_token()
            url = f"{self.api_base}/cgi-bin/appchat/get?access_token={token}&chatid={group_id}"
            resp = await self.client.get(url)
            data = resp.json()
            if data.get("errcode") == 0:
                userlist = data.get("chat_info", {}).get("userlist", [])
                return str(user_id) in [str(u) for u in userlist]
            return False
        except Exception as e:
            logger.warning(f"[WeCom] Failed to check user membership: {e}")
            return False

    async def _handle_http_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles inbound WeCom Webhook HTTP callbacks (GET verification and POST events)."""
        try:
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                return

            req_str = request_line.decode("utf-8", errors="replace").strip()
            parts = req_str.split(" ")
            method = parts[0] if parts else "GET"
            path = parts[1] if len(parts) > 1 else "/"

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

            # 1. WeCom URL GET verification (echostr echo)
            if method == "GET":
                parsed = urllib.parse.urlparse(path)
                qs = urllib.parse.parse_qs(parsed.query)
                echostr = qs.get("echostr", [""])[0]
                resp_bytes = echostr.encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/plain; charset=utf-8\r\n"
                    + f"Content-Length: {len(resp_bytes)}\r\n\r\n".encode("utf-8")
                    + resp_bytes
                )
                writer.write(response)
                await writer.drain()
                writer.close()
                return

            # 2. WeCom Message Event POST
            body_bytes = await reader.readexactly(content_length) if content_length > 0 else b""
            body_str = body_bytes.decode("utf-8", errors="replace")

            response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
            writer.write(response)
            await writer.drain()
            writer.close()

            # Parse XML/JSON payload
            from_user_match = re.search(r"<FromUserName><!\[CDATA\[(.*?)\]\]></FromUserName>", body_str)
            content_match = re.search(r"<Content><!\[CDATA\[(.*?)\]\]></Content>", body_str)
            msg_type_match = re.search(r"<MsgType><!\[CDATA\[(.*?)\]\]></MsgType>", body_str)
            chat_id_match = re.search(r"<ChatId><!\[CDATA\[(.*?)\]\]></ChatId>", body_str)

            sender_id = from_user_match.group(1) if from_user_match else "wecom_user"
            text = content_match.group(1) if content_match else ""
            msg_type = msg_type_match.group(1) if msg_type_match else "text"
            chat_id = chat_id_match.group(1) if chat_id_match else sender_id
            is_group = bool(chat_id_match)

            is_triggered = (not is_group) or (f"@{self.bot_username}" in text) or (f"@{self.bot_name}" in text)

            inbound = InboundMessage(
                chat_id=chat_id,
                chat_type="group" if is_group else "private",
                msg_id=str(int(time.time() * 1000)),
                sender_name=sender_id,
                from_user={"id": sender_id, "username": sender_id},
                text=text,
                is_triggered=is_triggered
            )
            asyncio.create_task(self.handler(inbound))

        except Exception as e:
            logger.error(f"[WeCom] Error handling webhook request: {e}", exc_info=True)

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting WeCom Webhook Server on port {self.port} (CorpID: {self.corp_id})...")
        self.server = await asyncio.start_server(self._handle_http_client, "0.0.0.0", self.port)
        async with self.server:
            await self.server.serve_forever()
