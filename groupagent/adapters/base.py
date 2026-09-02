"""
Base Agent Adapter Protocol for GroupAgent.
Decouples the chat gateway from any specific AI agent CLI or LLM API backend.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class BaseAgentAdapter(ABC):
    """Abstract interface for all Agent backends (CLI tools, Local LLMs, API endpoints)."""

    @abstractmethod
    async def execute_turn(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
        chat_id: Optional[int] = None,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Executes a turn and returns (response_text, new_conversation_id).
        If cancelled or terminated via /stop, returns (None, current_cid).
        """
        pass

    @abstractmethod
    def terminate(self, chat_id: int) -> None:
        """Immediately terminates in-flight task / worker for a given chat."""
        pass

    @abstractmethod
    def close(self) -> None:
        """Shuts down all resources and child workers."""
        pass
