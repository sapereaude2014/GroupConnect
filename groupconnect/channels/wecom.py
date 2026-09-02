"""
WeCom (WeChat Work / 企业微信) Platform Channel for GroupConnect.
Supports Enterprise Self-Built App API and Intelligent Bot Webhook integrations.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, InboundMessage
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.wecom")


class WeComChannel(BaseChannel):
    """Channel adapter for WeCom (Enterprise WeChat)."""

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
        self.api_base = config.raw.get("wecom_api_base", "https://qyapi.weixin.qq.com")
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
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

        # If chat_id starts with 'wrk' or 'chat', send to appchat; otherwise send to touser
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
        # WeCom does not provide typing action API
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

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting WeCom Channel (CorpID: {self.corp_id}, AgentID: {self.agent_id})...")
        while self.is_running:
            await asyncio.sleep(1)
