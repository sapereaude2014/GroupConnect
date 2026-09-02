"""
OpenCode CLI Harness Adapter.
Connects to official `opencode` CLI via non-interactive `run` execution.
"""

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.opencode")


@register_adapter(name="opencode", display_name="OpenCode (opencode)", aliases=["open-code"])
class OpenCodeAdapter(BaseAgentAdapter):
    def __init__(
        self,
        opencode_bin: str = "opencode",
        workspace_dir: str = "./workspace",
        model: Optional[str] = None,
        timeout_secs: int = 180
    ):
        self.opencode_bin = opencode_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.model = model
        self.timeout_secs = timeout_secs
        self.active_processes: Dict[int, Any] = {}

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        cmd = [self.opencode_bin, "run", "--format", "json", "--dir", self.workspace_dir]
        if self.model:
            cmd.extend(["--model", self.model])
        if conversation_id:
            cmd.extend(["-s", conversation_id])

        if attachments:
            for att in attachments:
                if att.get("path"):
                    cmd.extend(["-f", att["path"]])

        cmd.append(prompt)

        logger.info(f"[OpenCode] Spawning CLI runner for chat {chat_id}...")
        proc = None
        custom_env = os.environ.copy()
        if "TMPDIR" not in custom_env or not os.path.exists(custom_env["TMPDIR"]):
            custom_env["TMPDIR"] = "/tmp"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.workspace_dir,
                env=custom_env,
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
                logger.error(f"[OpenCode] Exited with code {proc.returncode}. Stderr: {stderr_str}")
                return f"⚠️ OpenCode error (Code {proc.returncode}):\n```\n{stderr_str or stdout_str}\n```", conversation_id

            final_text = ""
            for line in stdout_str.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("type") == "text" and event.get("content"):
                        final_text += event["content"]
                    elif event.get("type") == "message" and event.get("text"):
                        final_text += event["text"]
                except json.JSONDecodeError:
                    final_text += f"{line}\n"

            result_text = final_text.strip() if final_text.strip() else stdout_str
            new_cid = conversation_id or f"opencode_cid_{int(time.time())}"
            return result_text, new_cid

        except asyncio.TimeoutError:
            logger.error(f"[OpenCode] Execution timed out after {self.timeout_secs}s")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return "⏳ Error: OpenCode execution timed out.", conversation_id

        except asyncio.CancelledError:
            logger.info(f"[OpenCode] Turn cancelled for chat {chat_id}")
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
            logger.info(f"[OpenCode] Killing process group for chat {chat_id}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception as e:
                logger.warning(f"Error terminating OpenCode: {e}")
            self.active_processes.pop(chat_id, None)

    def close(self) -> None:
        for cid, proc in list(self.active_processes.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.active_processes.clear()
