"""
Configuration manager for GroupConnect.
Loads and validates settings from JSON configuration files.
Enforces secure-by-default allowlist policies.
"""

import json
import os
from typing import Any, Dict, List, Optional, Set


class GatewayConfig:
    def __init__(self, data: Dict[str, Any]):
        self.raw: Dict[str, Any] = data

        # Platform Settings
        self.platform: str = data.get("platform", "telegram").lower()
        self.bot_token: str = data.get("bot_token", "")
        self.bot_username: str = data.get("bot_username", "group_agent_bot").lower().lstrip("@")
        self.bot_name: str = data.get("bot_name", "GroupConnect")

        # Workspace & Storage Settings
        self.workspace_dir: str = os.path.abspath(data.get("workspace_dir", "./workspace"))
        self.attachments_dir: str = os.path.join(self.workspace_dir, "inbox", "attachments")
        self.chat_logs_dir: str = os.path.join(self.workspace_dir, "inbox", "chat_logs")

        # Agent Engine Settings (Supports: antigravity, claude, codex, opencode)
        self.engine_type: str = data.get("engine_type", "antigravity").lower()
        self.model: Optional[str] = data.get("model")
        self.agy_bin: str = data.get("agy_bin", "agy")
        self.claude_bin: str = data.get("claude_bin", "claude")
        self.codex_bin: str = data.get("codex_bin", "codex")
        self.opencode_bin: str = data.get("opencode_bin", "opencode")

        # Context & Window Settings
        self.max_history_len: int = int(data.get("max_history_len", 30))
        self.timeout_secs: int = int(data.get("timeout_secs", 180))
        self.session_idle_timeout_mins: int = int(data.get("session_idle_timeout_mins", 30))
        self.max_chunk_size: int = int(data.get("max_chunk_size", 3800))
        self.typing_interval_secs: float = float(data.get("typing_interval_secs", 4.0))

        # Security Allowlist Gatekeeper (Secure-by-Default)
        self.allow_open_access: bool = bool(data.get("allow_open_access", False))
        self.allowed_chat_ids: Set[int] = set(int(x) for x in data.get("allowed_chat_ids", []))
        self.allowed_user_ids: Set[int] = set(int(x) for x in data.get("allowed_user_ids", []))
        self.allowed_usernames: Set[str] = set(
            str(x).lower().lstrip("@") for x in data.get("allowed_usernames", [])
        )

        # Ensure required directories exist
        os.makedirs(self.attachments_dir, exist_ok=True)
        os.makedirs(self.chat_logs_dir, exist_ok=True)

    @classmethod
    def from_file(cls, path: str) -> "GatewayConfig":
        if not os.path.exists(path):
            raise FileNotFoundError(f"Configuration file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

    def to_dict(self) -> Dict[str, Any]:
        return self.raw
