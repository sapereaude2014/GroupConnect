"""
Configuration manager for GroupConnect.
Unified configuration loader supporting YAML/JSON with automatic environment variable expansion.
Normalizes human-intent config (groupconnect.yaml) into runtime gateway & autonomous routing state.
"""

import glob
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Union

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

from groupconnect.routing.router import AutonomousConfig

logger = logging.getLogger("groupconnect.config")

ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def load_dotenv_for_config(config_path: Optional[str]) -> None:
    """Loads .env and *.env files in config_path's directory and ~/.config/groupconnect into os.environ (non-overwriting)."""
    search_dirs: List[str] = []
    if config_path:
        cfg_dir = os.path.dirname(os.path.abspath(os.path.expanduser(config_path)))
        if os.path.isdir(cfg_dir):
            search_dirs.append(cfg_dir)
    global_cfg_dir = os.path.expanduser("~/.config/groupconnect")
    if os.path.isdir(global_cfg_dir) and global_cfg_dir not in search_dirs:
        search_dirs.append(global_cfg_dir)

    for d in search_dirs:
        for env_file in [os.path.join(d, ".env")] + sorted(glob.glob(os.path.join(d, "*.env"))):
            if not os.path.isfile(env_file):
                continue
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if line.startswith("export "):
                            line = line[7:].strip()
                        if "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass


def expand_env_vars(obj: Any) -> Any:
    """Recursively expands ${VAR} or ${VAR:-default} in strings, dicts, and lists."""
    if isinstance(obj, str):
        def _replace(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(var_name, default_val)
        return ENV_PATTERN.sub(_replace, obj)
    elif isinstance(obj, dict):
        return {k: expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [expand_env_vars(elem) for elem in obj]
    return obj


def load_raw_config_file(path: str) -> Dict[str, Any]:
    """Loads a YAML or JSON config file with environment variable expansion."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found: {path}")

    load_dotenv_for_config(path)

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Load YAML or JSON
    if path.endswith((".yaml", ".yml")):
        if yaml is None:
            raise ImportError("PyYAML is required to load YAML configuration files. Install via: pip install pyyaml")
        data = yaml.safe_load(content) or {}
    else:
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            if yaml is None:
                raise ImportError("PyYAML is required to load YAML configuration files. Install via: pip install pyyaml")
            data = yaml.safe_load(content) or {}

    return expand_env_vars(data)


class GatewayConfig:
    def __init__(self, data: Dict[str, Any], config_path: Optional[str] = None):
        self.raw: Dict[str, Any] = data
        self.config_path: Optional[str] = os.path.abspath(config_path) if config_path else None

        channel = data.get("channel") if isinstance(data.get("channel"), dict) else data
        bot = data.get("bot") if isinstance(data.get("bot"), dict) else data
        agent = data.get("agent") if isinstance(data.get("agent"), dict) else data
        security = (
            data.get("security")
            if isinstance(data.get("security"), dict)
            else (data.get("allowlist") if isinstance(data.get("allowlist"), dict) else data)
        )
        tuning = data.get("tuning") if isinstance(data.get("tuning"), dict) else data
        zero_at = data.get("zero_at", data.get("autonomous"))

        # Platform Settings
        self.platform: str = str(channel.get("platform", data.get("platform", "telegram"))).lower()
        self.bot_token: str = str(channel.get("token", channel.get("bot_token", data.get("bot_token", "")))).strip()
        self.bot_username: str = (
            str(bot.get("username", bot.get("bot_username", data.get("bot_username", "group_agent_bot"))))
            .lower()
            .lstrip("@")
        )
        self.bot_name: str = str(bot.get("name", bot.get("bot_name", data.get("bot_name", "GroupConnect"))))

        # Channel options
        self.channel_options: Dict[str, Any] = dict(
            channel.get("options", data.get("channel_options", {}))
        )
        for k in (
            "discord_bot_token",
            "slack_bot_token",
            "slack_app_token",
            "feishu_app_id",
            "feishu_app_secret",
            "wecom_corp_id",
            "wecom_corp_secret",
        ):
            if k in data:
                self.channel_options.setdefault(k, data[k])
        if self.platform == "discord":
            self.channel_options.setdefault("discord_bot_token", self.bot_token)
        elif self.platform == "slack":
            self.channel_options.setdefault("slack_bot_token", self.bot_token)
            if "slack_app_token" in channel:
                self.channel_options["slack_app_token"] = channel["slack_app_token"]
        elif self.platform in ("feishu", "lark"):
            if "app_id" in channel:
                self.channel_options["feishu_app_id"] = channel["app_id"]
            if "app_secret" in channel:
                self.channel_options["feishu_app_secret"] = channel["app_secret"]
        elif self.platform == "wecom":
            if "corp_id" in channel:
                self.channel_options["wecom_corp_id"] = channel["corp_id"]
            if "corp_secret" in channel:
                self.channel_options["wecom_corp_secret"] = channel["corp_secret"]

        # Workspace & Storage Settings
        ws_dir = agent.get("workspace", agent.get("workspace_dir", data.get("workspace_dir", "./workspace")))
        self.workspace_dir: str = os.path.abspath(os.path.expanduser(ws_dir))
        self.attachments_dir: str = os.path.join(self.workspace_dir, "inbox", "attachments")
        self.chat_logs_dir: str = os.path.join(self.workspace_dir, "inbox", "chat_logs")

        # Agent Engine Settings
        self.engine_type: str = str(
            agent.get("engine", agent.get("engine_type", data.get("engine_type", "antigravity")))
        ).lower()
        self.model: Optional[str] = agent.get("model", data.get("model"))
        self.agy_bin: str = agent.get("agy_bin", agent.get("bin", data.get("agy_bin", "agy")))
        self.claude_bin: str = agent.get("claude_bin", agent.get("bin", data.get("claude_bin", "claude")))
        self.codex_bin: str = agent.get("codex_bin", agent.get("bin", data.get("codex_bin", "codex")))
        self.opencode_bin: str = agent.get("opencode_bin", agent.get("bin", data.get("opencode_bin", "opencode")))
        self.teleworker_bin: str = agent.get(
            "teleworker_bin", agent.get("bin", data.get("teleworker_bin", "tele-worker"))
        )

        # Soul Persona Settings
        self.soul_path: Optional[str] = data.get("soul_path", bot.get("soul_path"))
        self.souls_dir: Optional[str] = data.get("souls_dir", bot.get("souls_dir"))

        # Context & Window Settings
        self.max_history_len: int = int(tuning.get("max_history_len", data.get("max_history_len", 30)))
        self.timeout_secs: int = int(
            agent.get("timeout_secs", tuning.get("timeout_secs", data.get("timeout_secs", 180)))
        )
        self.output_grace_secs: int = int(tuning.get("output_grace_secs", data.get("output_grace_secs", 15)))
        self.session_idle_timeout_mins: int = int(
            agent.get(
                "session_idle_timeout_mins",
                tuning.get("session_idle_timeout_mins", data.get("session_idle_timeout_mins", 30)),
            )
        )
        self.max_chunk_size: int = int(tuning.get("max_chunk_size", data.get("max_chunk_size", 3800)))
        self.typing_interval_secs: float = float(
            tuning.get("typing_interval_secs", data.get("typing_interval_secs", 4.0))
        )

        # Security Gatekeeper
        self.allow_open_access: bool = bool(
            security.get("allow_open_access", data.get("allow_open_access", False))
        )
        self.allow_group_members_dm: bool = bool(
            security.get("allow_group_members_dm", data.get("allow_group_members_dm", True))
        )
        self.allowed_chat_ids: Set[int] = set(
            int(x) for x in security.get("allowed_chat_ids", security.get("groups", data.get("allowed_chat_ids", [])))
        )
        self.allowed_user_ids: Set[int] = set(
            int(x) for x in security.get("allowed_user_ids", data.get("allowed_user_ids", []))
        )
        self.allowed_usernames: Set[str] = set(
            str(x).lower().lstrip("@")
            for x in security.get("allowed_usernames", security.get("users", data.get("allowed_usernames", [])))
        )

        # Cross-Bot IPC Relay Settings
        ipc_dir_raw = tuning.get("ipc_dir", data.get("ipc_dir", "/tmp/groupconnect_ipc"))
        self.ipc_dir: str = os.path.abspath(os.path.expanduser(ipc_dir_raw))
        self.max_bot_hops: int = int(tuning.get("max_bot_hops", data.get("max_bot_hops", 1)))

        # Custom Slash Commands
        self.custom_commands: List[Dict[str, Any]] = list(data.get("custom_commands", []))
        # Pattern Commands (regex-triggered, bypass LLM routing)
        self.pattern_commands: List[Dict[str, Any]] = list(data.get("pattern_commands", []))
        # Restart resume: re-dispatch recent unanswered human messages on startup (0 disables)
        self.resume_unanswered_secs: int = int(
            tuning.get("resume_unanswered_secs", data.get("resume_unanswered_secs", 300))
        )

        # Ensure required directories exist
        os.makedirs(self.attachments_dir, exist_ok=True)
        os.makedirs(self.chat_logs_dir, exist_ok=True)
        os.makedirs(self.ipc_dir, exist_ok=True)

        # Autonomous Routing (Zero-@)
        self.autonomous_config_path: str = str(data.get("autonomous_config_path", ""))
        self.autonomous_config: Optional[AutonomousConfig] = None
        if zero_at is not None:
            self._setup_autonomous(zero_at, bot, agent, tuning=tuning)
        elif self.autonomous_config_path and os.path.exists(self.autonomous_config_path):
            try:
                self.autonomous_config = AutonomousConfig(self.autonomous_config_path)
            except Exception as e:
                logger.warning(f"Could not load autonomous config from {self.autonomous_config_path}: {e}")

    def validate_credentials(self) -> None:
        """Raises ValueError if required platform credentials (e.g., bot_token) are empty or unexpanded."""
        if self.platform in ("telegram", "discord", "slack"):
            if not self.bot_token or self.bot_token in ("your-telegram-bot-token-here", "YOUR_TELEGRAM_BOT_TOKEN"):
                raise ValueError(
                    f"[Config Error] Missing or empty bot token for '{self.bot_username}' ({self.bot_name}). "
                    f"Ensure the token environment variable is set in ~/.config/groupconnect/guaguahome.env."
                )

    def _setup_autonomous(self, zero_at: Any, bot: Dict[str, Any], agent: Dict[str, Any], tuning: Optional[Dict[str, Any]] = None) -> None:
        """Configures Zero-@ Autonomous routing from unified configuration."""
        if zero_at is False:
            return

        if zero_at is True:
            zero_dict: Dict[str, Any] = {"enabled": True}
        elif isinstance(zero_at, dict):
            zero_dict = dict(zero_at)
        else:
            return

        if not zero_dict.get("enabled", True):
            return

        zero_dict["enabled"] = True
        zero_dict.setdefault("arbiter_bot", self.bot_username)
        zero_dict.setdefault("ipc_dir", self.ipc_dir)
        if tuning and "silence_window_secs" in tuning and "silence_secs" not in zero_dict:
            zero_dict["silence_secs"] = tuning["silence_window_secs"]

        # Roles
        roles = dict(zero_dict.get("roles", {}))
        if self.bot_username not in roles:
            roles[self.bot_username] = agent.get("role", bot.get("role", "General Assistant"))
        zero_dict["roles"] = roles

        # Aliases
        aliases = dict(zero_dict.get("aliases", {}))
        if self.bot_username not in aliases and bot.get("aliases"):
            aliases[self.bot_username] = list(bot.get("aliases", []))
        zero_dict["aliases"] = aliases

        # Allowed chats filter propagation
        if self.allowed_chat_ids and not zero_dict.get("allowed_chat_ids"):
            zero_dict["allowed_chat_ids"] = list(self.allowed_chat_ids)

        self.autonomous_config = AutonomousConfig(zero_dict, path=self.config_path)

    @classmethod
    def from_file(cls, path: str, bot_name: Optional[str] = None) -> "GatewayConfig":
        """Loads GatewayConfig from a JSON or YAML file.
        If file contains 'bots' list and bot_name is specified, returns that bot's config.
        """
        abs_path = os.path.abspath(path)
        data = load_raw_config_file(abs_path)

        if "bots" in data and isinstance(data["bots"], list):
            bots_list = data["bots"]
            if not bots_list:
                raise ValueError("Config file contains empty 'bots' list.")

            chosen = None
            if bot_name:
                target_norm = bot_name.lower().lstrip("@")
                for b in bots_list:
                    b_uname = str(b.get("username", "")).lower().lstrip("@")
                    b_name = str(b.get("name", "")).lower().lstrip("@")
                    if target_norm in (b_uname, b_name):
                        chosen = b
                        break
                if not chosen:
                    names = [b.get("username") or b.get("name", "unnamed") for b in bots_list]
                    raise ValueError(f"Bot '{bot_name}' not found in {path}. Available bots: {names}")
            else:
                chosen = bots_list[0]

            merged = cls._merge_bot_entry(data, chosen)
            return cls(merged, config_path=abs_path)

        return cls(data, config_path=abs_path)

    @classmethod
    def load_all_from_file(cls, path: str) -> List["GatewayConfig"]:
        """Loads all bot configurations defined in a file."""
        abs_path = os.path.abspath(path)
        data = load_raw_config_file(abs_path)

        if "bots" in data and isinstance(data["bots"], list) and len(data["bots"]) > 0:
            configs = []
            for b in data["bots"]:
                merged = cls._merge_bot_entry(data, b)
                configs.append(cls(merged, config_path=abs_path))
            return configs

        return [cls(data, config_path=abs_path)]

    @classmethod
    def _merge_bot_entry(cls, root_data: Dict[str, Any], bot_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Synthesizes a full single-bot config by combining root-level sections with a bot entry."""
        merged: Dict[str, Any] = {
            "channel": dict(root_data.get("channel", {})),
            "security": dict(root_data.get("security", root_data.get("allowlist", {}))),
            "tuning": dict(root_data.get("tuning", {})),
            "custom_commands": list(root_data.get("custom_commands", [])),
            "pattern_commands": list(root_data.get("pattern_commands", [])),
        }

        # Bot identity
        b_name = bot_entry.get("name", bot_entry.get("bot_name", "GroupConnect"))
        b_username = bot_entry.get("username", bot_entry.get("bot_username", b_name)).lower().lstrip("@")
        merged["bot"] = {
            "name": b_name,
            "username": b_username,
            "aliases": bot_entry.get("aliases", []),
            "role": bot_entry.get("role", "Assistant"),
            "souls_dir": bot_entry.get("souls_dir", root_data.get("souls_dir")),
            "soul_path": bot_entry.get("soul_path", root_data.get("soul_path")),
        }

        # Token
        if "token" in bot_entry:
            merged["channel"]["token"] = bot_entry["token"]
        elif "bot_token" in bot_entry:
            merged["channel"]["token"] = bot_entry["bot_token"]

        # Channel options
        if "options" in bot_entry:
            merged["channel"].setdefault("options", {}).update(bot_entry["options"])

        # Agent (inherit root agent defaults, then override per-bot)
        merged["agent"] = dict(root_data.get("agent", {}))
        agent_data = bot_entry.get("agent")
        if isinstance(agent_data, dict):
            merged["agent"].update(agent_data)
        elif isinstance(agent_data, str):
            merged["agent"]["engine"] = agent_data

        if "workspace" in bot_entry:
            merged["agent"]["workspace"] = bot_entry["workspace"]

        # Extra custom commands per bot
        if "custom_commands" in bot_entry:
            merged["custom_commands"].extend(bot_entry["custom_commands"])

        # Extra pattern commands per bot
        if "pattern_commands" in bot_entry:
            merged["pattern_commands"].extend(bot_entry["pattern_commands"])

        # Build Multi-Bot collective roles and aliases for Zero-@
        zero_at = root_data.get("zero_at", root_data.get("autonomous"))
        if zero_at is not False:
            zero_dict = dict(zero_at) if isinstance(zero_at, dict) else {"enabled": True}

            # All bots in the list
            all_bots = root_data.get("bots", [])
            roles = dict(zero_dict.get("roles", {}))
            aliases = dict(zero_dict.get("aliases", {}))

            for b in all_bots:
                uname = (b.get("username") or b.get("name") or "").lower().lstrip("@")
                if uname:
                    if uname not in roles and "role" in b:
                        roles[uname] = b["role"]
                    if uname not in aliases and "aliases" in b:
                        aliases[uname] = list(b["aliases"])

            zero_dict["roles"] = roles
            zero_dict["aliases"] = aliases
            # First bot is arbiter by default
            if all_bots and not zero_dict.get("arbiter_bot"):
                first_uname = (all_bots[0].get("username") or all_bots[0].get("name") or "").lower().lstrip("@")
                zero_dict["arbiter_bot"] = first_uname

            merged["zero_at"] = zero_dict

        return merged

    def to_dict(self) -> Dict[str, Any]:
        return self.raw
