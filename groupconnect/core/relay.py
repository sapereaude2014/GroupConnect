"""
Cross-Bot IPC Relay for GroupConnect.
Enables local multi-bot instances to synchronize chat contexts and perform
real-time conversational handoffs/wakes within shared group channels,
bypassing platform-level bot-to-bot silence restrictions.
"""

import asyncio
import glob
import json
import logging
import os
from typing import Any, Callable, Coroutine, Dict, Optional, Union

logger = logging.getLogger("groupconnect.relay")


class CrossBotRelay:
    """Manages Unix Domain Socket server & client for local inter-bot communication."""

    def __init__(
        self,
        bot_username: str,
        bot_name: str,
        ipc_dir: str = "/home/server/.local/run/groupconnect_ipc",
        on_event: Optional[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = None
    ):
        self.bot_username = bot_username.lower().lstrip("@")
        self.bot_name = bot_name
        self.ipc_dir = os.path.abspath(ipc_dir)
        self.sock_path = os.path.join(self.ipc_dir, f"{self.bot_username}.sock")
        self.on_event = on_event
        self.server: Optional[asyncio.Server] = None
        self.is_running = False

    async def start(self) -> None:
        """Starts the Unix Domain Socket server for this bot."""
        os.makedirs(self.ipc_dir, exist_ok=True)
        if os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError as e:
                logger.warning(f"Could not remove stale socket {self.sock_path}: {e}")

        try:
            self.server = await asyncio.start_unix_server(
                self._handle_client,
                path=self.sock_path
            )
            self.is_running = True
            logger.info(f"CrossBotRelay listening on {self.sock_path}")
        except Exception as e:
            logger.error(f"Failed to start CrossBotRelay socket on {self.sock_path}: {e}")

    async def stop(self) -> None:
        """Stops the socket server and removes the socket file."""
        self.is_running = False
        if self.server:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:
                pass
            self.server = None
        if os.path.exists(self.sock_path):
            try:
                os.remove(self.sock_path)
            except OSError:
                pass
        logger.info(f"CrossBotRelay stopped for @{self.bot_username}")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await reader.readline()
            if not line:
                return
            data = json.loads(line.decode("utf-8"))
            if self.on_event:
                asyncio.create_task(self.on_event(data))
        except Exception as e:
            logger.warning(f"Error handling relay client message: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def broadcast_reply(
        self,
        chat_id: Union[int, str],
        chat_type: str,
        msg_id: Union[int, str],
        text: str,
        hop_count: int = 0
    ) -> None:
        """Broadcasts a newly sent bot reply to all peer bot sockets."""
        if not os.path.isdir(self.ipc_dir):
            return

        payload = {
            "event": "bot_reply",
            "from_bot": self.bot_username,
            "from_name": self.bot_name,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "msg_id": msg_id,
            "text": text,
            "hop_count": hop_count
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"

        for sock_file in glob.glob(os.path.join(self.ipc_dir, "*.sock")):
            if os.path.basename(sock_file) == f"{self.bot_username}.sock":
                continue
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_unix_connection(sock_file),
                    timeout=2.0
                )
                writer.write(raw)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                logger.debug(f"Broadcast reply to peer socket {sock_file}")
            except (ConnectionRefusedError, FileNotFoundError, asyncio.TimeoutError):
                logger.debug(f"Peer socket {sock_file} unavailable")
                try:
                    if os.path.exists(sock_file):
                        os.remove(sock_file)
                except OSError:
                    pass
            except Exception as e:
                logger.warning(f"Failed to broadcast to {sock_file}: {e}")

