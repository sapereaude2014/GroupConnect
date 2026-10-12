"""
WeCom (WeChat Work / 企业微信) Platform Channel for GroupConnect.
Supports Enterprise Self-Built App API and Webhook callback listener.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import time
import urllib.parse
from typing import Any, Callable, Coroutine, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.core.config import GatewayConfig

try:
    from Crypto.Cipher import AES
except ImportError:  # optional runtime dependency, needed for WeCom decryption
    AES = None

logger = logging.getLogger("groupconnect.channel.wecom")


def _wecom_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """WeCom callback signature: SHA1 over the sorted concatenation."""
    raw = "".join(sorted([token, timestamp, nonce, encrypt]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _wecom_decrypt(encrypt_b64: str, encoding_aes_key: str, corp_id: str) -> str:
    """Decrypts a WeCom callback payload (AES-256-CBC) to plaintext XML.

    Layout after decryption: 16 random bytes | 4-byte big-endian msg length |
    message XML | receive_id (corp_id). The embedded receive_id must match the
    configured corp_id, otherwise the payload is rejected.
    """
    if AES is None:
        raise RuntimeError("pycryptodome is required for WeCom callbacks (pip install pycryptodome)")
    key = base64.b64decode(encoding_aes_key + "=")
    if len(key) != 32:
        raise ValueError("invalid EncodingAESKey length")
    data = base64.b64decode(encrypt_b64)
    if not data or len(data) % 16 != 0:
        raise ValueError("invalid ciphertext length")
    plain = AES.new(key, AES.MODE_CBC, key[:16]).decrypt(data)
    pad = plain[-1]
    if not 1 <= pad <= 32:
        raise ValueError("bad PKCS7 padding")
    content = plain[16:-pad]
    if len(content) < 4:
        raise ValueError("truncated payload")
    msg_len = struct.unpack(">I", content[:4])[0]
    if 4 + msg_len > len(content):
        raise ValueError("truncated message")
    msg = content[4:4 + msg_len]
    receive_id = content[4 + msg_len:].decode("utf-8", errors="replace")
    if corp_id and receive_id != corp_id:
        raise ValueError(f"receive_id mismatch ({receive_id})")
    return msg.decode("utf-8", errors="replace")


@register_channel(
    name="wecom",
    display_name="WeCom (企业微信)",
    aliases=["wechat", "wework", "weixin"],
    fields=[
        ChannelField(key="wecom_corp_id", label="WeCom Corp ID (ww...)", is_secret=False),
        ChannelField(key="wecom_corp_secret", label="WeCom App Secret", is_secret=True),
        ChannelField(key="wecom_agent_id", label="WeCom Agent ID [e.g. 1000002]", default="1000002"),
        ChannelField(key="wecom_callback_token", label="WeCom Callback Token - required to verify webhook signatures", is_secret=True),
        ChannelField(key="wecom_encoding_aes_key", label="WeCom EncodingAESKey (43 chars) - required to decrypt webhook payloads", is_secret=True),
        ChannelField(key="webhook_bind", label="Webhook bind address (default 127.0.0.1)", default="127.0.0.1"),
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
        self.callback_token = str(config.raw.get("wecom_callback_token", "") or "")
        self.encoding_aes_key = str(config.raw.get("wecom_encoding_aes_key", "") or "")
        self.bind_host = str(config.raw.get("webhook_bind", "127.0.0.1"))
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

            # 1. WeCom URL GET verification (signed echostr echo).
            # Fail-closed: the msg_signature must verify and the echostr must
            # decrypt to the configured corp_id before anything is echoed back.
            if method == "GET":
                parsed = urllib.parse.urlparse(path)
                qs = urllib.parse.parse_qs(parsed.query)
                sig = qs.get("msg_signature", [""])[0]
                ts = qs.get("timestamp", [""])[0]
                nonce = qs.get("nonce", [""])[0]
                echostr = qs.get("echostr", [""])[0]
                reject_reason = ""
                try:
                    if not (self.callback_token and self.encoding_aes_key):
                        reject_reason = "callback token / EncodingAESKey not configured"
                    elif not (sig and ts and nonce and echostr):
                        reject_reason = "incomplete verification params"
                    elif not hmac.compare_digest(_wecom_signature(self.callback_token, ts, nonce, echostr), sig):
                        reject_reason = "msg_signature mismatch"
                    else:
                        echo_plain = _wecom_decrypt(echostr, self.encoding_aes_key, self.corp_id)
                except Exception as e:
                    reject_reason = f"decryption failed ({e})"
                if reject_reason:
                    logger.warning(f"[WeCom] Rejecting callback verification: {reject_reason}")
                    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    await writer.drain()
                    writer.close()
                    return
                resp_bytes = echo_plain.encode("utf-8")
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

            # 2. WeCom Message Event POST — signature verification (fail-closed):
            # WeCom signs every callback with SHA1 over (token, timestamp, nonce,
            # encrypted_body) and AES-encrypts the payload. Verify + decrypt BEFORE
            # parsing any attacker-controlled data.
            body_bytes = await reader.readexactly(content_length) if content_length > 0 else b""
            body_str = body_bytes.decode("utf-8", errors="replace")

            parsed = urllib.parse.urlparse(path)
            qs = urllib.parse.parse_qs(parsed.query)
            sig = qs.get("msg_signature", [""])[0]
            ts = qs.get("timestamp", [""])[0]
            nonce = qs.get("nonce", [""])[0]
            encrypt_match = re.search(r"<Encrypt><!\[CDATA\[(.*?)\]\]></Encrypt>", body_str, re.DOTALL)
            reject_reason = ""
            try:
                if not (self.callback_token and self.encoding_aes_key):
                    reject_reason = "callback token / EncodingAESKey not configured"
                elif not encrypt_match:
                    reject_reason = "payload missing <Encrypt> field"
                elif not (sig and ts and nonce):
                    reject_reason = "incomplete verification params"
                elif not hmac.compare_digest(
                    _wecom_signature(self.callback_token, ts, nonce, encrypt_match.group(1)), sig
                ):
                    reject_reason = "msg_signature mismatch"
                else:
                    xml_plain = _wecom_decrypt(encrypt_match.group(1), self.encoding_aes_key, self.corp_id)
            except Exception as e:
                reject_reason = f"decryption failed ({e})"
            if reject_reason:
                logger.warning(f"[WeCom] Rejecting webhook event: {reject_reason}")
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                writer.close()
                return

            response = b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n"
            writer.write(response)
            await writer.drain()
            writer.close()

            # Parse the DECRYPTED plaintext XML
            from_user_match = re.search(r"<FromUserName><!\[CDATA\[(.*?)\]\]></FromUserName>", xml_plain)
            content_match = re.search(r"<Content><!\[CDATA\[(.*?)\]\]></Content>", xml_plain)
            msg_type_match = re.search(r"<MsgType><!\[CDATA\[(.*?)\]\]></MsgType>", xml_plain)
            chat_id_match = re.search(r"<ChatId><!\[CDATA\[(.*?)\]\]></ChatId>", xml_plain)

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
        if not (self.callback_token and self.encoding_aes_key):
            logger.warning(
                "[WeCom] wecom_callback_token / wecom_encoding_aes_key not configured; "
                "ALL inbound webhook events will be rejected (fail-closed)."
            )
        logger.info(f"Starting WeCom Webhook Server on {self.bind_host}:{self.port} (CorpID: {self.corp_id})...")
        self.server = await asyncio.start_server(self._handle_http_client, self.bind_host, self.port)
        async with self.server:
            await self.server.serve_forever()
