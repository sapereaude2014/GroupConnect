"""
Natural Language Fast Lane Pattern Executor for GroupConnect.
Matches regex patterns for device control and script execution, bypassing LLM routing.
Supports per-device concurrency locking.
"""

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("groupconnect.pattern")


class PatternExecutor:
    """Manages natural language pattern matching, per-device locking, and script execution."""

    def __init__(
        self,
        pattern_configs: List[Dict[str, Any]],
        custom_commands_map: Dict[str, Dict[str, Any]],
        command_dispatcher: Any,
        channel: Any,
        resume_complete_fn: Optional[Callable[[Any, Any, str], None]] = None
    ):
        self.command_dispatcher = command_dispatcher
        self.channel = channel
        self.resume_complete_fn = resume_complete_fn
        self.patterns: List[Dict[str, Any]] = []

        for pc in (pattern_configs or []):
            pattern_str = pc.get("pattern", "")
            if not pattern_str:
                continue
            cmd_name = str(pc.get("command", "")).strip().lower().lstrip("/")
            if cmd_name in custom_commands_map:
                pc["_cmd_cfg"] = custom_commands_map[cmd_name]
            elif pc.get("script"):
                if not cmd_name:
                    cmd_name = f"pattern_{len(self.patterns) + 1}"
                pc["_cmd_cfg"] = {
                    "command": cmd_name,
                    "script": pc.get("script", ""),
                    "pass_args": bool(pc.get("pass_args", True)),
                    "lock": bool(pc.get("lock", True)),
                    "ack_message": pc.get("ack_message", ""),
                    "success_message": pc.get("success_message", ""),
                    "error_message": pc.get("error_message", ""),
                    "default_args": list(pc.get("default_args", [])),
                    "force_arg": pc.get("force_arg", ""),
                }
            else:
                logger.warning(
                    f"Pattern command skipped (needs 'command' or 'script'): {pattern_str[:50]}"
                )
                continue
            try:
                pc["_compiled"] = re.compile(pattern_str)
                self.patterns.append(pc)
                logger.info(f"Pattern command registered: pattern='{pattern_str[:50]}' -> {cmd_name}")
            except re.error as e:
                logger.warning(f"Invalid regex in pattern_commands: {e}")

    @property
    def running_locks(self) -> Set[str]:
        return getattr(self.command_dispatcher, "running_commands", set())

    def acquire_lock(self, key: str) -> bool:
        """Acquire a per-device command lock."""
        clean = str(key).strip().lower()
        if clean in self.running_locks:
            return False
        self.running_locks.add(clean)
        return True

    def release_lock(self, key: str) -> None:
        """Release a per-device command lock."""
        self.running_locks.discard(str(key).strip().lower())

    def match(self, text: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """Matches a message against registered patterns.
        Returns (matched_pc, clean_text) or None if no match."""
        if not self.patterns or not text:
            return None

        # Clean trailing punctuation
        raw = re.sub(r"[，。！？.!?、…]+$", "", text).strip()
        if not raw:
            return None

        for pc in self.patterns:
            max_len = int(pc.get("max_length", 20))
            if len(raw) <= max_len and pc["_compiled"].search(raw):
                return pc, raw

        return None

    async def execute(
        self,
        chat_id: Any,
        pc: Dict[str, Any],
        text: str,
        reply_to_msg_id: Any = None,
        chat_type: str = "group"
    ) -> None:
        """Executes a pattern-matched command with per-device concurrency locking."""
        cmd_cfg = pc["_cmd_cfg"]
        cmd_name = str(cmd_cfg.get("command", "")).strip().lower()

        lock_key = None
        if cmd_cfg.get("lock", False):
            lock_key = f"{cmd_name}:{text}"
            if not self.acquire_lock(lock_key):
                await self.channel.send_reply(
                    chat_id, f"⏳ `{text}` 正在执行中…", reply_to_msg_id=reply_to_msg_id
                )
                return

        try:
            await self.command_dispatcher.execute_command(
                chat_id, cmd_cfg, text, reply_to_msg_id=reply_to_msg_id, chat_type=chat_type
            )
        finally:
            if lock_key is not None:
                self.release_lock(lock_key)
            if self.resume_complete_fn and reply_to_msg_id:
                try:
                    self.resume_complete_fn(chat_id, reply_to_msg_id, text)
                except Exception as e:
                    logger.warning(f"[PATTERN] Failed to mark resume completed: {e}")
