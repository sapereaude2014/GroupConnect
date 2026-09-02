"""
Feishu / Lark Platform Channel for GroupConnect.
Connects Feishu Open Platform bot API to core agent gateway.
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

logger = logging.getLogger("groupconnect.channel.feishu")


class FeishuChannel(BaseChannel):
    """Channel adapter for Feishu (Lark) Open Platform."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.app_id = config.raw.get("feishu_app_id") or config.raw.get("app_id", "")
        self.app_secret = config.raw.get("feishu_app_secret") or config.raw.get("app_secret", "")
        self.api_base = config.raw.get("feishu_api_base", "https://open.feishu.cn")
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self.client = httpx.AsyncClient(timeout=30.0)
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
        # Feishu does not have an explicit typing indicator API endpoint
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

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Feishu Channel (App ID: {self.app_id})...")
        while self.is_running:
            await asyncio.sleep(1)
