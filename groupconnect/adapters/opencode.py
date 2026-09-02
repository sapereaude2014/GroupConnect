"""
OpenCode CLI Adapter for GroupConnect.
Bridges OpenCode CLI non-interactive execution (`opencode run`) to chat platforms.
"""

import asyncio
import json
import logging
import os
import signal
from typing import Any, Dict, List, Optional, Set, Tuple

from groupconnect.adapters.base import BaseAgentAdapter

logger = logging.getLogger("groupconnect.adapters.opencode")


class OpenCodeAdapter(BaseAgentAdapter):
    """Adapter for OpenCode CLI headless automation (`opencode run`)."""

    def __init__(
        self,
        opencode_bin: str = "opencode",
        workspace_dir: str = ".",
        model: Optional[str] = None,
        timeout_secs: int = 180
    ):
        self.opencode_bin = opencode_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.model = model
        self.timeout_secs = timeout_secs
        self.active_procs: Dict[int, asyncio.subprocess.Process] = {}
        self.cancelled_chats: Set[int] = set()

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        cid_key = chat_id or 0

        # Build command: opencode run [OPTIONS] "<PROMPT>"
        cmd = [self.opencode_bin, "run"]
        if conversation_id:
            cmd.extend(["--session", conversation_id])
        if self.model:
            cmd.extend(["--model", self.model])

        # Enable JSON streaming format and append prompt
        cmd.extend(["--format", "json", prompt])

        logger.info(f"[OpenCode:{cid_key}] Executing opencode run (session={conversation_id})...")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True  # POSIX Process Group isolation for /stop
        )
        self.active_procs[cid_key] = proc

        collected_text: List[str] = []
        new_session_id = conversation_id

        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue
                try:
                    event = json.loads(line_str)
                    if "session_id" in event:
                        new_session_id = event["session_id"]
                    if event.get("type") == "text" and "content" in event:
                        collected_text.append(event["content"])
                    elif event.get("type") == "message" and "text" in event:
                        collected_text.append(event["text"])
                    elif "response" in event:
                        collected_text.append(str(event["response"]))
                except json.JSONDecodeError:
                    collected_text.append(line_str)

            await proc.wait()

            if cid_key in self.cancelled_chats:
                return None, new_session_id

            if proc.returncode != 0 and not collected_text:
                stderr_bytes = await proc.stderr.read()
                err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()
                return f"⚠️ OpenCode execution error (code {proc.returncode}):\n{err_msg}", new_session_id

            resp = "\n".join(collected_text).strip() or "(Task completed with no text output)"
            return resp, new_session_id
        except asyncio.TimeoutError:
            self.terminate(cid_key)
            return f"⚠️ OpenCode execution timed out after {self.timeout_secs}s.", new_session_id
        except asyncio.CancelledError:
            self.terminate(cid_key)
            return None, new_session_id
        except Exception as e:
            logger.error(f"[OpenCode:{cid_key}] Error: {e}", exc_info=True)
            self.terminate(cid_key)
            if cid_key in self.cancelled_chats:
                return None, new_session_id
            return f"⚠️ OpenCode execution exception: {e}", new_session_id
        finally:
            self.active_procs.pop(cid_key, None)
            self.cancelled_chats.discard(cid_key)

    def terminate(self, chat_id: int) -> None:
        self.cancelled_chats.add(chat_id)
        proc = self.active_procs.pop(chat_id, None)
        if proc and proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass

    def close(self) -> None:
        for cid in list(self.active_procs.keys()):
            self.terminate(cid)
