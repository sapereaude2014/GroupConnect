"""
TeleAgent CLI Harness Adapter.
Connects to local TeleAgent daemon via `tele-worker` CLI with JSON output and session resumption.
"""

import asyncio
import glob
import json
import logging
import os
import re
import signal
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, register_adapter

logger = logging.getLogger("groupconnect.adapter.teleagent")

# Marker prefix for GroupConnect-owned TeleAgent sessions. Worker sessions are
# titled "GC-<chat_id>-<spawn_ts>" so terminate() can locate and delete exactly
# the daemon-side sessions belonging to a chat — never user-created sessions.
_SESSION_TITLE_PREFIX = "GC-"
_SESSION_LIST_RE_TMPL = r"\[([A-Za-z0-9_-]+)\]\s*" + _SESSION_TITLE_PREFIX + r"{chat_id}-\d+"


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


def _load_agents_doc(workspace_dir: str) -> str:
    """Load the workspace AGENTS.md (if present) as part of the system prompt.

    AGENTS.md carries the workspace's operational rules and conventions. The
    TeleAgent daemon does not auto-read it, so the adapter injects it on the
    first turn of every conversation, giving it the same weight as the skills
    manifest. Returns an empty string when the file is missing or unreadable.
    """
    agents_md = os.path.join(workspace_dir, "AGENTS.md")
    try:
        if os.path.isfile(agents_md):
            with open(agents_md, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                return f"【Workspace AGENTS.md 规范】\n{content}"
    except Exception:
        pass
    return ""


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
        output_grace_secs: int = 15,
        abort_server_sessions: bool = True
    ):
        self.teleworker_bin = teleworker_bin
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.model = model
        self.timeout_secs = timeout_secs
        self.output_grace_secs = output_grace_secs
        # SIGKILL only kills the thin tele-worker client; the TeleAgent daemon
        # keeps executing the session's LLM loop server-side. When enabled,
        # terminate() also aborts the daemon sessions so /stop truly stops —
        # abort (not delete) keeps the session and its history, so the next
        # turn resumes the same conversation seamlessly.
        self.abort_server_sessions = abort_server_sessions

        self.workers: Dict[int, Any] = {}
        self.worker_last_used: Dict[int, float] = {}
        # Chats whose in-flight worker was intentionally killed by terminate()
        # (e.g. /stop). Checked by execute_turn so the crash-revival fallback
        # doesn't mistake the SIGKILL for a crashed session and respawn a worker.
        self._termination_requested: set = set()
        self.skills_manifest = _load_skills_manifest(self.workspace_dir)
        if self.skills_manifest:
            logger.info(f"[TeleAgent] Loaded skills manifest from {self.workspace_dir}/.agents/")
        self.agents_doc = _load_agents_doc(self.workspace_dir)
        if self.agents_doc:
            logger.info(f"[TeleAgent] Loaded AGENTS.md from {self.workspace_dir}/")

    @staticmethod
    def _kill_process_group(proc: Any) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass

    @staticmethod
    def _is_complete_json_document(data: bytes) -> bool:
        """True when accumulated stdout already forms one complete JSON document.
        tele-worker --json emits exactly one JSON object as its final answer."""
        if not data:
            return False
        try:
            json.loads(data.decode("utf-8", errors="replace"))
            return True
        except (json.JSONDecodeError, ValueError):
            return False

    async def _invoke_subprocess(
        self,
        cmd: List[str],
        chat_id: Optional[int] = None
    ) -> Tuple[int, str, str, bool]:
        """Run tele-worker; return (returncode, stdout, stderr, output_delivered).

        Guards against workers that write the final JSON answer but never exit
        (e.g. a leaked child process keeps the pipes open, so communicate()-style
        reads would block until the hard timeout). Once stdout holds a complete
        JSON document, the worker gets a short grace window to exit; after that
        its whole process group is force-killed so the answer can be used.
        """
        proc = None
        output_delivered = False
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

            async def _read_stdout() -> bytes:
                nonlocal output_delivered
                chunks: List[bytes] = []
                while True:
                    data = await proc.stdout.read(65536)
                    if not data:
                        break
                    chunks.append(data)
                    if self._is_complete_json_document(b"".join(chunks)):
                        # Final answer is in hand; don't wait forever for a stuck worker.
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=float(self.output_grace_secs))
                        except asyncio.TimeoutError:
                            output_delivered = True
                            logger.warning(
                                f"[TeleAgent] Worker for chat {chat_id} delivered final output "
                                f"but did not exit within {self.output_grace_secs}s; force-killing process group"
                            )
                        # In both cases reap any leftover group members (leaked children
                        # holding the pipes) so both readers get EOF.
                        self._kill_process_group(proc)
                        try:
                            await proc.wait()
                        except Exception:
                            pass
                        break
                while True:
                    data = await proc.stdout.read(65536)
                    if not data:
                        break
                    chunks.append(data)
                return b"".join(chunks)

            async def _read_stderr() -> bytes:
                chunks: List[bytes] = []
                while True:
                    data = await proc.stderr.read(65536)
                    if not data:
                        break
                    chunks.append(data)
                return b"".join(chunks)

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                asyncio.gather(_read_stdout(), _read_stderr()),
                timeout=float(self.timeout_secs)
            )
            stdout_str = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr_str = stderr_bytes.decode("utf-8", errors="replace").strip()
            return proc.returncode, stdout_str, stderr_str, output_delivered

        except asyncio.TimeoutError:
            logger.error(f"[TeleAgent] Task timed out after {self.timeout_secs}s for chat {chat_id}")
            if proc and proc.returncode is None:
                self._kill_process_group(proc)
                try:
                    await proc.wait()
                except Exception:
                    pass
            raise
        except asyncio.CancelledError:
            logger.info(f"[TeleAgent] Turn was cancelled for chat {chat_id}")
            if proc and proc.returncode is None:
                self._kill_process_group(proc)
                try:
                    await proc.wait()
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
        # Inject workspace AGENTS.md and skills manifest on first turn (no existing conversation).
        # Order matters: workspace rules come first, then the skills catalog.
        if not conversation_id:
            injected = []
            if self.agents_doc:
                injected.append(self.agents_doc)
            if self.skills_manifest:
                injected.append(self.skills_manifest)
            if injected:
                prompt = "\n\n".join(injected + [prompt])

        cmd = [
            self.teleworker_bin,
            "-p", prompt,
            "-d", self.workspace_dir,
            "--json",
            "--timeout", str(self.timeout_secs),
        ]
        if chat_id is not None:
            # Tag the daemon session so terminate() can purge it later via /stop.
            cmd.extend(["--title", f"{_SESSION_TITLE_PREFIX}{chat_id}-{int(time.time())}"])
        if conversation_id:
            cmd.extend(["-s", conversation_id])
        if self.model:
            cmd.extend(["-m", self.model])

        logger.info(f"[TeleAgent] Spawning runner for chat {chat_id}: tele-worker -p ... {'-s ' + conversation_id[:12] if conversation_id else '(new session)'}")

        try:
            code, stdout_str, stderr_str, output_delivered = await self._invoke_subprocess(cmd, chat_id)
            text, new_cid, err_code = self._parse_teleworker_output(stdout_str)

            # Intentional termination (/stop or engine reset) killed this worker.
            # Do NOT mistake it for a crash: no revival fallback, no error spam.
            if chat_id is not None and chat_id in self._termination_requested:
                self._termination_requested.discard(chat_id)
                if output_delivered and text:
                    # /stop landed late: the complete answer was already in hand.
                    logger.info(f"[TeleAgent] Stop requested post-delivery for chat {chat_id}; trusting delivered output")
                    return text, (new_cid or conversation_id)
                logger.info(f"[TeleAgent] Stop requested for chat {chat_id}; worker terminated without revival")
                return None, conversation_id

            # Worker was force-killed only AFTER the complete final answer was already
            # delivered on stdout (worker hung post-output, or a /stop landed late).
            # Trust the delivered answer instead of erroring out or re-running the task.
            if output_delivered and text:
                logger.info(f"[TeleAgent] Using output delivered before force-kill for chat {chat_id}")
                return text, (new_cid or conversation_id)

            # If resuming an existing session failed (process crash, session_busy, session not found, or empty response)
            if conversation_id and (code != 0 or err_code in ("session_busy", "internal_error") or not text):
                logger.warning(
                    f"[TeleAgent] Resumed session {conversation_id} failed or busy (code={code}, err_code={err_code}, stderr={stderr_str}). "
                    f"Auto-fallback to a fresh session..."
                )
                fallback_prompt = prompt
                if self.agents_doc and "【Workspace AGENTS.md 规范】" not in fallback_prompt:
                    fallback_prompt = f"{self.agents_doc}\n\n{fallback_prompt}"
                if self.skills_manifest and "【Pre-loaded Skills Manifest】" not in fallback_prompt:
                    fallback_prompt = f"{self.skills_manifest}\n\n{fallback_prompt}"

                fallback_cmd = [
                    self.teleworker_bin,
                    "-p", fallback_prompt,
                    "-d", self.workspace_dir,
                    "--json",
                    "--timeout", str(self.timeout_secs),
                ]
                if chat_id is not None:
                    fallback_cmd.extend(["--title", f"{_SESSION_TITLE_PREFIX}{chat_id}-{int(time.time())}"])
                if self.model:
                    fallback_cmd.extend(["-m", self.model])

                logger.info(f"[TeleAgent] Spawning fresh fallback runner for chat {chat_id}")
                code, stdout_str, stderr_str, output_delivered = await self._invoke_subprocess(fallback_cmd, chat_id)

                # /stop arrived while the fallback worker was running
                if chat_id is not None and chat_id in self._termination_requested:
                    self._termination_requested.discard(chat_id)
                    logger.info(f"[TeleAgent] Stop requested for chat {chat_id} during fallback; not reviving further")
                    return None, conversation_id

                text, new_cid, err_code = self._parse_teleworker_output(stdout_str)

                if output_delivered and text:
                    logger.info(f"[TeleAgent] Using output delivered before force-kill for chat {chat_id}")
                    return text, (new_cid or conversation_id)

            if code != 0:
                logger.error(f"[TeleAgent] Process exited with code {code}. Stderr: {stderr_str}")
                return f"⚠️ 执行出错（Exit code {code}），已重置会话。", None

            if not text:
                logger.warning(f"[TeleAgent] Empty response received for chat {chat_id}. Stderr: {stderr_str}")
                return "⚠️ 暂时未能生成有效回复，请稍后再试。", None

            return text, (new_cid or conversation_id)

        except asyncio.TimeoutError:
            return "⏳ Error: Generation timed out.", None
        except asyncio.CancelledError:
            return None, conversation_id

    def _abort_server_sessions(self, chat_id: int) -> None:
        """Aborts the in-flight generation of the daemon-side TeleAgent sessions
        tagged for this chat.

        Runs in an executor thread after /stop. Killing the tele-worker client
        leaves the daemon session's LLM loop alive (it keeps burning tokens and
        running tools to completion); POST /session/<id>/abort stops the
        generation while keeping the session and its history, so the next turn
        resumes the same conversation. Idempotent on idle sessions. Only
        sessions titled GC-<chat_id>-<ts> are touched — user-created sessions
        are never matched.
        """
        try:
            listing = subprocess.run(
                [self.teleworker_bin, "-l"],
                capture_output=True, timeout=15,
            )
            text = listing.stdout.decode("utf-8", errors="replace")
            pattern = _SESSION_LIST_RE_TMPL.format(chat_id=re.escape(str(chat_id)))
            session_ids = re.findall(pattern, text)
            for sid in session_ids:
                result = subprocess.run(
                    [self.teleworker_bin, "--abort-session", sid],
                    capture_output=True, timeout=15,
                )
                if result.returncode == 0:
                    logger.info(f"[TeleAgent] Aborted daemon session {sid} for chat {chat_id} (/stop)")
                else:
                    logger.warning(
                        f"[TeleAgent] Failed to abort daemon session {sid} for chat {chat_id}: "
                        f"{result.stderr.decode('utf-8', errors='replace').strip()[:200]}"
                    )
        except FileNotFoundError:
            logger.warning(f"[TeleAgent] tele-worker binary not found; skipping session abort for chat {chat_id}")
        except Exception as e:
            logger.warning(f"[TeleAgent] Session abort failed for chat {chat_id}: {e}")

    def terminate(self, chat_id: int) -> None:
        proc = self.workers.get(chat_id)
        if proc and proc.returncode is None:
            # Flag BEFORE killing so execute_turn sees it after the process exits
            # and skips the auto-restart fallback. Only set when actually killing
            # a live worker — a no-op /stop must not poison the next turn.
            try:
                self._termination_requested.add(chat_id)
            except TypeError:
                pass  # unhashable chat_id; skip flagging
            logger.info(f"[TeleAgent] Preemptively terminating process group for chat {chat_id}")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as e:
                logger.warning(f"Failed to killpg for chat {chat_id}: {e}")
            self.workers.pop(chat_id, None)
        # The SIGKILL above only stops the thin client. The TeleAgent daemon
        # keeps running this chat's session server-side unless we abort it,
        # so /stop must also abort the daemon sessions (leak fix). Abort keeps
        # the session + history alive for seamless resumption.
        if self.abort_server_sessions:
            try:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, self._abort_server_sessions, chat_id)
            except RuntimeError:
                # No running event loop (sync context): abort synchronously.
                self._abort_server_sessions(chat_id)

    def close(self) -> None:
        for cid, proc in list(self.workers.items()):
            if proc.returncode is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    pass
        self.workers.clear()
