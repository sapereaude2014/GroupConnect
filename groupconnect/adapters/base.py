"""
Base Abstract Adapter and Dynamic Adapter Registry for Local CLI Agent Harnesses.
Supports: Google Antigravity, Anthropic Claude Code, OpenAI Codex, OpenCode.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Type


@dataclass
class AdapterMetadata:
    name: str
    display_name: str
    aliases: List[str]


ADAPTER_REGISTRY: Dict[str, Type["BaseAgentAdapter"]] = {}
ADAPTER_METADATA: Dict[str, AdapterMetadata] = {}


def register_adapter(name: str, display_name: str, aliases: Optional[List[str]] = None):
    """Decorator to register a new CLI agent harness adapter dynamically."""
    def decorator(cls: Type["BaseAgentAdapter"]):
        norm_name = name.lower()
        all_aliases = [norm_name] + [a.lower() for a in (aliases or [])]
        meta = AdapterMetadata(name=norm_name, display_name=display_name, aliases=all_aliases)
        ADAPTER_METADATA[norm_name] = meta
        for alias in all_aliases:
            ADAPTER_REGISTRY[alias] = cls
        return cls
    return decorator


def get_adapter_class(engine_name: str) -> Type["BaseAgentAdapter"]:
    name_clean = engine_name.lower().strip()
    if name_clean not in ADAPTER_REGISTRY:
        supported = ", ".join(sorted(ADAPTER_METADATA.keys()))
        raise ValueError(f"Unsupported engine_type '{engine_name}'. Supported harnesses: {supported}")
    return ADAPTER_REGISTRY[name_clean]


class BaseAgentAdapter(ABC):
    """Abstract interface for CLI-based AI agent runners."""

    @abstractmethod
    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Executes a single conversation turn.

        Returns:
            Tuple[Optional[str], Optional[str]]: (response_text, new_or_updated_conversation_id)
            If response_text is None, turn was cancelled.
        """
        pass

    @abstractmethod
    def terminate(self, chat_id: int) -> None:
        """Immediately terminates and aborts active generation for the chat session."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Cleans up all worker processes and persistent subprocesses."""
        pass
