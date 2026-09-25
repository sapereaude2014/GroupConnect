"""
Outbound Message & File Delivery for GroupConnect.
Handles parsing <sendfile> attachment tags, delivering files and text to channels,
recording in chat history, and CrossBotRelay broadcast.
"""

import logging
import os
import re
from typing import Any, List, Optional, Set, Tuple

logger = logging.getLogger("groupconnect.delivery")

SENDFILE_TAG_PATTERN = re.compile(
    r"[【\[](?:send_?file|file|send_document|发文件):\s*([^\s`\"'<>|\]】]+)(?:\s*\|\s*([^\]】]+))?[】\]]",
    re.IGNORECASE
)


def extract_outbound_files(reply_text: str, workspace_dir: str) -> List[Tuple[str, Optional[str]]]:
    """
    Extract outbound file attachments from bot reply text.
    Only explicit send tags are recognized:
      【SendFile: /path/to/file】
      【SendFile: /path/to/file | caption】
      [SendFile: /path/to/file]
      [SendFile: /path/to/file | caption]
    Returns a list of (file_path, caption) tuples.
    """
    if not reply_text:
        return []

    found = []
    seen: Set[str] = set()

    for m in SENDFILE_TAG_PATTERN.finditer(reply_text):
        raw_path = m.group(1).strip().strip("`'\"")
        caption = m.group(2).strip() if m.group(2) else None
        path = raw_path if os.path.isabs(raw_path) else os.path.join(workspace_dir, raw_path)
        if os.path.isfile(path) and path not in seen:
            seen.add(path)
            found.append((path, caption))

    return found


def strip_sendfile_tags(text: str) -> str:
    """Remove outbound send tags from reply text so internal markup doesn't appear in chat."""
    if not text:
        return ""
    cleaned = SENDFILE_TAG_PATTERN.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


class OutboundDelivery:
    """Delivers formatted messages, files, and broadcasts to channels and peers."""

    def __init__(
        self,
        channel: Any,
        context_mgr: Any,
        workspace_dir: str,
        bot_name: str,
        bot_username: str,
        relay: Optional[Any] = None
    ):
        self.channel = channel
        self.context_mgr = context_mgr
        self.workspace_dir = workspace_dir
        self.bot_name = bot_name
        self.bot_username = bot_username
        self.relay = relay

    async def deliver(
        self,
        chat_id: Any,
        reply_text: str,
        reply_to_msg_id: Any = None,
        chat_type: str = "group",
        hop_count: int = 0
    ) -> Tuple[Optional[Any], str]:
        """
        Delivers clean text and outbound files to channel.
        Records clean text into context and broadcasts to relay.
        Returns (sent_msg_id, clean_reply_text).
        """
        outbound_files = extract_outbound_files(reply_text, self.workspace_dir)
        clean_reply_text = strip_sendfile_tags(reply_text)

        sent_msg_id = None
        try:
            if clean_reply_text and clean_reply_text.strip():
                sent_msg_id = await self.channel.send_reply(chat_id, clean_reply_text, reply_to_msg_id=reply_to_msg_id)
            elif not outbound_files:
                # No files and empty text: trigger default fallback message
                sent_msg_id = await self.channel.send_reply(chat_id, clean_reply_text, reply_to_msg_id=reply_to_msg_id)
        except Exception as e:
            logger.error(f"[DELIVERY] Failed to deliver reply to chat {chat_id}: {e}")

        for file_path, file_caption in outbound_files:
            try:
                logger.info(f"[DELIVERY] Delivering outbound attachment: {file_path} (caption={file_caption}) to chat {chat_id}")
                await self.channel.send_file(
                    chat_id=chat_id,
                    file_path=file_path,
                    caption=file_caption,
                    reply_to_msg_id=sent_msg_id or reply_to_msg_id
                )
            except Exception as e:
                logger.error(f"[DELIVERY] Failed to deliver outbound attachment {file_path} to chat {chat_id}: {e}")

        # Record in history
        self.context_mgr.record_message(
            chat_id=chat_id,
            sender_name=f"{self.bot_name} (@{self.bot_username})",
            text=clean_reply_text,
            msg_id=sent_msg_id,
            is_bot_reply=True,
            bot_username=self.bot_username,
            reply_to_msg_id=reply_to_msg_id or 0
        )

        # Broadcast via relay
        if self.relay:
            try:
                await self.relay.broadcast_reply(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    msg_id=sent_msg_id or 0,
                    text=clean_reply_text,
                    hop_count=hop_count
                )
            except Exception as e:
                logger.warning(f"[DELIVERY] Failed to broadcast reply via relay: {e}")

        return sent_msg_id, clean_reply_text
