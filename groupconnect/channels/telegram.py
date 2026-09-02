"""
Telegram Platform Channel for GroupAgent.
Implements long polling, multimodal media downloads, typing heartbeats, and Markdown auto-fallback.
"""

import asyncio
import datetime
import json
import logging
import os
import re
from typing import Any, Callable, Coroutine, Dict, List, Optional
import httpx

from groupconnect.channels.base import BaseChannel, InboundMessage
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig
from groupconnect.core.context import format_sender

logger = logging.getLogger("groupconnect.channel.telegram")


class TelegramChannel(BaseChannel):
    """Full-featured Telegram Bot API Channel."""

    def __init__(
        self,
        config: GatewayConfig,
        on_message_callback: Callable[[InboundMessage], Coroutine[Any, Any, None]]
    ):
        self.config = config
        self.on_message_callback = on_message_callback
        self.bot_token = config.bot_token
        self.bot_username = config.bot_username.lower().lstrip("@")
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}"
        self.client: Optional[httpx.AsyncClient] = None
        self.bot_info: Dict[str, Any] = {}
        self.is_running = False

    async def start(self) -> None:
        self.client = httpx.AsyncClient(timeout=35.0)
        self.is_running = True

        # Verify bot token
        try:
            r = await self.client.get(f"{self.api_base}/getMe")
            data = r.json()
            if not data.get("ok"):
                raise ValueError(f"Failed to authenticate bot token: {data}")
            self.bot_info = data["result"]
            actual_username = self.bot_info.get("username", "").lower()
            if actual_username:
                self.bot_username = actual_username
            logger.info(f"Connected to Telegram API: @{self.bot_username} (ID: {self.bot_info.get('id')})")
        except Exception as e:
            logger.error(f"Telegram connection error: {e}")
            raise

        # Main Polling Loop
        offset = 0
        backoff = 1

        while self.is_running:
            try:
                params = {
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": json.dumps(["message", "edited_message", "my_chat_member"])
                }
                r = await self.client.get(f"{self.api_base}/getUpdates", params=params, timeout=35.0)
                if r.status_code == 200:
                    backoff = 1
                    res = r.json()
                    if res.get("ok"):
                        updates = res.get("result", [])
                        for update in updates:
                            update_id = update["update_id"]
                            offset = max(offset, update_id + 1)
                            asyncio.create_task(self._process_raw_update(update))
                elif r.status_code == 409:
                    logger.warning("Telegram conflict: Another bot instance is polling. Backing off 5s...")
                    await asyncio.sleep(5)
                else:
                    logger.warning(f"Telegram getUpdates returned {r.status_code}: {r.text}")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Telegram polling exception: {e}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _process_raw_update(self, update: Dict[str, Any]) -> None:
        # Check if bot was added to / removed from chat
        my_chat_member = update.get("my_chat_member")
        if my_chat_member:
            chat = my_chat_member.get("chat", {})
            chat_id = chat.get("id")
            new_status = my_chat_member.get("new_chat_member", {}).get("status")
            if new_status in ("member", "administrator"):
                if self.config.allowed_chat_ids and chat_id not in self.config.allowed_chat_ids:
                    logger.warning(f"[SECURITY] Bot added to unauthorized chat {chat_id} ({chat.get('title')}). Leaving...")
                    await self.leave_chat(chat_id)
            return

        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")
        if not chat_id:
            return

        from_user = msg.get("from", {})
        sender_name = format_sender(from_user)

        # Download attachments
        attachments = await self._extract_and_download_attachments(msg)

        # Handle reply message attachments
        reply_attachments = []
        reply_msg = msg.get("reply_to_message")
        reply_preview = ""
        reply_to_msg_id = None
        if reply_msg:
            reply_to_msg_id = reply_msg.get("message_id")
            reply_attachments = await self._extract_and_download_attachments(reply_msg)
            r_sender = format_sender(reply_msg.get("from", {}))
            r_text = self._extract_message_text(reply_msg, reply_attachments)
            reply_preview = f"{r_sender}: {r_text[:60]}..." if len(r_text) > 60 else f"{r_sender}: {r_text}"

        text = self._extract_message_text(msg, attachments)
        triggered = self._is_bot_triggered(msg, text)

        inbound = InboundMessage(
            chat_id=chat_id,
            chat_type=chat_type,
            msg_id=msg.get("message_id", 0),
            sender_name=sender_name,
            from_user=from_user,
            text=text,
            reply_to_msg_id=reply_to_msg_id,
            reply_preview=reply_preview,
            is_triggered=triggered,
            attachments=attachments,
            reply_attachments=reply_attachments
        )

        await self.on_message_callback(inbound)

    def _is_bot_triggered(self, msg: Dict[str, Any], text: str) -> bool:
        chat = msg.get("chat", {})
        chat_type = chat.get("type", "private")

        if chat_type == "private":
            return True

        reply_to = msg.get("reply_to_message")
        if reply_to:
            reply_from = reply_to.get("from", {})
            if reply_from.get("id") == self.bot_info.get("id") or reply_from.get("username", "").lower() == self.bot_username:
                return True

        if f"@{self.bot_username}" in text.lower():
            return True

        entities = msg.get("entities") or msg.get("caption_entities") or []
        for ent in entities:
            if ent.get("type") == "mention":
                offset = ent.get("offset", 0)
                length = ent.get("length", 0)
                mention_name = text[offset:offset+length].lower().lstrip("@")
                if mention_name == self.bot_username:
                    return True
            elif ent.get("type") == "bot_command":
                offset = ent.get("offset", 0)
                length = ent.get("length", 0)
                cmd_text = text[offset:offset+length]
                if cmd_text.startswith("/"):
                    cmd_clean, target_bot, _ = parse_bot_command(cmd_text, self.bot_username)
                    if cmd_clean and (target_bot is None or target_bot == self.bot_username):
                        return True

        return False

    def _extract_message_text(self, msg: Dict[str, Any], attachments: Optional[List[Dict[str, Any]]] = None) -> str:
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if attachments:
            att_parts = []
            for att in attachments:
                if att["type"] == "photo":
                    att_parts.append(f"[Photo Attachment: {att['path']}]")
                elif att["type"] == "voice":
                    att_parts.append(f"[Voice Attachment: {att['path']}]")
                else:
                    att_parts.append(f"[File Attachment: {att.get('name', 'file')} -> {att['path']}]")
            att_desc = " ".join(att_parts)
            if text:
                return f"{att_desc} {text}"
            return att_desc

        if not text:
            if "photo" in msg:
                return "[Photo]"
            if "document" in msg:
                return f"[Document: {msg['document'].get('file_name', 'Unnamed')}]"
            if "voice" in msg:
                return "[Voice Message]"
            if "audio" in msg:
                return f"[Audio: {msg['audio'].get('file_name', 'Audio')}]"
            if "video" in msg:
                return "[Video Message]"
            return "[Media Message]"
        return text

    async def _download_telegram_file(self, file_id: str, suggested_name: str) -> Optional[str]:
        try:
            r = await self.client.get(f"{self.api_base}/getFile", params={"file_id": file_id}, timeout=20.0)
            data = r.json()
            if not data.get("ok"):
                return None
            file_path = data["result"].get("file_path")
            if not file_path:
                return None

            ext = os.path.splitext(file_path)[1]
            if not ext and "." in suggested_name:
                ext = os.path.splitext(suggested_name)[1]

            base_name = os.path.splitext(os.path.basename(suggested_name))[0] or "attachment"
            safe_base = re.sub(r"[^\w\-_\.]", "_", base_name)[:50]
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            local_filename = f"{timestamp}_{safe_base}{ext}"
            local_path = os.path.join(self.config.attachments_dir, local_filename)

            download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"
            r_file = await self.client.get(download_url, timeout=60.0)
            if r_file.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(r_file.content)
                logger.info(f"Downloaded media attachment to {local_path} ({len(r_file.content)} bytes)")
                return local_path
            return None
        except Exception as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            return None

    async def _extract_and_download_attachments(self, msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        attachments = []

        # Photos
        if "photo" in msg and msg["photo"]:
            best_photo = msg["photo"][-1]
            file_id = best_photo.get("file_id")
            if file_id:
                local_path = await self._download_telegram_file(file_id, "photo.jpg")
                if local_path:
                    attachments.append({"type": "photo", "path": local_path, "name": os.path.basename(local_path), "file_id": file_id})

        # Documents
        if "document" in msg:
            doc = msg["document"]
            file_id = doc.get("file_id")
            file_name = doc.get("file_name", "document.bin")
            mime_type = doc.get("mime_type", "")
            if file_id:
                local_path = await self._download_telegram_file(file_id, file_name)
                if local_path:
                    doc_type = "photo" if (mime_type.startswith("image/") or file_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))) else "document"
                    attachments.append({"type": doc_type, "path": local_path, "name": file_name, "mime_type": mime_type, "file_id": file_id})

        # Voice
        if "voice" in msg:
            file_id = msg["voice"].get("file_id")
            if file_id:
                local_path = await self._download_telegram_file(file_id, "voice.ogg")
                if local_path:
                    attachments.append({"type": "voice", "path": local_path, "name": os.path.basename(local_path), "file_id": file_id})

        return attachments

    async def send_reply(self, chat_id: int, text: str, reply_to_msg_id: Optional[int] = None) -> int:
        max_chunk = min(self.config.max_chunk_size, 4000)
        chunks = []
        if len(text) <= max_chunk:
            chunks = [text]
        else:
            parts = text.split("\n\n")
            cur_chunk = ""
            for part in parts:
                if len(cur_chunk) + len(part) + 2 <= max_chunk:
                    cur_chunk = f"{cur_chunk}\n\n{part}".strip()
                else:
                    if cur_chunk:
                        chunks.append(cur_chunk)
                    if len(part) <= max_chunk:
                        cur_chunk = part
                    else:
                        for i in range(0, len(part), max_chunk):
                            chunks.append(part[i:i+max_chunk])
                        cur_chunk = ""
            if cur_chunk:
                chunks.append(cur_chunk)

        last_sent_msg_id = 0
        for idx, chunk in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }
            if idx == 0 and reply_to_msg_id:
                payload["reply_to_message_id"] = reply_to_msg_id

            try:
                r = await self.client.post(f"{self.api_base}/sendMessage", json=payload, timeout=15.0)
                data = r.json()
                if data.get("ok"):
                    last_sent_msg_id = data["result"].get("message_id", 0)
                else:
                    # Markdown syntax degradation fallback
                    payload.pop("parse_mode", None)
                    r_fb = await self.client.post(f"{self.api_base}/sendMessage", json=payload, timeout=15.0)
                    data_fb = r_fb.json()
                    if data_fb.get("ok"):
                        last_sent_msg_id = data_fb["result"].get("message_id", 0)
            except Exception as e:
                logger.error(f"Error sending message chunk: {e}")
                try:
                    payload.pop("parse_mode", None)
                    r_fb = await self.client.post(f"{self.api_base}/sendMessage", json=payload, timeout=15.0)
                    data_fb = r_fb.json()
                    if data_fb.get("ok"):
                        last_sent_msg_id = data_fb["result"].get("message_id", 0)
                except Exception as ex:
                    logger.error(f"Fallback send failed: {ex}")

        return last_sent_msg_id

    async def send_typing_action(self, chat_id: int) -> None:
        try:
            await self.client.post(
                f"{self.api_base}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
                timeout=5.0
            )
        except Exception:
            pass

    async def leave_chat(self, chat_id: int) -> bool:
        try:
            r = await self.client.post(f"{self.api_base}/leaveChat", json={"chat_id": chat_id}, timeout=10.0)
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"Failed to leave chat {chat_id}: {e}")
            return False

    async def check_user_membership(self, group_chat_id: int, user_id: int) -> bool:
        try:
            r = await self.client.get(
                f"{self.api_base}/getChatMember",
                params={"chat_id": group_chat_id, "user_id": user_id},
                timeout=8.0
            )
            if r.status_code == 200:
                data = r.json()
                if data.get("ok"):
                    status = data.get("result", {}).get("status")
                    return status in ("creator", "administrator", "member", "restricted")
            return False
        except Exception:
            return False
