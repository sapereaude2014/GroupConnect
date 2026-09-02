"""
Claude Code CLI Adapter for GroupAgent.
Bridges Anthropic's Claude Code CLI to chat platforms.
"""

import asyncio
import logging
import os
import signal
from typing import Any, Dict, List, Optional, Set, Tuple

from groupagent.adapters.base import BaseAgentAdapter

logger = logging.getLogger("groupagent.adapters.claude_code")


class ClaudeCodeAdapter(BaseAgentAdapter):
    def __init__(self, claude_bin: str = "claude", workspace_dir: str = ".", timeout_secs: int = 180):
        self.claude_bin = claude_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
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
        cmd = [self.claude_bin, "--print", "-p", prompt]
        if conversation_id:
            cmd.extend(["--resume", conversation_id])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True
        )
        self.active_procs[cid_key] = proc

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_secs)
            if cid_key in self.cancelled_chats:
                return None, conversation_id

            out_text = stdout.decode("utf-8", errors="replace").strip()
            err_text = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0:
                logger.warning(f"Claude Code returned {proc.returncode}: {err_text}")
                return out_text or f"⚠️ Claude Code error (code {proc.returncode}):\n{err_text}", conversation_id

            return out_text or "(Done, no output)", conversation_id
        except asyncio.TimeoutError:
            self.terminate(cid_key)
            return "⚠️ Request timed out.", conversation_id
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
