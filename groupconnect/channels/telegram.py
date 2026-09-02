"""
Telegram Platform Channel for GroupConnect.
Connects Telegram Bot API (Long-Polling & Webhooks) to core agent gateway.
"""

import asyncio
import logging
import os
import re
import sys
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.telegram")


@register_channel(
    name="telegram",
    display_name="Telegram",
    aliases=["tg"],
    fields=[
        ChannelField(key="bot_token", label="Telegram Bot Token (from @BotFather)", is_secret=True),
        ChannelField(key="bot_username", label="Bot Username (without @, e.g. my_bot)", default="my_group_bot")
    ]
)
class TelegramChannel(BaseChannel):
    """Channel adapter for Telegram Bot API using native long-polling."""

    def __init__(
        self,
        config: GatewayConfig,
        message_handler: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.handler = message_handler
        self.bot_token = config.bot_token
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self.file_api_base = f"https://api.telegram.org/file/bot{self.bot_token}"

        self.client = httpx.AsyncClient(timeout=60.0)
        self.is_running = False
        self.last_update_id = 0

    async def _api_call(self, method: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.api_base}/{method}"
        resp = await self.client.post(url, json=kwargs)
        return resp.json()

    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        try:
            await self._api_call("sendChatAction", chat_id=chat_id, action="typing")
        except Exception as e:
            logger.debug(f"Failed to send typing action: {e}")

    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        try:
            res = await self._api_call("leaveChat", chat_id=chat_id)
            return res.get("ok", False)
        except Exception as e:
            logger.warning(f"Failed to leave chat {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_id: Union[int, str], user_id: Union[int, str]) -> bool:
        try:
            res = await self._api_call("getChatMember", chat_id=group_id, user_id=user_id)
            if res.get("ok"):
                status = res["result"].get("status")
                return status in ("creator", "administrator", "member", "restricted")
            return False
        except Exception as e:
            logger.warning(f"Error checking membership for user {user_id} in {group_id}: {e}")
            return False

    async def send_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        chunks = self._split_message(text, max_len=self.config.max_chunk_size)
        last_sent_id = None

        for i, chunk in enumerate(chunks):
            target_reply_to = reply_to_msg_id if i == 0 else None
            # Try Markdown first
            res = await self._api_call(
                "sendMessage",
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
                reply_to_message_id=target_reply_to
            )
            # Markdown parse fallback: retry as plain text
            if not res.get("ok"):
                logger.warning(f"Markdown parse failed ({res.get('description')}). Retrying as plain text...")
                clean_chunk = self._strip_markdown(chunk)
                res = await self._api_call(
                    "sendMessage",
                    chat_id=chat_id,
                    text=clean_chunk,
                    reply_to_message_id=target_reply_to
                )

            if res.get("ok"):
                last_sent_id = res["result"]["message_id"]
            else:
                logger.error(f"Failed to deliver Telegram message chunk {i}: {res}")

        return last_sent_id

    def _split_message(self, text: str, max_len: int = 3800) -> List[str]:
        if len(text) <= max_len:
            return [text]

        chunks = []
        paragraphs = text.split("\n\n")
        current_chunk = ""

        for p in paragraphs:
            if len(current_chunk) + len(p) + 2 <= max_len:
                current_chunk = f"{current_chunk}\n\n{p}" if current_chunk else p
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                if len(p) <= max_len:
                    current_chunk = p
                else:
                    lines = p.split("\n")
                    sub_chunk = ""
                    for line in lines:
                        if len(sub_chunk) + len(line) + 1 <= max_len:
                            sub_chunk = f"{sub_chunk}\n{line}" if sub_chunk else line
                        else:
                            if sub_chunk:
                                chunks.append(sub_chunk)
                            while len(line) > max_len:
                                chunks.append(line[:max_len])
                                line = line[max_len:]
                            sub_chunk = line
                    current_chunk = sub_chunk

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _strip_markdown(self, text: str) -> str:
        s = re.sub(r"```[a-zA-Z0-9_-]*\n?(.*?)```", r"\1", text, flags=re.DOTALL)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        s = re.sub(r"__([^_]+)__", r"\1", s)
        s = re.sub(r"_([^_]+)_", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        return s

    async def _download_file(self, file_id: str, dest_filename: str) -> Optional[str]:
        try:
            res = await self._api_call("getFile", file_id=file_id)
            if not res.get("ok"):
                return None
            file_path = res["result"].get("file_path")
            if not file_path:
                return None

            download_url = f"{self.file_api_base}/{file_path}"
            resp = await self.client.get(download_url)
            if resp.status_code == 200:
                local_path = os.path.join(self.config.attachments_dir, dest_filename)
                with open(local_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Successfully downloaded attachment to {local_path}")
                return local_path
        except Exception as e:
            logger.error(f"Failed to download Telegram file {file_id}: {e}")
        return None

    async def _process_update(self, update: Dict[str, Any]) -> None:
        msg = update.get("message")
        if not msg:
            return

        chat_id = msg["chat"]["id"]
        chat_type = msg["chat"]["type"]  # 'private', 'group', 'supergroup', 'channel'
        msg_id = msg["message_id"]
        from_user = msg.get("from", {})
        sender_name = from_user.get("first_name", "")
        if from_user.get("last_name"):
            sender_name += f" {from_user.get('last_name')}"
        if from_user.get("username"):
            sender_name += f" (@{from_user.get('username')})"

        raw_text = msg.get("text") or msg.get("caption") or ""
        reply_to = msg.get("reply_to_message")
        reply_to_msg_id = reply_to.get("message_id") if reply_to else None
        reply_preview = (reply_to.get("text") or reply_to.get("caption") or "") if reply_to else ""

        # Check Trigger Status
        is_triggered = False
        if chat_type == "private":
            is_triggered = True
        else:
            bot_tag = f"@{self.bot_username}"
            if bot_tag.lower() in raw_text.lower():
                is_triggered = True
            elif reply_to and reply_to.get("from", {}).get("username", "").lower() == self.bot_username.lower():
                is_triggered = True
            elif raw_text.startswith("/"):
                cmd, target_bot, _ = parse_bot_command(raw_text, self.bot_username)
                if cmd and (target_bot is None or target_bot.lower() == self.bot_username.lower()):
                    is_triggered = True

        # Process Media Attachments
        attachments = []
        now_ts = int(time.time())

        # Photos (take highest resolution)
        if "photo" in msg:
            highest_photo = msg["photo"][-1]
            fid = highest_photo["file_id"]
            fname = f"{now_ts}_{chat_id}_{msg_id}_photo.jpg"
            local_path = await self._download_file(fid, fname)
            if local_path:
                attachments.append({"type": "photo", "path": local_path, "name": fname})
                if not raw_text:
                    raw_text = "[Photo Attachment]"

        # Voice Notes
        if "voice" in msg:
            fid = msg["voice"]["file_id"]
            fname = f"{now_ts}_{chat_id}_{msg_id}_voice.ogg"
            local_path = await self._download_file(fid, fname)
            if local_path:
                attachments.append({"type": "voice", "path": local_path, "name": fname})
                if not raw_text:
                    raw_text = "[Voice Audio Attachment]"

        # Documents
        if "document" in msg:
            doc = msg["document"]
            fid = doc["file_id"]
            orig_name = doc.get("file_name", "file")
            fname = f"{now_ts}_{chat_id}_{msg_id}_{orig_name}"
            local_path = await self._download_file(fid, fname)
            if local_path:
                attachments.append({"type": "document", "path": local_path, "name": orig_name})
                if not raw_text:
                    raw_text = f"[Document Attachment: {orig_name}]"

        # Reply Attachments
        reply_attachments = []
        if reply_to and "photo" in reply_to:
            r_photo = reply_to["photo"][-1]
            r_fid = r_photo["file_id"]
            r_fname = f"reply_{now_ts}_{chat_id}_{reply_to['message_id']}_photo.jpg"
            r_path = await self._download_file(r_fid, r_fname)
            if r_path:
                reply_attachments.append({"type": "photo", "path": r_path, "name": r_fname})

        inbound = InboundMessage(
            chat_id=chat_id,
            chat_type=chat_type,
            msg_id=msg_id,
            sender_name=sender_name,
            from_user=from_user,
            text=raw_text,
            reply_to_msg_id=reply_to_msg_id,
            reply_preview=reply_preview,
            is_triggered=is_triggered,
            attachments=attachments,
            reply_attachments=reply_attachments
        )

        asyncio.create_task(self.handler(inbound))

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Telegram Long-Polling Listener (@{self.bot_username})...")

        while self.is_running:
            try:
                res = await self._api_call(
                    "getUpdates",
                    offset=self.last_update_id + 1,
                    timeout=30,
                    allowed_updates=["message"]
                )
                if not res.get("ok"):
                    logger.warning(f"Telegram getUpdates returned error: {res}")
                    await asyncio.sleep(3)
                    continue

                for update in res.get("result", []):
                    self.last_update_id = max(self.last_update_id, update["update_id"])
                    await self._process_update(update)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Telegram long-polling loop: {e}")
                await asyncio.sleep(3)
