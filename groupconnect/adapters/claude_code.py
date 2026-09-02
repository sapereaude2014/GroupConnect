"""
Anthropic Claude Code CLI Harness Adapter.
Connects to official `claude` CLI via non-interactive `-p` execution.
"""

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.claude_code")


@register_adapter(name="claude", display_name="Anthropic Claude Code (claude)", aliases=["claude_code", "anthropic"])
class ClaudeCodeAdapter(BaseAgentAdapter):
    def __init__(
        self,
        claude_bin: str = "claude",
        workspace_dir: str = "./workspace",
        timeout_secs: int = 180
    ):
        self.claude_bin = claude_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.timeout_secs = timeout_secs
        self.active_processes: Dict[int, Any] = {}

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        cmd = [self.claude_bin, "-p", prompt]
        if conversation_id:
            cmd.extend(["--resume", conversation_id])

        logger.info(f"[ClaudeCode] Spawning CLI runner for chat {chat_id}...")
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
                self.active_processes[chat_id] = proc

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(self.timeout_secs)
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.error(f"[ClaudeCode] Exited with code {proc.returncode}. Stderr: {stderr_str}")
                return f"⚠️ Claude Code error (Code {proc.returncode}):\n```\n{stderr_str or stdout_str}\n```", conversation_id

            new_cid = conversation_id or f"claude_cid_{int(time.time())}"
            return stdout_str, new_cid

        except asyncio.TimeoutError:
            logger.error(f"[ClaudeCode] Execution timed out after {self.timeout_secs}s")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return "⏳ Error: Claude Code execution timed out.", conversation_id

        except asyncio.CancelledError:
            logger.info(f"[ClaudeCode] Turn cancelled for chat {chat_id}")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return None, conversation_id

        finally:
            if chat_id is not None and chat_id in self.active_processes:
                self.active_processes.pop(chat_id, None)

    def terminate(self, chat_id: int) -> None:
        proc = self.active_processes.get(chat_id)
        if proc and proc.returncode is None:
            logger.info(f"[ClaudeCode] Killing process group for chat {chat_id}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception as e:
                logger.warning(f"Error terminating ClaudeCode: {e}")
            self.active_processes.pop(chat_id, None)

    def close(self) -> None:
        for cid, proc in list(self.active_processes.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.active_processes.clear()
