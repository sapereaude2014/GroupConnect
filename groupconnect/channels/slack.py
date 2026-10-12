"""
Slack Platform Channel for GroupConnect.
Connects Slack Web API & Events API webhook listener to core agent gateway.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional, Union

import httpx

from groupconnect.channels.base import BaseChannel, ChannelField, InboundMessage, register_channel
from groupconnect.core.config import GatewayConfig

logger = logging.getLogger("groupconnect.channel.slack")

# Slack's own guidance: reject requests older than 5 minutes to block replay
# of captured signatures.
_MAX_SIGNATURE_AGE_SECS = 300


@register_channel(
    name="slack",
    display_name="Slack",
    aliases=[],
    fields=[
        ChannelField(key="slack_bot_token", label="Slack Bot User OAuth Token (xoxb-...)", is_secret=True),
        ChannelField(key="slack_signing_secret", label="Slack Signing Secret - required to verify webhook signatures", is_secret=True),
        ChannelField(key="bot_username", label="Slack Bot User ID / Name", default="slack_bot"),
        ChannelField(key="webhook_bind", label="Webhook bind address (default 127.0.0.1)", default="127.0.0.1"),
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
        self.signing_secret = str(config.raw.get("slack_signing_secret", "") or "")
        self.api_base = "https://slack.com/api"
        self.bot_username = config.bot_username
        self.bot_name = config.bot_name
        self.port = int(config.raw.get("webhook_port", config.raw.get("port", 8091)))
        self.bind_host = str(config.raw.get("webhook_bind", "127.0.0.1"))

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

            # Signature verification (fail-closed): Slack signs every request
            # with HMAC-SHA256 over "v0:{timestamp}:{body}". Reject unsigned,
            # badly signed or stale requests BEFORE parsing attacker-controlled data.
            sig_header = headers.get("x-slack-signature", "")
            ts_str = headers.get("x-slack-request-timestamp", "")
            reject_reason = ""
            if not self.signing_secret:
                reject_reason = "slack_signing_secret not configured"
            elif not sig_header or not ts_str:
                reject_reason = "missing X-Slack-Signature / X-Slack-Request-Timestamp headers"
            else:
                try:
                    if abs(time.time() - int(ts_str)) > _MAX_SIGNATURE_AGE_SECS:
                        reject_reason = "stale signature timestamp (possible replay)"
                    else:
                        basestring = f"v0:{ts_str}:".encode("utf-8") + body_bytes
                        expected = "v0=" + hmac.new(
                            self.signing_secret.encode("utf-8"), basestring, hashlib.sha256
                        ).hexdigest()
                        if not hmac.compare_digest(expected, sig_header):
                            reject_reason = "signature mismatch"
                except ValueError:
                    reject_reason = "invalid signature data"
            if reject_reason:
                logger.warning(f"[Slack] Rejecting webhook request: {reject_reason}")
                writer.write(b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                writer.close()
                return

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
        if not self.signing_secret:
            logger.warning(
                "[Slack] slack_signing_secret is not configured; ALL inbound webhook events "
                "will be rejected (fail-closed). Copy the Signing Secret from the Slack app "
                "config page to enable this channel."
            )
        logger.info(f"Starting Slack Events Webhook Server on {self.bind_host}:{self.port}...")
        self.server = await asyncio.start_server(self._handle_http_client, self.bind_host, self.port)
        async with self.server:
            await self.server.serve_forever()
