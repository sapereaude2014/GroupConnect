"""
OpenAI Codex CLI Harness Adapter.
Connects to official `codex` CLI via non-interactive `exec` / `exec resume` execution.
"""

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.codex")


@register_adapter(name="codex", display_name="OpenAI Codex (codex)", aliases=["openai_codex", "openai"])
class CodexAdapter(BaseAgentAdapter):
    def __init__(
        self,
        codex_bin: str = "codex",
        workspace_dir: str = "./workspace",
        model: Optional[str] = None,
        timeout_secs: int = 180
    ):
        self.codex_bin = codex_bin
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
        if conversation_id:
            cmd = [
                self.codex_bin, "exec", "resume",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox"
            ]
            if self.model:
                cmd.extend(["-m", self.model])
            if attachments:
                for att in attachments:
                    if att.get("type") == "photo" and att.get("path"):
                        cmd.extend(["-i", att["path"]])
            cmd.extend([conversation_id, prompt])
        else:
            cmd = [
                self.codex_bin, "exec",
                "--json",
                "--dangerously-bypass-approvals-and-sandbox"
            ]
            if self.model:
                cmd.extend(["-m", self.model])
            if attachments:
                for att in attachments:
                    if att.get("type") == "photo" and att.get("path"):
                        cmd.extend(["-i", att["path"]])
            cmd.append(prompt)

        logger.info(f"[Codex] Spawning CLI runner for chat {chat_id}: {' '.join(cmd[:6])}...")
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
                logger.error(f"[Codex] Exited with code {proc.returncode}. Stderr: {stderr_str}")
                return f"⚠️ OpenAI Codex error (Code {proc.returncode}):\n```\n{stderr_str or stdout_str}\n```", conversation_id

            final_text = ""
            new_cid = conversation_id
            for line in stdout_str.split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("session_id") or event.get("id"):
                        new_cid = event.get("session_id") or event.get("id")
                    if event.get("type") == "message" and event.get("content"):
                        final_text += event["content"]
                    elif event.get("type") == "agent_response" and event.get("text"):
                        final_text += event["text"]
                    elif event.get("type") == "item" and event.get("text"):
                        final_text += event["text"]
                except json.JSONDecodeError:
                    final_text += f"{line}\n"

            result_text = final_text.strip() if final_text.strip() else stdout_str
            return result_text, new_cid

        except asyncio.TimeoutError:
            logger.error(f"[Codex] Execution timed out after {self.timeout_secs}s")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            return "⏳ Error: OpenAI Codex execution timed out.", conversation_id

        except asyncio.CancelledError:
            logger.info(f"[Codex] Turn cancelled for chat {chat_id}")
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
            logger.info(f"[Codex] Killing process group for chat {chat_id}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception as e:
                logger.warning(f"Error terminating Codex: {e}")
            self.active_processes.pop(chat_id, None)

    def close(self) -> None:
        for cid, proc in list(self.active_processes.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.active_processes.clear()
