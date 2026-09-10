"""
TeleAgent CLI Harness Adapter.
Connects to local TeleAgent daemon via `tele-worker` CLI with JSON output and session resumption.
"""

import asyncio
import glob
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.teleagent")


def _load_skills_manifest(workspace_dir: str) -> str:
    """Scan .agents/skills/*/SKILL.md and .agents/plugins/*/skills/*/SKILL.md, return compact manifest."""
    entries = []

    # 1. Top-level skills
    skills_dir = os.path.join(workspace_dir, ".agents", "skills")
    if os.path.isdir(skills_dir):
        for skill_md in sorted(glob.glob(os.path.join(skills_dir, "*", "SKILL.md"))):
            _extract_skill_entry(skill_md, workspace_dir, entries)

    # 2. Plugin-bundled skills
    plugins_dir = os.path.join(workspace_dir, ".agents", "plugins")
    if os.path.isdir(plugins_dir):
        for skill_md in sorted(glob.glob(os.path.join(plugins_dir, "*", "skills", "*", "SKILL.md"))):
            _extract_skill_entry(skill_md, workspace_dir, entries)

    if not entries:
        return ""
    return (
        "【Pre-loaded Skills Manifest】\n"
        "The following skills are available. Read the SKILL.md at the given path for detailed usage.\n"
        + "\n".join(entries)
    )


def _extract_skill_entry(skill_md: str, workspace_dir: str, entries: list) -> None:
    """Extract name and description from a SKILL.md frontmatter and append to entries."""
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            lines = f.read()
        name = ""
        desc = ""
        if lines.startswith("---"):
            end = lines.find("---", 3)
            if end != -1:
                front = lines[3:end]
                for line in front.strip().splitlines():
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip()
                    elif line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
        if name:
            rel_path = os.path.relpath(skill_md, workspace_dir)
            entries.append(f"- **{name}**: {desc}  (`{rel_path}`)")
    except Exception:
        pass


@register_adapter(name="teleagent", display_name="TeleAgent (tele-worker)", aliases=["tele-worker", "teleworker"])
class TeleAgentAdapter(BaseAgentAdapter):
    def __init__(
        self,
        teleworker_bin: str = "tele-worker",
        workspace_dir: str = "./workspace",
        model: Optional[str] = None,
        timeout_secs: int = 1800,
        idle_timeout_mins: int = 120
    ):
        self.teleworker_bin = teleworker_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.model = model
        self.timeout_secs = timeout_secs
        self.idle_timeout_mins = idle_timeout_mins

        self.workers: Dict[int, Any] = {}
        self.worker_last_used: Dict[int, float] = {}
        self.skills_manifest = _load_skills_manifest(self.workspace_dir)
        if self.skills_manifest:
            logger.info(f"[TeleAgent] Loaded skills manifest from {self.workspace_dir}/.agents/")

    async def _invoke_subprocess(
        self,
        cmd: List[str],
        chat_id: Optional[int] = None
    ) -> Tuple[int, str, str]:
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
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
            return proc.returncode, stdout_str, stderr_str

        except asyncio.TimeoutError:
            logger.error(f"[TeleAgent] Task timed out after {self.timeout_secs}s for chat {chat_id}")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            raise
        except asyncio.CancelledError:
            logger.info(f"[TeleAgent] Turn was cancelled for chat {chat_id}")
            if proc and proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            raise
        finally:
            if chat_id is not None and chat_id in self.workers:
                self.workers.pop(chat_id, None)

    @staticmethod
    def _parse_teleworker_output(stdout_str: str) -> Tuple[str, Optional[str], Optional[str]]:
        text = ""
        new_cid = None
        error_code = None
        try:
            data = json.loads(stdout_str)
            if isinstance(data, dict):
                if data.get("session_id"):
                    new_cid = data["session_id"]
                if data.get("text") is not None:
                    text = str(data["text"]).strip()
                raw = data.get("raw")
                if isinstance(raw, dict) and raw.get("code"):
                    error_code = raw.get("code")
        except json.JSONDecodeError:
            text = stdout_str
        return text, new_cid, error_code

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        # Inject skills manifest on first turn (no existing conversation)
        if self.skills_manifest and not conversation_id:
            prompt = f"{self.skills_manifest}\n\n{prompt}"

        cmd = [
            self.teleworker_bin,
            "-p", prompt,
            "-d", self.workspace_dir,
            "--json",
        ]
        if conversation_id:
            cmd.extend(["-s", conversation_id])
        if self.model:
            cmd.extend(["-m", self.model])

        logger.info(f"[TeleAgent] Spawning runner for chat {chat_id}: tele-worker -p ... {'-s ' + conversation_id[:12] if conversation_id else '(new session)'}")

        try:
            code, stdout_str, stderr_str = await self._invoke_subprocess(cmd, chat_id)
            text, new_cid, err_code = self._parse_teleworker_output(stdout_str)

            # If resuming an existing session failed (process crash, session_busy, session not found, or empty response)
            if conversation_id and (code != 0 or err_code in ("session_busy", "internal_error") or not text):
                logger.warning(
                    f"[TeleAgent] Resumed session {conversation_id} failed or busy (code={code}, err_code={err_code}, stderr={stderr_str}). "
                    f"Auto-fallback to a fresh session..."
                )
                fallback_prompt = prompt
                if self.skills_manifest and "【Pre-loaded Skills Manifest】" not in fallback_prompt:
                    fallback_prompt = f"{self.skills_manifest}\n\n{fallback_prompt}"

                fallback_cmd = [
                    self.teleworker_bin,
                    "-p", fallback_prompt,
                    "-d", self.workspace_dir,
                    "--json",
                ]
                if self.model:
                    fallback_cmd.extend(["-m", self.model])

                logger.info(f"[TeleAgent] Spawning fresh fallback runner for chat {chat_id}")
                code, stdout_str, stderr_str = await self._invoke_subprocess(fallback_cmd, chat_id)
                text, new_cid, err_code = self._parse_teleworker_output(stdout_str)

            if code != 0:
                logger.error(f"[TeleAgent] Process exited with code {code}. Stderr: {stderr_str}")
                return f"⚠️ 执行出错（Exit code {code}），已重置会话。", None

            if not text:
                logger.warning(f"[TeleAgent] Empty response received for chat {chat_id}. Stderr: {stderr_str}")
                return "⚠️ 管家暂时没能生成回复，请稍后再试。", None

            return text, (new_cid or conversation_id)

        except asyncio.TimeoutError:
            return "⏳ Error: Generation timed out.", None
        except asyncio.CancelledError:
            return None, conversation_id

    def terminate(self, chat_id: int) -> None:
        proc = self.workers.get(chat_id)
        if proc and proc.returncode is None:
            logger.info(f"[TeleAgent] Preemptively terminating process group for chat {chat_id}")
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
