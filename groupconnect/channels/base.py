"""
Base Channel Protocol for GroupConnect.
Decouples chat platforms (Telegram, Feishu, WeCom, Discord, Slack) from core logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class InboundMessage:
    chat_id: Union[int, str]
    chat_type: str  # 'private', 'group', 'supergroup', 'channel'
    msg_id: Union[int, str]
    sender_name: str
    from_user: Dict[str, Any]
    text: str
    reply_to_msg_id: Optional[Union[int, str]] = None
    reply_preview: str = ""
    is_triggered: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    reply_attachments: List[Dict[str, Any]] = field(default_factory=list)


class BaseChannel(ABC):
    """Abstract interface for all IM messaging platform channels."""

    @abstractmethod
    async def start(self) -> None:
        """Starts the platform listener (polling, websocket, or webhook)."""
        pass

    @abstractmethod
    async def send_reply(self, chat_id: Union[int, str], text: str, reply_to_msg_id: Optional[Union[int, str]] = None) -> Optional[Union[int, str]]:
        """Sends a text reply to the specified chat and returns the sent message ID."""
        pass

    @abstractmethod
    async def send_typing_action(self, chat_id: Union[int, str]) -> None:
        """Sends a typing / working heartbeat indicator."""
        pass

    @abstractmethod
    async def leave_chat(self, chat_id: Union[int, str]) -> bool:
        """Leaves an unauthorized group / channel."""
        pass
