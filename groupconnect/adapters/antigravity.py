"""
Google Antigravity CLI Harness Adapter.
Connects to local `agy` via CLI non-interactive mode.
"""

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.antigravity")


@register_adapter(name="antigravity", display_name="Google Antigravity (agy)", aliases=["agy", "gemini"])
class AntigravityAdapter(BaseAgentAdapter):
    def __init__(
        self,
        agy_bin: str = "agy",
        workspace_dir: str = "./workspace",
        model: str = "gemini-3.7-flash-high",
        timeout_secs: int = 180,
        idle_timeout_mins: int = 30
    ):
        self.agy_bin = agy_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.model = model
        self.timeout_secs = timeout_secs
        self.idle_timeout_mins = idle_timeout_mins

        self.workers: Dict[int, Any] = {}
        self.worker_last_used: Dict[int, float] = {}

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        cmd = [self.agy_bin, "-p", prompt, "--model", self.model]
        if conversation_id:
            if conversation_id == "continue":
                cmd.append("--continue")
            else:
                cmd.extend(["--conversation", conversation_id])

        logger.info(f"[Antigravity] Spawning runner for chat {chat_id}: {' '.join(cmd[:6])}...")
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True
            )
            if chat_id is not None:
                self.workers[chat_id] = proc
                self.worker_last_used[chat_id] = time.time()

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(self.timeout_secs)
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.error(f"[Antigravity] Process exited with code {proc.returncode}. Stderr: {stderr_str}")
                return f"⚠️ Execution failed (Exit code {proc.returncode}):\n```\n{stderr_str or stdout_str}\n```", conversation_id

            new_cid = conversation_id or "continue"
            return stdout_str, new_cid

        except asyncio.TimeoutError:
            logger.error(f"[Antigravity] Task timed out after {self.timeout_secs}s for chat {chat_id}")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return "⏳ Error: Generation timed out.", conversation_id

        except asyncio.CancelledError:
            logger.info(f"[Antigravity] Turn was cancelled for chat {chat_id}")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return None, conversation_id

        finally:
            if chat_id is not None and chat_id in self.workers:
                self.workers.pop(chat_id, None)

    def terminate(self, chat_id: int) -> None:
        proc = self.workers.get(chat_id)
        if proc and proc.returncode is None:
            logger.info(f"[Antigravity] Preemptively terminating process group for chat {chat_id}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Failed to killpg for chat {chat_id}: {e}")
            self.workers.pop(chat_id, None)

    def reap_idle_workers(self) -> None:
        pass

    def close(self) -> None:
        for cid, proc in list(self.workers.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.workers.clear()
