"""
Base Channel Protocol and Dynamic Channel Registry for GroupConnect.
Allows new platform channels to register dynamically without modifying core engine or CLI wizard.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional, Type, Union


@dataclass
class ChannelField:
    key: str
    label: str
    default: Optional[Union[str, int]] = None
    is_secret: bool = False
    is_int: bool = False


@dataclass
class ChannelMetadata:
    name: str
    display_name: str
    aliases: List[str]
    fields: List[ChannelField]


CHANNEL_REGISTRY: Dict[str, Type["BaseChannel"]] = {}
CHANNEL_METADATA: Dict[str, ChannelMetadata] = {}


def register_channel(
    name: str,
    display_name: str,
    aliases: Optional[List[str]] = None,
    fields: Optional[List[ChannelField]] = None
):
    """Decorator to register a new platform channel dynamically."""
    def decorator(cls: Type["BaseChannel"]):
        normalized_name = name.lower()
        all_aliases = [normalized_name] + [a.lower() for a in (aliases or [])]
        meta = ChannelMetadata(
            name=normalized_name,
            display_name=display_name,
            aliases=all_aliases,
            fields=fields or []
        )
        CHANNEL_METADATA[normalized_name] = meta
        for alias in all_aliases:
            CHANNEL_REGISTRY[alias] = cls
        return cls
    return decorator


def get_channel_class(platform_name: str) -> Type["BaseChannel"]:
    """Resolves channel class by name or alias."""
    name_clean = platform_name.lower().strip()
    if name_clean not in CHANNEL_REGISTRY:
        supported = ", ".join(sorted(CHANNEL_METADATA.keys()))
        raise ValueError(f"Unsupported platform channel '{platform_name}'. Supported channels: {supported}")
    return CHANNEL_REGISTRY[name_clean]


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
