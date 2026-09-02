"""
Antigravity (agy) Adapter with Resident Worker Pool.
Enables zero-cold-start streaming execution and process group isolation.
"""

import asyncio
import json
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from groupconnect.adapters.base import BaseAgentAdapter

logger = logging.getLogger("groupconnect.adapters.antigravity")


def kill_process_group(proc: Optional[asyncio.subprocess.Process], sig=signal.SIGTERM) -> None:
    """Terminates an entire subprocess group (PGID == PID)."""
    if not proc or proc.pid is None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    except Exception as e:
        logger.warning(f"Error killing process group {proc.pid}: {e}")


class ResidentAgyWorker:
    """Persistent Antigravity CLI process communicating over stdin/stdout stream-json NDJSON."""

    def __init__(self, chat_id: int, agy_bin: str, workspace_dir: str, model: str, conversation_id: Optional[str] = None):
        self.chat_id = chat_id
        self.agy_bin = agy_bin
        self.workspace_dir = workspace_dir
        self.model = model
        self.conversation_id = conversation_id
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.last_active = time.time()

    async def start(self) -> None:
        cmd = [
            self.agy_bin,
            "--add-dir", self.workspace_dir,
            "--dangerously-skip-permissions",
            "--model", self.model,
            "--input-format", "stream-json",
            "--output-format", "stream-json",
        ]
        if self.conversation_id:
            cmd.extend(["--conversation", self.conversation_id])

        logger.info(f"[Worker:{self.chat_id}] Spawning resident agy process (resume={bool(self.conversation_id)})...")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.workspace_dir,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True  # POSIX Process Group isolation
        )

        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), timeout=15.0)
            if line:
                data = json.loads(line.decode("utf-8", errors="replace").strip())
                if data.get("event") == "init":
                    self.conversation_id = data.get("conversation_id") or self.conversation_id
                    logger.info(f"[Worker:{self.chat_id}] Resident worker ready (CID: {self.conversation_id})")
        except Exception as e:
            logger.warning(f"[Worker:{self.chat_id}] Init event read warning: {e}")

    async def execute_turn(self, prompt: str, is_cancelled: Callable_Cancelled = None) -> Tuple[Optional[str], Optional[str]]:
        if self.proc is None or self.proc.returncode is not None:
            await self.start()

        self.last_active = time.time()
        turn_msg = {
            "event": "user",
            "message": {
                "content": prompt
            }
        }

        try:
            input_bytes = (json.dumps(turn_msg, ensure_ascii=False) + "\n").encode("utf-8")
            self.proc.stdin.write(input_bytes)
            await self.proc.stdin.drain()
        except Exception as e:
            logger.error(f"[Worker:{self.chat_id}] Failed to write to resident stdin: {e}, restarting worker...")
            self.close()
            await self.start()
            self.proc.stdin.write((json.dumps(turn_msg, ensure_ascii=False) + "\n").encode("utf-8"))
            await self.proc.stdin.drain()

        collected_deltas: List[str] = []
        final_response: Optional[str] = None

        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str:
                continue
            try:
                data = json.loads(line_str)
                evt = data.get("event")
                if evt == "step_update":
                    step = data.get("step_update", {})
                    self.conversation_id = step.get("conversation_id") or self.conversation_id
                    delta = step.get("text_delta")
                    if delta:
                        collected_deltas.append(delta)
                elif evt == "result":
                    res = data.get("result", {})
                    self.conversation_id = res.get("conversation_id") or self.conversation_id
                    if res.get("status") == "ERROR":
                        err_msg = res.get("error") or "Engine execution error"
                        return f"⚠️ Execution error:\n{err_msg}", self.conversation_id
                    final_response = res.get("response")
                    break
            except json.JSONDecodeError:
                pass

        resp = (final_response or "".join(collected_deltas)).strip() or "(Task completed with no text output)"
        return resp, self.conversation_id

    def close(self, sig=signal.SIGTERM) -> None:
        if self.proc:
            kill_process_group(self.proc, sig)
            self.proc = None


class AntigravityAdapter(BaseAgentAdapter):
    """Adapter for Antigravity engine with resident multi-session worker pool."""

    def __init__(self, agy_bin: str, workspace_dir: str, model: str, timeout_secs: int = 180, idle_timeout_mins: int = 30):
        self.agy_bin = agy_bin
        self.workspace_dir = workspace_dir
        self.model = model
        self.timeout_secs = timeout_secs
        self.idle_timeout_mins = idle_timeout_mins

        self.workers: Dict[int, ResidentAgyWorker] = {}
        self.cancelled_chats: Set[int] = set()

    def get_worker(self, chat_id: int, cid: Optional[str] = None) -> ResidentAgyWorker:
        worker = self.workers.get(chat_id)
        if not worker or worker.proc is None or worker.proc.returncode is not None:
            worker = ResidentAgyWorker(chat_id, self.agy_bin, self.workspace_dir, self.model, conversation_id=cid)
            self.workers[chat_id] = worker
        elif cid and worker.conversation_id != cid:
            worker.close()
            worker = ResidentAgyWorker(chat_id, self.agy_bin, self.workspace_dir, self.model, conversation_id=cid)
            self.workers[chat_id] = worker
        return worker

    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        cid_key = chat_id or 0
        worker = self.get_worker(cid_key, cid=conversation_id)

        try:
            task = asyncio.create_task(worker.execute_turn(prompt))
            resp, new_cid = await asyncio.wait_for(task, timeout=self.timeout_secs)
            if cid_key in self.cancelled_chats:
                return None, new_cid
            return resp, new_cid
        except asyncio.TimeoutError:
            logger.error(f"Task timed out after {self.timeout_secs}s for chat {cid_key}")
            self.terminate(cid_key)
            return "⚠️ Request timed out. Please try again.", worker.conversation_id
        except asyncio.CancelledError:
            self.terminate(cid_key)
            return None, worker.conversation_id
        except Exception as e:
            logger.error(f"Execution error in chat {cid_key}: {e}", exc_info=True)
            self.terminate(cid_key)
            if cid_key in self.cancelled_chats:
                return None, worker.conversation_id
            return f"⚠️ Execution error: {e}", worker.conversation_id
        finally:
            self.cancelled_chats.discard(cid_key)

    def terminate(self, chat_id: int) -> None:
        self.cancelled_chats.add(chat_id)
        worker = self.workers.pop(chat_id, None)
        if worker:
            worker.close(signal.SIGTERM)

    def reap_idle_workers(self) -> None:
        now = time.time()
        timeout = self.idle_timeout_mins * 60
        if timeout <= 0:
            return
        expired = [cid for cid, w in self.workers.items() if (now - w.last_active) > timeout]
        for cid in expired:
            logger.info(f"[Reaper] Reaping idle worker for chat {cid}")
            self.terminate(cid)

    def close(self) -> None:
        for cid in list(self.workers.keys()):
            self.terminate(cid)
