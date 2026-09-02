"""
Base Channel Protocol for GroupAgent.
Decouples chat platforms (Telegram, Discord, Feishu, WeCom, Slack) from core logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class InboundMessage:
    chat_id: int
    chat_type: str  # 'private', 'group', 'supergroup', 'channel'
    msg_id: int
    sender_name: str
    from_user: Dict[str, Any]
    text: str
    reply_to_msg_id: Optional[int] = None
    reply_preview: str = ""
    is_triggered: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    reply_attachments: List[Dict[str, Any]] = field(default_factory=list)


class BaseChannel(ABC):
    """Abstract interface for all IM messaging platform channels."""

    @abstractmethod
    async def start(self) -> None:
        """Starts the platform listener (polling or webhook)."""
        pass

    @abstractmethod
    async def send_reply(self, chat_id: int, text: str, reply_to_msg_id: Optional[int] = None) -> int:
        """Sends a text reply to the specified chat and returns the sent message ID."""
        pass

    @abstractmethod
    async def send_typing_action(self, chat_id: int) -> None:
        """Sends a typing / working heartbeat indicator."""
        pass

    @abstractmethod
    async def leave_chat(self, chat_id: int) -> bool:
        """Leaves an unauthorized group / channel."""
        pass
