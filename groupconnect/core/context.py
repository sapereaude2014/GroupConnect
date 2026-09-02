"""
Sliding Window Context & Message History Manager for GroupAgent.
Maintains in-memory deques for immediate recall and logs structured JSONL to disk monthly.
"""

import collections
import datetime
import json
import logging
import os
import time
from typing import Any, Deque, Dict, List, Optional

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
    """Manages chat buffer history, incremental delta tracking, and disk logging."""

    def __init__(self, max_history_len: int = 30, chat_logs_dir: str = "./inbox/chat_logs", idle_timeout_mins: int = 30):
        self.max_history_len = max_history_len
        self.chat_logs_dir = chat_logs_dir
        self.idle_timeout_mins = idle_timeout_mins

        self.buffers: Dict[int, Deque[Dict[str, Any]]] = {}
        self.sessions: Dict[int, Dict[str, Any]] = {}

        os.makedirs(self.chat_logs_dir, exist_ok=True)

    def get_buffer(self, chat_id: int) -> Deque[Dict[str, Any]]:
        if chat_id not in self.buffers:
            self.buffers[chat_id] = collections.deque(maxlen=self.max_history_len)
        return self.buffers[chat_id]

    def get_session(self, chat_id: int) -> Dict[str, Any]:
        now = time.time()
        sess = self.sessions.get(chat_id)
        if sess:
            if self.idle_timeout_mins > 0 and (now - sess.get("last_active", 0)) > (self.idle_timeout_mins * 60):
                logger.info(f"Session for chat {chat_id} expired after {self.idle_timeout_mins}m idle.")
                sess = None

        if not sess:
            sess = {
                "conversation_id": None,
                "last_active": now,
                "turns": 0,
                "last_bot_msg_id": 0,
            }
            self.sessions[chat_id] = sess
        return sess

    def reset_session(self, chat_id: int) -> None:
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
        chat_id: int,
        sender_name: str,
        text: str,
        msg_id: int = 0,
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

    def build_group_context(self, chat_id: int, since_msg_id: int = 0) -> str:
        """
        Builds the context string from buffer.
        If since_msg_id > 0, returns only incremental messages after that message ID.
        """
        buf = self.get_buffer(chat_id)
        if not buf:
            return ""

        lines = []
        for item in buf:
            if since_msg_id > 0 and item.get("msg_id", 0) <= since_msg_id:
                continue
            line = f"[{item['time']}] {item['sender']}{item['reply_info']}: {item['text']}"
            lines.append(line)

        return "\n".join(lines)
