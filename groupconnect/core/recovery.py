"""
Crash Recovery and Resume Manager for GroupConnect.
Detects unanswered messages across chats on startup and safely re-dispatches them,
with poison message quarantine to prevent crash loops.
"""

from datetime import datetime
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from groupconnect.channels.base import InboundMessage
from groupconnect.core.parser import parse_bot_command

logger = logging.getLogger("groupconnect.recovery")


class ResumeManager:
    """Detects unanswered human messages upon gateway startup and re-dispatches them."""

    def __init__(
        self,
        context_mgr: Any,
        bot_username: str,
        window_seconds: int = 300,
        max_retries: int = 2,
        allowed_chat_ids: Optional[List[Any]] = None,
        state_file: Optional[str] = None
    ):
        self.context_mgr = context_mgr
        self.bot_username = bot_username
        self.window_seconds = window_seconds
        self.max_retries = max_retries
        self.allowed_chat_ids = allowed_chat_ids or []
        self.state_file = state_file

        chat_logs = getattr(context_mgr, "chat_logs_dir", None)
        if not self.state_file and isinstance(chat_logs, str) and chat_logs.strip():
            prefix = f".recovery_state_{bot_username}.json" if bot_username else ".recovery_state.json"
            self.state_file = os.path.join(chat_logs, prefix)

        # Poison message tracking: {msg_key: retry_count}
        self._retry_counts: Dict[str, int] = {}
        self._poison_quarantine: Set[str] = set()

        self._load_state()

    def _load_state(self) -> None:
        """Loads persisted retry counts and quarantined message keys across restarts."""
        if not self.state_file or not os.path.isfile(self.state_file):
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._retry_counts = data.get("retries", {})
                self._poison_quarantine = set(data.get("quarantine", []))
        except Exception as e:
            logger.warning(f"[RESUME] Failed to load recovery state from {self.state_file}: {e}")

    def _save_state(self) -> None:
        """Persists retry counts and quarantined message keys to disk."""
        if not self.state_file:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_file)), exist_ok=True)
            tmp_file = f"{self.state_file}.tmp.{os.getpid()}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "retries": self._retry_counts,
                    "quarantine": sorted(list(self._poison_quarantine)),
                    "updated_at": time.time()
                }, f, indent=2)
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            logger.warning(f"[RESUME] Failed to save recovery state to {self.state_file}: {e}")

    def mark_completed(self, chat_id: Any, msg_id: Any, raw: str = "") -> None:
        """Clears retry state for a message that completed successfully."""
        msg_key = f"{chat_id}:{msg_id}:{raw[:40]}"
        if msg_key in self._retry_counts:
            del self._retry_counts[msg_key]
            self._save_state()

    def _evaluate_candidate(
        self,
        raw: str,
        chat_type: str,
        is_arbiter: bool
    ) -> Tuple[bool, bool]:
        """Determines whether a message is an eligible resume candidate for THIS bot.
        Returns (is_candidate, is_triggered).
        If not a candidate, the message is skipped entirely (no retries incremented).
        """
        stripped = (raw or "").strip()
        bot_tag = f"@{self.bot_username}".lower()
        raw_lower = raw.lower()

        # Slash commands: strictly isolated from natural conversation routing
        if stripped.startswith("/"):
            cmd, target_bot, _ = parse_bot_command(stripped, self.bot_username)
            if not cmd:
                return False, False
            if target_bot is not None and target_bot.lower() != self.bot_username.lower():
                return False, False
            return True, True

        if chat_type == "private":
            return True, True

        # Group chat: check if explicitly tagged for this bot
        if bot_tag in raw_lower:
            return True, True

        # Check if explicitly tagged for ANOTHER bot or user mention
        other_mention = re.search(r"@[a-zA-Z][a-zA-Z0-9_]{4,}(?!\.\w)|<@[!&]?\w+>", raw)
        if other_mention:
            return False, False

        # Untriggered message (no @mention) in group chat:
        # Only the Arbiter bot may re-dispatch untriggered messages to Jev.
        if not is_arbiter:
            return False, False

        return True, False

    def _try_dispatch(
        self,
        entry: Dict[str, Any],
        chat_id: Any,
        is_arbiter: bool,
        directly_answered_ids: Optional[Set[str]] = None,
    ) -> Optional[InboundMessage]:
        """Validates candidate eligibility, tracks retries, and constructs InboundMessage."""
        raw = str(entry.get("text", ""))
        msg_id = entry.get("msg_id", 0)

        if directly_answered_ids and str(msg_id) in directly_answered_ids:
            return None

        try:
            chat_type = "private" if int(chat_id) > 0 else "group"
        except (TypeError, ValueError):
            chat_type = "group"

        is_cand, is_trig = self._evaluate_candidate(raw, chat_type, is_arbiter)
        if not is_cand:
            return None

        msg_key = f"{chat_id}:{msg_id}:{raw[:40]}"

        # Poison message quarantine check
        retries = self._retry_counts.get(msg_key, 0)
        if retries >= self.max_retries:
            if msg_key not in self._poison_quarantine:
                logger.error(
                    f"[RESUME] Poison message quarantined in chat {chat_id} "
                    f"(retried {retries} times without completion): '{raw[:40]}'. Skipping."
                )
                self._poison_quarantine.add(msg_key)
                self._save_state()
            return None

        self._retry_counts[msg_key] = retries + 1
        self._save_state()

        from_user = (
            {"id": chat_id, "first_name": str(entry.get("sender", ""))}
            if chat_type == "private"
            else {"first_name": str(entry.get("sender", ""))}
        )
        inbound = InboundMessage(
            chat_id=chat_id,
            chat_type=chat_type,
            msg_id=msg_id,
            sender_name=str(entry.get("sender", "")),
            from_user=from_user,
            text=raw,
            is_triggered=is_trig,
            is_resume=True
        )
        logger.info(
            f"[RESUME] Re-dispatching unanswered message in chat {chat_id}: '{raw[:30]}'"
        )
        return inbound

    def find_unanswered_messages(
        self,
        window_seconds: Optional[int] = None,
        allowed_chat_ids: Optional[List[Any]] = None,
        is_arbiter: bool = True
    ) -> List[Tuple[Any, InboundMessage]]:
        """Scans active context buffers for human messages that received no bot reply.
        Returns list of (chat_id, InboundMessage) ready to be processed."""
        window = self.window_seconds if window_seconds is None else window_seconds
        if window <= 0:
            return []

        allowed = self.allowed_chat_ids if allowed_chat_ids is None else allowed_chat_ids
        resumable = []

        buffers = getattr(self.context_mgr, "buffers", {})
        for chat_id, buf in list(buffers.items()):
            try:
                if not buf:
                    continue
                if allowed and (chat_id not in allowed and str(chat_id) not in {str(x) for x in allowed}):
                    continue

                # Watermark scan: locate the newest bot reply that records which human
                # message it answered (reply_to_msg_id). That quoted message is the
                # watermark — everything the conversation has already covered up to and
                # including it is settled. Human messages AFTER the watermark (and
                # inside the freshness window) are unanswered resume candidates.
                # Bot replies without reply_to_msg_id (pre-linkage data / fast-lane
                # receipts) are skipped: the newest LINKED reply wins. If the buffer
                # has no linked replies at all, fall back to the legacy positional
                # backward scan so old deployments keep their previous behavior.
                watermark_idx = None
                directly_answered_ids = set()
                for i in range(len(buf) - 1, -1, -1):
                    entry = buf[i]
                    if not entry.get("is_bot"):
                        continue
                    reply_target = str(entry.get("reply_to_msg_id") or "")
                    if reply_target and reply_target != "0":
                        directly_answered_ids.add(reply_target)
                        for j in range(len(buf)):
                            if (str(buf[j].get("msg_id", "")) == reply_target
                                    and not buf[j].get("is_bot")):
                                if watermark_idx is None or j > watermark_idx:
                                    watermark_idx = j
                                break

                if watermark_idx is not None:
                    # Collect every human message after the watermark (oldest first)
                    candidates = []
                    for i in range(watermark_idx + 1, len(buf)):
                        entry = buf[i]
                        if entry.get("is_bot") or not str(entry.get("text", "")).strip():
                            continue
                        try:
                            msg_time = datetime.strptime(str(entry.get("time", "")), "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue
                        if not (0 <= time.time() - msg_time.timestamp() <= window):
                            continue
                        candidates.append(entry)

                    for last in candidates:
                        inbound = self._try_dispatch(last, chat_id, is_arbiter, directly_answered_ids)
                        if inbound:
                            resumable.append((chat_id, inbound))
                    continue

                # Legacy fallback: positional backward scan (pre-linkage data / tests without reply_to_msg_id)
                last_human_idx = None
                seen_bot = False
                for i in range(len(buf) - 1, -1, -1):
                    if buf[i].get("is_bot"):
                        seen_bot = True
                        continue
                    if not str(buf[i].get("text", "")).strip():
                        continue
                    if not seen_bot:
                        last_human_idx = i
                        break
                    seen_bot = False

                if last_human_idx is None:
                    continue

                last = buf[last_human_idx]
                try:
                    msg_time = datetime.strptime(str(last.get("time", "")), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if not (0 <= time.time() - msg_time.timestamp() <= window):
                    continue

                inbound = self._try_dispatch(last, chat_id, is_arbiter)
                if inbound:
                    resumable.append((chat_id, inbound))
            except Exception as e:
                logger.warning(f"[RESUME] Failed to resume chat {chat_id}: {e}")

        return resumable
