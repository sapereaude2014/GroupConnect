"""
Telegram Platform Channel for GroupConnect.
Connects Telegram Bot API (Long-Polling & Webhooks) to core agent gateway.
"""

import asyncio
import logging
import math
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


def _wgs84_to_gcj02(lon: float, lat: float) -> "tuple[float, float]":
    """Convert WGS-84 (GPS / Google global) coords to GCJ-02 (Amap / China datum).

    Uses the public GCJ-02 offset model. Points outside mainland China are
    returned unchanged, since GCJ-02 only applies within China.
    """
    if not (72.004 <= lon <= 137.8347 and 0.8293 <= lat <= 55.8271):
        return lon, lat
    a, ee = 6378245.0, 0.00669342162296594323
    x, y = lon - 105.0, lat - 35.0
    d_lat = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    d_lat += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lat += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    d_lat += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    d_lon = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    d_lon += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    d_lon += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    d_lon += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    rad_lat = lat / 180.0 * math.pi
    magic = 1 - ee * math.sin(rad_lat) ** 2
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    d_lon = (d_lon * 180.0) / (a / sqrt_magic * math.cos(rad_lat) * math.pi)
    return lon + d_lon, lat + d_lat


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

    async def _api_call(self, method: str, retries: int = 3, **kwargs) -> Dict[str, Any]:
        url = f"{self.api_base}/{method}"
        last_exc = None
        for attempt in range(retries):
            try:
                resp = await self.client.post(url, json=kwargs)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < retries - 1:
                    logger.warning(f"Telegram API {method} connection failed (attempt {attempt+1}/{retries}): {e}. Retrying in {attempt+1}s...")
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    logger.error(f"Telegram API {method} failed after {retries} attempts: {e}")
        if last_exc:
            raise last_exc
        return {"ok": False, "description": "Unknown API error"}

    async def _upload_file(
        self,
        method: str,
        chat_id: Union[int, str],
        file_field: str,
        file_path: str,
        caption: Optional[str] = None,
        reply_to_msg_id: Optional[Union[int, str]] = None,
        retries: int = 3
    ) -> Dict[str, Any]:
        url = f"{self.api_base}/{method}"
        data = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_msg_id:
            data["reply_to_message_id"] = str(reply_to_msg_id)

        filename = os.path.basename(file_path)
        last_exc = None
        for attempt in range(retries):
            try:
                with open(file_path, "rb") as f:
                    file_content = f.read()
                files = {file_field: (filename, file_content)}
                resp = await self.client.post(url, data=data, files=files, timeout=120.0)
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_exc = e
                if attempt < retries - 1:
                    logger.warning(f"Telegram upload {method} failed (attempt {attempt+1}/{retries}): {e}. Retrying...")
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    logger.error(f"Telegram upload {method} failed after {retries} attempts: {e}")
            except Exception as e:
                logger.error(f"Telegram upload {method} read error for {file_path}: {e}")
                return {"ok": False, "description": str(e)}
        if last_exc:
            raise last_exc
        return {"ok": False, "description": "Unknown upload error"}

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
            logger.warning(f"Failed to check membership for user {user_id} in {group_id}: {e}")
            return False

    async def send_reply(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        # Guard against empty text (TeleAgent can return empty on failures)
        if not text or not text.strip():
            text = "⚠️ 管家暂时没能生成回复，请稍后再试。"

        chunks = self._split_message(text, max_len=self.config.max_chunk_size)
        last_sent_id = None

        for i, chunk in enumerate(chunks):
            target_reply_to = reply_to_msg_id if i == 0 else None
            try:
                # Detect HTML blockquote for expandable fallback
                use_html = '<blockquote' in chunk
                if use_html:
                    res = await self._api_call(
                        "sendMessage",
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode="HTML",
                        reply_to_message_id=target_reply_to
                    )
                else:
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
                    desc = res.get('description', '')
                    logger.warning(f"Parse failed ({desc}). Retrying as plain text...")
                    clean_chunk = self._strip_markdown(chunk)
                    # If reply target was the problem (deleted/not found), drop it on retry
                    retry_reply_to = None if ('replied' in desc or 'not found' in desc) else target_reply_to
                    res = await self._api_call(
                        "sendMessage",
                        chat_id=chat_id,
                        text=clean_chunk,
                        reply_to_message_id=retry_reply_to
                    )

                if res.get("ok"):
                    last_sent_id = res["result"]["message_id"]
                else:
                    logger.error(f"Failed to deliver Telegram message chunk {i}: {res}")
            except Exception as e:
                logger.error(f"Failed to deliver Telegram message chunk {i} after retries: {e}")

        return last_sent_id

    async def send_file(
        self,
        chat_id: Union[int, str],
        file_path: str,
        caption: Optional[str] = None,
        reply_to_msg_id: Optional[Union[int, str]] = None
    ) -> Optional[Union[int, str]]:
        """Sends an outbound file/multimedia attachment to the specified chat."""
        if not os.path.isfile(file_path):
            logger.warning(f"send_file called with non-existent file: {file_path}")
            return None

        # Check Telegram Bot API 50MB limit
        file_size = os.path.getsize(file_path)
        if file_size > 50 * 1024 * 1024:
            logger.warning(f"File {file_path} ({file_size} bytes) exceeds Telegram 50MB bot upload limit")
            await self.send_reply(
                chat_id,
                f"⚠️ 文件超过 Telegram 50MB 大小限制，无法直接上传：`{os.path.basename(file_path)}`",
                reply_to_msg_id=reply_to_msg_id
            )
            return None

        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            method = "sendPhoto"
            field_name = "photo"
        elif ext in (".ogg", ".opus"):
            method = "sendVoice"
            field_name = "voice"
        elif ext in (".mp3", ".m4a", ".wav", ".flac", ".aac"):
            method = "sendAudio"
            field_name = "audio"
        elif ext in (".mp4", ".mov", ".mkv", ".webm"):
            method = "sendVideo"
            field_name = "video"
        elif ext == ".gif":
            method = "sendAnimation"
            field_name = "animation"
        else:
            method = "sendDocument"
            field_name = "document"

        try:
            res = await self._upload_file(
                method=method,
                chat_id=chat_id,
                file_field=field_name,
                file_path=file_path,
                caption=caption,
                reply_to_msg_id=reply_to_msg_id
            )
            # If specialized media endpoint failed, fallback to sendDocument
            if not res.get("ok") and method != "sendDocument":
                desc = res.get("description", "")
                logger.warning(f"{method} upload failed ({desc}), falling back to sendDocument for {file_path}...")
                res = await self._upload_file(
                    method="sendDocument",
                    chat_id=chat_id,
                    file_field="document",
                    file_path=file_path,
                    caption=caption,
                    reply_to_msg_id=reply_to_msg_id
                )

            if res.get("ok"):
                msg_id = res["result"]["message_id"]
                logger.info(f"Delivered outbound file {file_path} as {method} to chat {chat_id} (msg_id: {msg_id})")
                return msg_id
            else:
                logger.error(f"Failed to deliver file {file_path} to chat {chat_id}: {res}")
                return None
        except Exception as e:
            logger.error(f"Exception during outbound file delivery for {file_path}: {e}")
            return None

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
        # Strip HTML tags we may have injected (blockquote fallback) so a
        # plain-text retry never leaks raw tags into the chat.
        s = re.sub(r"</?blockquote[^>]*>", "", text)
        s = re.sub(r"```[a-zA-Z0-9_-]*\n?(.*?)```", r"\1", s, flags=re.DOTALL)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        s = re.sub(r"__([^_]+)__", r"\1", s)
        s = re.sub(r"_([^_]+)_", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        return s

    async def _resolve_address(self, lat: float, lon: float) -> str:
        """Reverse-geocode (lat, lon) into a human-readable address via Amap.

        Input coords are treated as WGS-84 (Google Maps / GPS origin) and
        converted to GCJ-02 before querying. Returns "" on any failure so the
        caller can fall back to raw coordinates.
        """
        key = getattr(self.config, "amap_key", "")
        if not key or lat is None or lon is None:
            return ""
        try:
            gcj_lon, gcj_lat = _wgs84_to_gcj02(float(lon), float(lat))
            resp = await self.client.get(
                "https://restapi.amap.com/v3/geocode/regeo",
                params={"location": f"{gcj_lon:.6f},{gcj_lat:.6f}", "key": key, "extensions": "base"},
                timeout=httpx.Timeout(3.0),
            )
            data = resp.json()
            if data.get("status") == "1":
                return str(data.get("regeocode", {}).get("formatted_address", "") or "")
            logger.warning(f"Amap regeo rejected ({lat}, {lon}): {data.get('info', '')}")
        except Exception as e:
            logger.warning(f"Amap regeo failed for ({lat}, {lon}): {e}")
        return ""

    async def _download_file(self, file_id: str, dest_filename: str) -> Optional[str]:
        try:
            local_path = os.path.join(self.config.attachments_dir, dest_filename)
            if os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
                logger.debug(f"Attachment already exists locally: {local_path}")
                return local_path

            res = await self._api_call("getFile", file_id=file_id)
            if not res.get("ok"):
                return None
            file_path = res["result"].get("file_path")
            if not file_path:
                return None

            download_url = f"{self.file_api_base}/{file_path}"
            resp = await self.client.get(download_url)
            if resp.status_code == 200:
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
        if not raw_text:
            if "location" in msg:
                loc = msg["location"]
                lat, lon = loc.get("latitude"), loc.get("longitude")
                addr = await self._resolve_address(lat, lon)
                raw_text = (
                    f"[Location: {addr} (lat={lat}, lon={lon})]"
                    if addr else f"[Location: lat={lat}, lon={lon}]"
                )
            elif "venue" in msg:
                venue = msg["venue"]
                title = venue.get("title", "")
                address = venue.get("address", "")
                vloc = venue.get("location", {})
                if not address:
                    address = await self._resolve_address(vloc.get("latitude"), vloc.get("longitude"))
                raw_text = f"[Venue: {title} ({address}), lat={vloc.get('latitude')}, lon={vloc.get('longitude')}]"
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

        # Process Media Attachments (deterministic filename via msg date to deduplicate across bots)
        attachments = []
        msg_date = msg.get("date", int(time.time()))

        # Photos (take highest resolution)
        if "photo" in msg:
            highest_photo = msg["photo"][-1]
            fid = highest_photo["file_id"]
            fname = f"{msg_date}_{chat_id}_{msg_id}_photo.jpg"
            local_path = await self._download_file(fid, fname)
            if local_path:
                attachments.append({"type": "photo", "path": local_path, "name": fname})
                if not raw_text:
                    raw_text = "[Photo Attachment]"

        # Voice Notes
        if "voice" in msg:
            fid = msg["voice"]["file_id"]
            fname = f"{msg_date}_{chat_id}_{msg_id}_voice.ogg"
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
            fname = f"{msg_date}_{chat_id}_{msg_id}_{orig_name}"
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
            r_date = reply_to.get("date", msg_date)
            r_fname = f"reply_{r_date}_{chat_id}_{reply_to['message_id']}_photo.jpg"
            r_path = await self._download_file(r_fid, r_fname)
            if r_path:
                reply_attachments.append({"type": "photo", "path": r_path, "name": r_fname})

        reply_to_bot = reply_to.get("from", {}).get("username", "") if (reply_to and reply_to.get("from", {}).get("is_bot")) else ""

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
            reply_attachments=reply_attachments,
            reply_to_bot_username=reply_to_bot
        )

        asyncio.create_task(self.handler(inbound))

    async def _register_bot_commands(self) -> None:
        """Registers clean slash commands for both default and Chinese locales upon startup."""
        commands_en = [
            {"command": "status", "description": "View session, engine, and buffer status"},
            {"command": "stop", "description": "Immediately terminate in-flight generation"},
            {"command": "new", "description": "Reset context and start fresh"},
            {"command": "help", "description": "Show usage guide and available commands"},
        ]
        commands_zh = [
            {"command": "status", "description": "查看当前会话、引擎与滑动窗口状态"},
            {"command": "stop", "description": "立即打断当前正在生成的任务"},
            {"command": "new", "description": "重置上下文并开启全新会话"},
            {"command": "help", "description": "查看使用指南与指令说明"},
        ]

        # Dynamically append custom slash commands defined in bot config
        for c in getattr(self.config, "custom_commands", []):
            cmd_name = str(c.get("command", "")).strip().lstrip("/")
            if not cmd_name:
                continue
            desc_zh = str(c.get("description", cmd_name))
            desc_en = str(c.get("description_en", desc_zh))
            commands_en.append({"command": cmd_name, "description": desc_en})
            commands_zh.append({"command": cmd_name, "description": desc_zh})
        try:
            await self._api_call("setMyCommands", commands=commands_en)
            await self._api_call("setMyCommands", commands=commands_zh, language_code="zh")
            logger.info("Synchronized Telegram bot commands menu.")
        except Exception as e:
            logger.warning(f"Failed to synchronize Telegram bot commands: {e}")

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting Telegram Long-Polling Listener (@{self.bot_username})...")
        await self._register_bot_commands()

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
