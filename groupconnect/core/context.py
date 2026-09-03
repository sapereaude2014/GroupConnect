"""
Sliding Window Context & Message History Manager for GroupConnect.
Maintains in-memory deques for immediate recall, logs structured JSONL to disk monthly,
and rehydrates historical context upon restart.
"""

import collections
import datetime
import glob
import json
import logging
import os
import time
from typing import Any, Deque, Dict, List, Optional, Union

logger = logging.getLogger("groupconnect.context")


def format_sender(from_user: Dict[str, Any]) -> str:
    """Formats a user dictionary into a readable display name."""
    first_name = from_user.get("first_name", "")
    last_name = from_user.get("last_name", "")
    full_name = f"{first_name} {last_name}".strip() or "Unknown User"
    username = from_user.get("username")
    if username:
        return f"{full_name} (@{username})"
    return full_name


class ContextManager:
    """Manages chat buffer history, incremental delta tracking, disk logging, and warm restart rehydration."""

    def __init__(self, max_history_len: int = 30, chat_logs_dir: str = "./inbox/chat_logs", idle_timeout_mins: int = 30):
        self.max_history_len = max_history_len
        self.chat_logs_dir = os.path.abspath(chat_logs_dir)
        self.idle_timeout_mins = idle_timeout_mins

        self.buffers: Dict[Union[int, str], Deque[Dict[str, Any]]] = {}
        self.sessions: Dict[Union[int, str], Dict[str, Any]] = {}

        os.makedirs(self.chat_logs_dir, exist_ok=True)
        self.rehydrate_all()

    def _rehydrate_buffer_from_disk(self, chat_id: Union[int, str]) -> Deque[Dict[str, Any]]:
        """Restores recent sliding window messages from persistent JSONL logs on disk."""
        buf = collections.deque(maxlen=self.max_history_len)
        try:
            pattern = os.path.join(self.chat_logs_dir, f"chat_{chat_id}_*.jsonl")
            matching_files = sorted(glob.glob(pattern), reverse=True)

            collected_lines: List[str] = []
            for file_path in matching_files:
                if len(collected_lines) >= self.max_history_len:
                    break
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        lines = [line.strip() for line in f if line.strip()]
                        needed = self.max_history_len - len(collected_lines)
                        collected_lines = lines[-needed:] + collected_lines
                except Exception as e:
                    logger.warning(f"Error reading chat log file {file_path}: {e}")

            for line in collected_lines:
                try:
                    item = json.loads(line)
                    buf.append(item)
                except Exception:
                    pass

            if buf:
                logger.info(f"Rehydrated {len(buf)} historical messages into sliding window for chat {chat_id}")
        except Exception as e:
            logger.warning(f"Failed to rehydrate chat buffer for {chat_id}: {e}")

        return buf

    def rehydrate_all(self) -> None:
        """Discovers and rehydrates all chat buffers found in chat_logs_dir upon startup."""
        try:
            pattern = os.path.join(self.chat_logs_dir, "chat_*_*.jsonl")
            for fpath in glob.glob(pattern):
                fname = os.path.basename(fpath)
                # Filename format: chat_{chat_id}_{YYYY-MM}.jsonl
                parts = fname.split("_")
                if len(parts) >= 3:
                    cid_str = parts[1]
                    try:
                        cid: Union[int, str] = int(cid_str)
                    except ValueError:
                        cid = cid_str
                    if cid not in self.buffers:
                        self.buffers[cid] = self._rehydrate_buffer_from_disk(cid)
        except Exception as e:
            logger.warning(f"Error rehydrating all chat buffers: {e}")

    def get_buffer(self, chat_id: Union[int, str]) -> Deque[Dict[str, Any]]:
        if chat_id not in self.buffers:
            self.buffers[chat_id] = self._rehydrate_buffer_from_disk(chat_id)
        return self.buffers[chat_id]

    def get_session(self, chat_id: Union[int, str]) -> Dict[str, Any]:
        now = time.time()
        sess = self.sessions.get(chat_id)
        if sess:
            if self.idle_timeout_mins > 0 and (now - sess.get("last_active", 0)) > (self.idle_timeout_mins * 60):
                logger.info(f"Session for chat {chat_id} expired after {self.idle_timeout_mins}m idle.")
                sess = None

        if not sess:
            # Check if there is a recent bot reply in the rehydrated buffer to restore last_bot_msg_id
            last_bot_id = 0
            buf = self.get_buffer(chat_id)
            for item in reversed(buf):
                if item.get("is_bot") and item.get("msg_id"):
                    last_bot_id = item.get("msg_id")
                    break

            sess = {
                "conversation_id": None,
                "last_active": now,
                "turns": 0,
                "last_bot_msg_id": last_bot_id,
            }
            self.sessions[chat_id] = sess
        return sess

    def reset_session(self, chat_id: Union[int, str]) -> None:
        self.sessions[chat_id] = {
            "conversation_id": None,
            "last_active": time.time(),
            "turns": 0,
            "last_bot_msg_id": 0,
        }
        if chat_id in self.buffers:
            self.buffers[chat_id].clear()

    def record_message(
        self,
        chat_id: Union[int, str],
        sender_name: str,
        text: str,
        msg_id: Union[int, str] = 0,
        is_bot_reply: bool = False,
        reply_preview: str = "",
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        buf = self.get_buffer(chat_id)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        reply_info = f" [In reply to: \"{reply_preview}\"]" if reply_preview else ""
        item = {
            "time": now_str,
            "msg_id": msg_id,
            "sender": sender_name,
            "text": text,
            "reply_info": reply_info,
            "is_bot": is_bot_reply,
            "attachments": attachments or []
        }
        buf.append(item)

        # Append to monthly JSONL file
        try:
            month_str = datetime.datetime.now().strftime("%Y-%m")
            log_file = os.path.join(self.chat_logs_dir, f"chat_{chat_id}_{month_str}.jsonl")
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Failed to persist chat log: {e}")

        return item

    def build_group_context(self, chat_id: Union[int, str], since_msg_id: Union[int, str] = 0) -> str:
        """
        Builds the context string from buffer.
        If since_msg_id > 0, returns only incremental messages after that message ID.
        """
        buf = self.get_buffer(chat_id)
        if not buf:
            return ""

        lines = []
        for item in buf:
            if since_msg_id and str(item.get("msg_id", "")) == str(since_msg_id):
                continue
            if since_msg_id and isinstance(since_msg_id, int) and isinstance(item.get("msg_id"), int):
                if item.get("msg_id", 0) <= since_msg_id:
                    continue

            line = f"[{item['time']}] {item['sender']}{item['reply_info']}: {item['text']}"
            lines.append(line)

        return "\n".join(lines)
