"""
Core implementation of Autonomous Routing (免@自主感知唤醒).

Decision pipeline (arbiter side only):
    L0 physical noise  - empty / punctuation-only / emoji-only  (0 token)
    L1 alias bypass    - contains a bot alias -> direct wake    (0 token)
    L2 classifier     - active provider engine (jev|gemini) judgment (1 API call)

Tri-state output:
    {"target_bot": <bot|none>, "urgency": "immediate"|"wait_silence"|"drop"}

Fail-closed iron rule: no key / timeout / bad JSON / low confidence -> drop.
"""

import asyncio
import datetime as _dt
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

import httpx
 
logger = logging.getLogger("groupconnect.routing")


def find_default_config_path() -> str:
    """Find the default autonomous configuration file path.

    Standard discovery precedence:
    1. GROUPCONNECT_ROUTING_CONFIG environment variable
    2. ~/.config/groupconnect/groupconnect.yaml
    3. groupconnect.yaml (repository root)
    4. groupconnect.example.yaml (repository root, fallback example)
    """
    env_path = os.environ.get("GROUPCONNECT_ROUTING_CONFIG")
    if env_path and os.path.isfile(env_path):
        return env_path

    candidate_yaml = os.path.expanduser("~/.config/groupconnect/groupconnect.yaml")
    if os.path.isfile(candidate_yaml):
        return candidate_yaml

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    for name in (
        "groupconnect.yaml",
        "groupconnect.yml",
        "groupconnect.example.yaml",
    ):
        p = os.path.join(repo_root, name)
        if os.path.isfile(p):
            return p

    return os.path.join(repo_root, "groupconnect.example.yaml")


DEFAULT_CONFIG_PATH = find_default_config_path()

from groupconnect.routing.defaults import (
    DEFAULT_NOISE_PATTERNS,
    DEFAULT_ALIAS_DROP_PATTERNS,
    DEFAULT_RULE_TEMPLATES,
    DEFAULT_LLM_PROMPT_TEMPLATE,
    DEFAULT_ROUTING_RULES_MD,
    DEFAULT_IMMEDIATE_CRITERIA,
    DEFAULT_WAIT_CRITERIA,
    DEFAULT_DROP_CRITERIA,
    DEFAULT_GROUP_DESCRIPTION,
    DEFAULT_PARALLEL_CRITERIA,
)

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(obj: Any) -> Any:
    if isinstance(obj, str):
        def _repl(m: re.Match) -> str:
            return os.environ.get(m.group(1), m.group(2) if m.group(2) is not None else "")
        return _ENV_VAR_RE.sub(_repl, obj)
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    return obj


class AutonomousConfig:
    """Loads and validates the shared autonomous routing configuration."""

    def __init__(
        self,
        path_or_data: Optional[Union[str, Dict[str, Any]]] = None,
        path: Optional[str] = None,
    ):
        if isinstance(path_or_data, dict):
            self.raw_data: Optional[Dict[str, Any]] = path_or_data
            self.path: Optional[str] = path
            self._last_mtime: float = (
                os.path.getmtime(path) if (path and os.path.isfile(path)) else 0.0
            )
        else:
            self.raw_data = None
            self.path = path_or_data or path or find_default_config_path()
            self._last_mtime = 0.0
        self._load()

    def reload_if_modified(self) -> None:
        try:
            if self.path and os.path.isfile(self.path):
                mtime = os.path.getmtime(self.path)
                if mtime != self._last_mtime:
                    self.raw_data = None
                    self._load()
        except Exception:
            pass

    def _load(self) -> None:
        if self.path and os.path.isfile(self.path):
            cfg_dir = os.path.dirname(os.path.abspath(self.path))
            if os.path.isdir(cfg_dir):
                import glob as _glob
                for env_file in [os.path.join(cfg_dir, ".env")] + sorted(_glob.glob(os.path.join(cfg_dir, "*.env"))):
                    if os.path.isfile(env_file):
                        try:
                            with open(env_file, "r", encoding="utf-8") as ef:
                                for line in ef:
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

        raw: Dict[str, Any] = {}
        if self.raw_data is not None:
            raw = _expand_env(self.raw_data)
        elif self.path and os.path.isfile(self.path):
            try:
                self._last_mtime = os.path.getmtime(self.path)
                with open(self.path, "r", encoding="utf-8") as f:
                    if self.path.endswith((".yaml", ".yml")):
                        import yaml
                        raw = yaml.safe_load(f) or {}
                    else:
                        raw = json.load(f)
                raw = _expand_env(raw)
            except Exception as e:
                logger.warning("Failed to load autonomous config from %s: %s", self.path, e)
                raw = {}
        else:
            self._last_mtime = 0.0

        cfg = raw.get("autonomous", raw.get("zero_at", raw))
        if not isinstance(cfg, dict):
            cfg = {"enabled": bool(cfg)}
        else:
            cfg = dict(cfg)

        if getattr(self, "_bound_platform", ""):
            cfg.setdefault("platform", self._bound_platform)
        self._bound_platform: str = str(cfg.get("platform", "")).lower()

        # Merge multi-bot roles/aliases/arbiter/ipc/security when loading unified YAML directly
        if "bots" in raw and isinstance(raw["bots"], list):
            all_bots = raw["bots"]
            root_platform = str(
                (raw.get("channel") if isinstance(raw.get("channel"), dict) else {}).get(
                    "platform", raw.get("platform", "telegram")
                )
            ).lower()
            if self._bound_platform:
                same_platform_bots = [
                    b for b in all_bots
                    if isinstance(b, dict) and str(
                        b.get(
                            "platform",
                            (b.get("channel") if isinstance(b.get("channel"), dict) else {}).get("platform", root_platform)
                        )
                    ).lower() == self._bound_platform
                ] or all_bots
            else:
                same_platform_bots = all_bots

            roles = dict(cfg.get("roles", {}))
            aliases = dict(cfg.get("aliases", {}))
            for b in same_platform_bots:
                if not isinstance(b, dict):
                    continue
                uname = (b.get("username") or b.get("name") or "").lower().lstrip("@")
                if uname:
                    if uname not in roles and "role" in b:
                        roles[uname] = b["role"]
                    if uname not in aliases and "aliases" in b:
                        aliases[uname] = list(b["aliases"])
            cfg["roles"] = roles
            cfg["aliases"] = aliases
            if same_platform_bots and not cfg.get("arbiter_bot"):
                first = same_platform_bots[0] if isinstance(same_platform_bots[0], dict) else {}
                cfg["arbiter_bot"] = (first.get("username") or first.get("name") or "").lower().lstrip("@")

        if "tuning" in raw and isinstance(raw["tuning"], dict):
            if not cfg.get("ipc_dir") and "ipc_dir" in raw["tuning"]:
                cfg["ipc_dir"] = raw["tuning"]["ipc_dir"]
            if "silence_window_secs" in raw["tuning"] and "silence_secs" not in cfg:
                cfg["silence_secs"] = raw["tuning"]["silence_window_secs"]

        security = raw.get("security", raw.get("allowlist", {}))
        if isinstance(security, dict) and not cfg.get("allowed_chat_ids"):
            chats = security.get("allowed_chat_ids", security.get("groups", []))
            if chats:
                cfg["allowed_chat_ids"] = list(chats)

        self.enabled: bool = bool(cfg.get("enabled", False))
        self.arbiter_bot: str = str(cfg.get("arbiter_bot", "")).lower().lstrip("@")
        self.ipc_dir: str = cfg.get("ipc_dir", "/tmp/groupconnect_ipc")

        windows = cfg.get("windows", {})
        self.immediate_secs: float = float(
            windows.get("immediate_secs", cfg.get("immediate_secs", 1.0))
        )
        self.silence_secs: float = float(
            windows.get("silence_secs", cfg.get("silence_secs", cfg.get("silence_window_secs", 4.0)))
        )

        ctx = cfg.get("context", {})
        self.context_window_size: int = int(
            ctx.get("window_size", cfg.get("context_window_size", 3))
        )

        self.aliases: Dict[str, list] = {
            str(bot).lower().lstrip("@"): list(aliases or [])
            for bot, aliases in cfg.get("aliases", {}).items()
        }
        self.alias_mode: str = str(cfg.get("alias_mode", "bypass"))  # bypass | hint

        # Pre-bypass filters: built-in defaults are ALWAYS active; user config extends them
        raw_alias_drop = cfg.get("alias_drop_regex") or []
        self.alias_drop_regex: list = list(DEFAULT_ALIAS_DROP_PATTERNS)
        for pat in raw_alias_drop:
            if pat and pat not in self.alias_drop_regex:
                self.alias_drop_regex.append(pat)

        raw_noise = cfg.get("noise_regex") or []
        merged_noise = list(DEFAULT_NOISE_PATTERNS)
        for pat in raw_noise:
            if pat and pat not in merged_noise:
                merged_noise.append(pat)
        self.noise_regex: list = [re.compile(p) for p in merged_noise]

        # ---- Classifier provider registry (self-describing) ----
        clf = cfg.get("classifier", {})
        self.confidence_threshold: float = float(
            clf.get("confidence_threshold", cfg.get("confidence_threshold", 0.60))
        )
        self.parallel_threshold: float = float(
            clf.get("parallel_threshold", cfg.get("parallel_threshold", self.confidence_threshold))
        )
        self.daily_budget: int = int(
            clf.get("daily_budget", cfg.get("daily_budget", 800))
        )

        providers = clf.get("providers")
        if not providers:
            clf_engine = str(clf.get("engine", cfg.get("engine", "jev"))).lower()
            if clf_engine == "jev":
                default_model = "jev-latest"
                default_env = "JEV_API_KEY"
            elif clf_engine in ("openai", "llm"):
                default_model = "gpt-4o-mini"
                default_env = "OPENAI_API_KEY"
            elif clf_engine == "anthropic":
                default_model = "claude-3-5-haiku-latest"
                default_env = "ANTHROPIC_API_KEY"
            else:
                default_model = "gemini-2.5-flash-lite"
                default_env = "GEMINI_ROUTER_API_KEY" if "GEMINI_ROUTER_API_KEY" in os.environ else "GEMINI_API_KEY"
            clf_model = clf.get("model", cfg.get("model", default_model)) or default_model
            api_key = clf.get("api_key", cfg.get("api_key", os.environ.get(default_env, "")))
            api_key_env = clf.get("api_key_env", default_env if not clf.get("api_key") and not cfg.get("api_key") else "")
            providers = {
                "default": {
                    "engine": clf_engine,
                    "model": clf_model,
                    "base_url": clf.get("base_url", cfg.get("base_url", "")),
                    "api_key": api_key,
                    "api_key_env": api_key_env,
                    "timeout_ms": clf.get("timeout_ms", 5000),
                }
            }
        default_active = "typesafe" if "typesafe" in providers else next(iter(providers.keys()), "typesafe")
        self.providers: Dict[str, dict] = {
            str(name).lower().lstrip("@"): (p if isinstance(p, dict) else {})
            for name, p in providers.items()
        }
        self.active_provider: str = str(clf.get("active", default_active)).lower()
        pcfg = self.providers.get(self.active_provider)
        if pcfg is None:
            if self.providers:
                logger.warning(
                    "[ROUTING] classifier.active '%s' not found in providers %s; "
                    "classifier fails closed until fixed.",
                    self.active_provider, sorted(self.providers),
                )
            pcfg = {}
        self.engine: str = str(pcfg.get("engine", "jev" if self.active_provider == "typesafe" else "llm")).lower()
        if pcfg:
            if self.engine == "jev":
                default_engine_model = "jev-latest"
            elif self.engine in ("openai", "llm"):
                default_engine_model = "gpt-4o-mini"
            elif self.engine == "anthropic":
                default_engine_model = "claude-3-5-haiku-latest"
            else:
                default_engine_model = "gemini-2.5-flash-lite"
        else:
            default_engine_model = ""
        self.model: str = str(pcfg.get("model") or default_engine_model)
        self.base_url: str = _expand_env(str(pcfg.get("base_url", clf.get("base_url", "")))).strip().rstrip("/")
        raw_api_key = os.environ.get(str(pcfg.get("api_key_env", "")), "") or str(pcfg.get("api_key", ""))
        self.api_key: str = _expand_env(raw_api_key).strip()
        self.timeout_ms: int = int(pcfg.get("timeout_ms", 3000))

        self.roles: Dict[str, str] = {
            str(bot).lower().lstrip("@"): role
            for bot, role in cfg.get("roles", {}).items()
        }

        # Classifier wording (immediate/wait/drop/group/parallel):
        # Built-in DEFAULT_RULE_TEMPLATES overlaid by optional zero_at.rules in YAML
        self.rule_templates: Dict[str, str] = dict(DEFAULT_RULE_TEMPLATES)
        raw_rules = cfg.get("rules")
        self.custom_rules: Dict[str, str] = (
            {str(k): str(v) for k, v in raw_rules.items() if v}
            if isinstance(raw_rules, dict)
            else {}
        )
        if self.custom_rules:
            self.rule_templates.update(self.custom_rules)

        conc = cfg.get("concurrency", {})
        self.max_queue_backlog: int = int(conc.get("max_queue_backlog", 2))
        self.degrade: str = cfg.get("degrade", "alias_only")
        self.throttle_min_interval: float = float(conc.get("throttle_min_interval", 1.5))

        self.allowed_chat_ids: set = set(cfg.get("allowed_chat_ids", []))
        self.allowed_senders: set = set(cfg.get("allowed_senders", []))

    def is_alias_self_referential(self, alias: str, text: str) -> bool:
        """True if this specific alias is used in a self-referential / banter pattern."""
        esc_alias = re.escape(alias)
        for tpl in self.alias_drop_regex:
            try:
                if re.search(tpl.replace("{alias}", esc_alias), text):
                    return True
            except re.error:
                continue
        return False

    def alias_self_reference(self, text: str) -> bool:
        """True if ANY alias in text matches a self-referential drop pattern."""
        for bot, aliases in self.aliases.items():
            for a in aliases:
                if a and a in text and self.is_alias_self_referential(a, text):
                    return True
        return False

    def alias_hits(self, text: str) -> list:
        """Returns list of distinct bot usernames whose non-self-referential aliases
        appear in text, ordered by first occurrence position (earliest mention wins).
        For each bot, the EARLIEST position among ALL its matched aliases is used
        (not just the first alias in the list)."""
        matched = []
        for bot, aliases in self.aliases.items():
            best_pos = None
            for a in aliases:
                if a and a in text and not self.is_alias_self_referential(a, text):
                    pos = text.find(a)
                    if best_pos is None or pos < best_pos:
                        best_pos = pos
            if best_pos is not None:
                matched.append((best_pos, bot))
        matched.sort(key=lambda x: x[0])
        return [bot for _, bot in matched]

    def alias_hit(self, text: str) -> Optional[str]:
        """Returns the first-mentioned bot username if any alias found, or None."""
        hits = self.alias_hits(text)
        return hits[0] if hits else None

    def is_noise(self, text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return True
        if t.startswith("/"):
            return True
        return any(p.match(t) for p in self.noise_regex)


class AutonomousObserver:
    """Symmetric executor running on BOTH processes.

    Arm a countdown window upon a decision targeting us; any OTHER human
    message during the window cancels it; otherwise dispatch (reply-anchored).
    """

    def __init__(
        self,
        my_bot: str,
        cfg: AutonomousConfig,
        dispatch: Callable[[Dict[str, Any]], Awaitable[None]],
    ):
        self.my_bot = my_bot
        self.cfg = cfg
        self.dispatch = dispatch
        # chat_id -> {"task": asyncio.Task, "sender": str}
        self.pending: Dict[Any, Dict[str, Any]] = {}

    def on_human_message(self, chat_id: Any, sender_name: str) -> None:
        """Any OTHER human speaking in the chat preempts the pending reply."""
        p = self.pending.get(chat_id)
        if p is None:
            return
        if sender_name != p.get("sender"):
            self._cancel(chat_id)
            logger.info(f"[ROUTING] Human interjected in chat {chat_id}; autonomous reply cancelled.")

    def on_decision(self, decision: Dict[str, Any]) -> None:
        """Called on both sides: locally by the arbiter, remotely via relay."""
        target = str(decision.get("target_bot", "none")).lower().lstrip("@")
        targets_raw = decision.get("target_bots")
        if targets_raw and isinstance(targets_raw, (list, set, tuple)):
            target_set = {str(t).lower().lstrip("@") for t in targets_raw}
        elif target and target != "none":
            target_set = {target}
        else:
            target_set = set()

        urgency = decision.get("urgency", "drop")
        chat_id = decision.get("chat_id")
        should_act = self.my_bot in target_set
        if not should_act or urgency == "drop" or chat_id is None:
            return
        secs = self.cfg.immediate_secs if urgency == "immediate" else self.cfg.silence_secs
        self._cancel(chat_id)  # always cancel stale pending first: no orphan tasks
        task = asyncio.create_task(self._countdown(decision, secs))
        self.pending[chat_id] = {"task": task, "sender": decision.get("sender", "")}
        logger.info(
            f"[ROUTING] Armed {urgency} window ({secs}s) for chat {chat_id}, "
            f"target {self.my_bot} (targets={sorted(target_set)})."
        )

    def _cancel(self, chat_id: Any) -> None:
        p = self.pending.pop(chat_id, None)
        if p and p.get("task") and not p["task"].done():
            p["task"].cancel()

    async def _countdown(self, decision: Dict[str, Any], secs: float) -> None:
        chat_id = decision.get("chat_id")
        try:
            await asyncio.sleep(secs)
            logger.info(
                f"[ROUTING] Window elapsed in chat {chat_id}; dispatching to {self.my_bot}. "
                f"(source={decision.get('source')}, urgency={decision.get('urgency')})"
            )
            await self.dispatch(decision)
        except asyncio.CancelledError:
            pass
        finally:
            self.pending.pop(chat_id, None)


class AutonomousArbiter:
    """The SINGLE decision point. Only loaded on the arbiter process."""

    def __init__(self, cfg: AutonomousConfig, context_summary_fn=None):
        self.cfg = cfg
        self.context_summary_fn = context_summary_fn
        self._budget_day: str = ""
        self._budget_used: int = 0
        self._prompt_cache: Optional[str] = None
        self._prompt_mtime: float = 0.0
        self._call_lock: asyncio.Lock = asyncio.Lock()  # serialize + throttle
        self._last_call_ts: float = 0.0
        self._min_interval: float = float(cfg.throttle_min_interval)

    # ---------- budget ----------
    def _budget_exceeded(self) -> bool:
        today = _dt.date.today().isoformat()
        if today != self._budget_day:
            self._budget_day = today
            self._budget_used = 0
        return self._budget_used >= self.cfg.daily_budget

    # ---------- prompt ----------
    def _render_prompt(self, text: str, sender: str, context: str, alias_hint: str) -> str:
        roles = "\n".join(f"  {bot}: {role}" for bot, role in self.cfg.roles.items())
        return (
            DEFAULT_LLM_PROMPT_TEMPLATE.replace("{ROLES}", roles)
               .replace("{RULES_SECTION}", self._load_rules_instructions())
               .replace("{CONTEXT}", context or "(no prior messages)")
               .replace("{SENDER}", sender)
               .replace("{TEXT}", text)
               .replace("{ALIAS_HINT}", alias_hint)
        )

    def _load_rules_instructions(self) -> str:
        """Renders decision instructions by substituting active rule_templates (with zero_at.rules already replaced in-place)."""
        t = self.cfg.rule_templates
        return (
            DEFAULT_ROUTING_RULES_MD.strip()
            .replace("{group}", t.get("group", DEFAULT_GROUP_DESCRIPTION))
            .replace("{immediate}", t.get("immediate", DEFAULT_IMMEDIATE_CRITERIA))
            .replace("{wait}", t.get("wait", DEFAULT_WAIT_CRITERIA))
            .replace("{drop}", t.get("drop", DEFAULT_DROP_CRITERIA))
            .replace("{parallel}", t.get("parallel", DEFAULT_PARALLEL_CRITERIA))
        )


    # ---------- pipeline ----------
    def evaluate_sync(self, text: str, sender: str, context: str = "") -> Optional[Dict[str, Any]]:
        """L0 (physical noise) + L1 (alias bypass). Returns a decision or None.
        Synchronous & 0-token. A None result means "proceed to L3 classifier".
        """
        self.cfg.reload_if_modified()
        if self.cfg.is_noise(text):
            return {"target_bot": "none", "target_bots": [], "urgency": "drop",
                    "confidence": 1.0, "source": "noise"}
        if self.cfg.alias_mode == "bypass":
            hits = self.cfg.alias_hits(text)
            if hits:
                if len(hits) == 1:
                    # Single alias hit: bypass directly, zero-token
                    return {"target_bot": hits[0], "target_bots": [hits[0]], "urgency": "immediate",
                            "confidence": 1.0, "source": "alias_bypass"}
                # Multiple aliases: defer to classifier — it understands
                # dispatch vs. parallel semantics (e.g. "A, let B handle X"
                # vs. "A and B both look at this").
                return None
            elif self.cfg.alias_self_reference(text):
                return {"target_bot": "none", "target_bots": [], "urgency": "drop",
                        "confidence": 1.0, "source": "alias_self_reference"}
        return None  # -> L3

    async def classify(self, text: str, sender: str, context: str, alias_hint: str = "") -> Dict[str, Any]:
        """L3: single classifier tri-state call. Fail-closed -> drop.
        Dispatches on the ACTIVE provider's engine (jev | gemini)."""
        self.cfg.reload_if_modified()
        drop = {"target_bot": "none", "target_bots": [], "urgency": "drop", "confidence": 0.0, "source": "classifier"}
        if not self.cfg.api_key:
            logger.warning("[ROUTING] No API key configured; fail-closed drop.")
            return drop
        if self._budget_exceeded():
            if self.cfg.degrade == "alias_only":
                logger.warning("[ROUTING] Daily budget exceeded; fail-closed drop (alias bypass still active).")
                return drop
        if not alias_hint:
            hits = self.cfg.alias_hits(text)
            if hits:
                alias_map = {
                    f"@{b}": [a for a in self.cfg.aliases.get(b, []) if a and a in text]
                    for b in hits
                }
                alias_hint = f"(Detected bot aliases in message: {alias_map})"
        engine = self.cfg.engine
        if engine == "jev":
            return await self._classify_jev(text, sender, context, alias_hint, drop)
        if engine in ("llm", "openai", "gemini", "anthropic"):
            return await self._classify_llm(text, sender, context, alias_hint, drop)
        logger.warning(f"[ROUTING] Unknown classifier engine '{engine}'; fail-closed drop.")
        return drop

    def _jev_parallel_templates(self) -> Dict[str, str]:
        t = self.cfg.rule_templates
        parallel = t.get("parallel", DEFAULT_PARALLEL_CRITERIA)
        templates = {}
        for bot, role in self.cfg.roles.items():
            templates[bot] = parallel.replace("{bot}", bot).replace("{role}", role)
        return templates

    def _jev_criteria(self) -> Tuple[dict, dict, str]:
        """Builds Jev choice criteria + map + group description from the
        rules-file templates (single source of truth); falls back to module
        defaults when a template is missing. Code only assembles, never words."""
        t = self.cfg.rule_templates
        imm = t.get("immediate", DEFAULT_IMMEDIATE_CRITERIA)
        wait = t.get("wait", DEFAULT_WAIT_CRITERIA)
        drop = t.get("drop", DEFAULT_DROP_CRITERIA)
        group = t.get("group", DEFAULT_GROUP_DESCRIPTION)
        criteria, jev_map = {}, {}
        for bot, role in self.cfg.roles.items():
            criteria[f"{bot}_immediate"] = imm.replace("{bot}", bot).replace("{role}", role)
            criteria[f"{bot}_wait"] = wait.replace("{bot}", bot).replace("{role}", role)
            jev_map[f"{bot}_immediate"] = (bot, "immediate")
            jev_map[f"{bot}_wait"] = (bot, "wait_silence")
        criteria["none_drop"] = drop
        jev_map["none_drop"] = ("none", "drop")
        return criteria, jev_map, group

    async def _classify_jev(self, text: str, sender: str, context: str, alias_hint: str, drop: dict) -> Dict[str, Any]:
        """Jev (TypeSafe) classifier: structured Choice + per-bot Noul questions."""
        criteria, jev_map, group_description = self._jev_criteria()
        parallel_templates = self._jev_parallel_templates()

        state = {
            "group": group_description,
            "bot_roles": dict(self.cfg.roles),
            "recent_conversation": context or "(no prior messages)",
            "current_message": {"sender": sender, "text": text},
            "alias_hint": alias_hint or "(no alias detected)",
        }
        questions = {
            "routing": {
                "type": "choice",
                "instructions": self._load_rules_instructions(),
                "criteria": criteria,
            }
        }
        # Multi-bot perception: add per-bot Noul questions for parallel collaboration detection
        if len(self.cfg.roles) > 1:
            for bot in self.cfg.roles:
                p_inst = parallel_templates.get(bot)
                if p_inst:
                    questions[f"parallel_{bot}"] = {
                        "type": "noul",
                        "instructions": p_inst,
                    }

        api_root = getattr(self.cfg, "base_url", "") or "https://api.typesafe.ai/v1"
        url = api_root if api_root.endswith("/systemone") else f"{api_root}/systemone"
        timeout = self.cfg.timeout_ms / 1000.0
        payload = {"state": state, "model": self.cfg.model, "questions": questions}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        retryable = {429, 500, 502, 503, 504}
        backoffs = [1.0, 2.0, 4.0]
        async with self._call_lock:
            wait = self._min_interval - (asyncio.get_running_loop().time() - self._last_call_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = asyncio.get_running_loop().time()
            res = None
            for attempt in range(len(backoffs) + 1):
                try:
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        res = await client.post(url, json=payload, headers=headers)
                    if res.status_code not in retryable:
                        break
                except Exception as e:
                    res = None
                    if attempt < len(backoffs):
                        logger.warning(f"[ROUTING] Jev attempt {attempt+1} failed: {e}; retry in {backoffs[attempt]}s.")
                        await asyncio.sleep(backoffs[attempt])
                        continue
                    logger.warning(f"[ROUTING] Jev failed after {attempt+1} attempts: {e}; fail-closed drop.")
                    return drop
                if res.status_code in retryable and attempt < len(backoffs):
                    logger.warning(f"[ROUTING] Jev HTTP {res.status_code} (attempt {attempt+1}); retry in {backoffs[attempt]}s.")
                    await asyncio.sleep(backoffs[attempt])
            if res is None or res.status_code != 200:
                logger.warning(f"[ROUTING] Jev exhausted retries; fail-closed drop.")
                return drop
            answers = res.json().get("answers", {})
            routing_ans = answers.get("routing", {})
            choice = routing_ans.get("choice", "none_drop")
            confidence = float(routing_ans.get("confidence", 0.0) or 0.0)
            target_bot, urgency = jev_map.get(choice, ("none", "drop"))
            probs = routing_ans.get("probabilities", {})

            # Marginal probability aggregation across immediate & wait per bot:
            # Prevents probability split between immediate/wait from causing false drops.
            if probs:
                bot_probs = {b: 0.0 for b in self.cfg.roles.keys()}
                none_prob = float(probs.get("none_drop", 0.0) or 0.0)
                for k, p in probs.items():
                    for b in bot_probs:
                        if k.startswith(b):
                            bot_probs[b] += float(p or 0.0)

                best_bot, best_bot_prob = max(bot_probs.items(), key=lambda x: x[1])
                if best_bot_prob >= self.cfg.confidence_threshold and best_bot_prob > none_prob:
                    target_bot = best_bot
                    confidence = best_bot_prob
                    p_imm = float(probs.get(f"{best_bot}_immediate", 0.0) or 0.0)
                    p_wait = float(probs.get(f"{best_bot}_wait", 0.0) or 0.0)
                    urgency = "immediate" if p_imm >= p_wait else "wait_silence"
                elif none_prob >= self.cfg.confidence_threshold or best_bot_prob < self.cfg.confidence_threshold:
                    target_bot = "none"
                    urgency = "drop"
                    confidence = max(none_prob, 1.0 - best_bot_prob)

            # Step 1: Extract Noul parallel results for ALL bots BEFORE drop check.
            # This allows Noul to rescue a Choice drop when the sender explicitly
            # wants multiple bots to respond together (e.g. "you two both look at this").
            noul_results: list = []  # (bot, noul_prob) pairs, threshold-filtered
            for b in self.cfg.roles:
                noul_ans = answers.get(f"parallel_{b}", {})
                noul_prob = float(noul_ans.get("noul", 0.0) or 0.0)
                if noul_prob >= self.cfg.parallel_threshold:
                    noul_results.append((b, noul_prob))
            noul_bots = [b for b, _ in noul_results]

            # Step 2: Determine primary bot and urgency via combined Choice + Noul
            choice_ok = (
                urgency != "drop"
                and confidence >= self.cfg.confidence_threshold
                and target_bot != "none"
            )

            if choice_ok:
                # Choice succeeded: use Choice's primary, Noul adds parallel co-respondents
                target_bots = [target_bot]
                for b in noul_bots:
                    if b != target_bot:
                        target_bots.append(b)
            elif noul_bots:
                # Choice dropped but Noul detected explicit parallel intent -> rescue
                target_bots = list(noul_bots)
                noul_results.sort(key=lambda x: x[1], reverse=True)
                target_bot = noul_results[0][0]
                urgency = "immediate"
                confidence = noul_results[0][1]
            else:
                # Neither Choice nor Noul found anything -> fail-closed drop
                target_bot = "none"
                target_bots = []
                urgency = "drop"

            decision = {
                "target_bot": target_bot,
                "target_bots": target_bots,
                "urgency": urgency,
                "confidence": round(confidence, 2),
                "source": "classifier",
            }
            self._budget_used += 1
            return decision

    @staticmethod
    def _extract_json_dict(raw_text: str) -> Dict[str, Any]:
        """Extracts JSON object from LLM text, stripping optional markdown fences."""
        s = (raw_text or "").strip()
        if s.startswith("```"):
            s = re.sub(r"^```(?:json)?\s*", "", s)
            s = re.sub(r"\s*```$", "", s).strip()
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end >= start:
            s = s[start : end + 1]
        return json.loads(s)

    async def _classify_llm(self, text: str, sender: str, context: str, alias_hint: str, drop: dict) -> Dict[str, Any]:
        """General LLM JSON classifier: renders prompt -> calls OpenAI-compatible / Gemini / Anthropic API -> parses JSON."""
        prompt = self._render_prompt(text, sender, context, alias_hint)
        if not prompt:
            return drop

        engine = self.cfg.engine
        base_url = getattr(self.cfg, "base_url", "")
        use_gemini_native = (engine == "gemini")
        use_anthropic = (engine == "anthropic")

        if use_gemini_native:
            api_root = base_url or "https://generativelanguage.googleapis.com/v1beta"
            url = f"{api_root}/models/{self.cfg.model}:generateContent?key={self.cfg.api_key}"
            headers: Dict[str, str] = {}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                },
            }
        elif use_anthropic:
            api_root = base_url or "https://api.anthropic.com/v1"
            url = api_root if api_root.endswith("/messages") else f"{api_root}/messages"
            headers = {
                "x-api-key": self.cfg.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": self.cfg.model,
                "max_tokens": 256,
                "temperature": 0.0,
                "messages": [{"role": "user", "content": prompt}],
            }
        else:
            # Standard OpenAI-compatible Chat Completions endpoint (OpenAI, DeepSeek, Qwen, SiliconFlow, OpenRouter, etc.)
            api_root = base_url or "https://api.openai.com/v1"
            url = api_root if api_root.endswith("/chat/completions") else f"{api_root}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.cfg.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.cfg.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
            }

        timeout = self.cfg.timeout_ms / 1000.0
        async with self._call_lock:  # throttle: no classifier bursts (anti-429)
            wait = self._min_interval - (asyncio.get_running_loop().time() - self._last_call_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = asyncio.get_running_loop().time()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 429:  # rate limit: exponential backoff retries
                    for attempt, backoff in enumerate((2.0, 4.0), start=1):
                        logger.warning(f"[ROUTING] Classifier 429; backoff {backoff}s (retry {attempt}/2).")
                        await asyncio.sleep(backoff)
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            res = await client.post(url, json=payload, headers=headers)
                        if res.status_code != 429:
                            break
                if res.status_code != 200:
                    logger.warning(f"[ROUTING] Classifier HTTP {res.status_code}; fail-closed drop.")
                    return drop
                resp_json = res.json()
                if use_gemini_native:
                    raw_text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                elif use_anthropic:
                    raw_text = resp_json["content"][0]["text"]
                else:
                    raw_text = resp_json["choices"][0]["message"]["content"]
                data = self._extract_json_dict(raw_text)
            except Exception as e:
                logger.warning(f"[ROUTING] Classifier failed: {e}; fail-closed drop.")
                return drop

            raw_target = data.get("target_bots") or data.get("target_bot", "none")
            if isinstance(raw_target, list):
                cleaned = [str(t).lower().lstrip("@") for t in raw_target]
                target_bots = [t for t in cleaned if t in self.cfg.roles]
            elif isinstance(raw_target, str):
                t_str = str(raw_target).lower().lstrip("@")
                target_bots = [t_str] if t_str in self.cfg.roles else []
            else:
                target_bots = []

            primary_target = target_bots[0] if target_bots else "none"

            decision = {
                "target_bot": primary_target,
                "target_bots": target_bots,
                "urgency": str(data.get("urgency", "drop")).lower(),
                "confidence": float(data.get("confidence", 0.0) or 0.0),
                "source": "classifier",
            }
            if decision["urgency"] not in ("immediate", "wait_silence", "drop") or not target_bots:
                decision["urgency"] = "drop"
            if decision["urgency"] != "drop" and decision["confidence"] < self.cfg.confidence_threshold:
                logger.info(f"[ROUTING] Confidence {decision['confidence']} below threshold; drop.")
                decision["urgency"] = "drop"
            if decision["urgency"] == "drop":
                decision.update(target_bot="none", target_bots=[])
            self._budget_used += 1
            return decision


class AutonomousController:
    """Facade mounted on GroupConnectEngine. Decides the local role:

    - arbiter process  -> Arbiter + Observer (decides AND may execute)
    - follower process -> Observer only       (never decides)
    """

    def __init__(
        self,
        bot_username: str,
        cfg: AutonomousConfig,
        relay=None,
        dispatch=None,
        context_summary_fn=None,
    ):
        self.my_bot = str(bot_username).lower().lstrip("@")
        self.cfg = cfg
        self.relay = relay
        self.observer = AutonomousObserver(self.my_bot, cfg, dispatch) if dispatch else None
        self.is_arbiter = (self.my_bot == cfg.arbiter_bot)
        self._context_summary_fn = context_summary_fn
        self.arbiter = AutonomousArbiter(cfg, context_summary_fn) if self.is_arbiter else None
        if cfg.enabled:
            logger.info(
                f"[ROUTING] Autonomous routing enabled. Role: "
                f"{'ARBITER' if self.is_arbiter else 'FOLLOWER'} (arbiter=@{cfg.arbiter_bot})"
            )

    # ---------- engine hooks ----------
    def on_human_message(self, msg) -> None:
        if getattr(msg, "is_bot_relay", False) or bool(getattr(msg, "from_user", {}).get("is_bot", False)):
            return
        if self.observer is not None:
            self.observer.on_human_message(msg.chat_id, msg.sender_name)

    def on_relay_event(self, event: Dict[str, Any]) -> None:
        if event.get("event") != "autonomous_decision":
            return
        if self.observer is not None:
            self.observer.on_decision(event)

    def chat_allowed(self, chat_id: Any) -> bool:
        if self.cfg.allowed_chat_ids:
            return chat_id in self.cfg.allowed_chat_ids
        return True

    def sender_allowed(self, sender_name: str) -> bool:
        if self.cfg.allowed_senders:
            return any(s in sender_name for s in self.cfg.allowed_senders)
        return True

    async def evaluate_and_publish(self, msg) -> None:
        """Arbiter-only entry: run the pipeline and broadcast the decision once."""
        if not self.is_arbiter or self.arbiter is None:
            return
        self.cfg.reload_if_modified()
        if getattr(msg, "is_bot_relay", False) or bool(getattr(msg, "from_user", {}).get("is_bot", False)):
            return
        if getattr(msg, "attachments", None):
            return  # v1: autonomous routing for plain text only
        if not self.chat_allowed(msg.chat_id) or not self.sender_allowed(msg.sender_name):
            return
        context = ""
        if self._context_summary_fn:
            try:
                context = self._context_summary_fn(msg.chat_id, msg.msg_id, self.cfg.context_window_size)
            except Exception as e:
                logger.warning(f"[ROUTING] Context build failed: {e}")

        decision = self.arbiter.evaluate_sync(msg.text or "", msg.sender_name, context)
        if decision is None:
            alias_hint = ""
            if self.cfg.alias_mode == "hint":
                hit = self.cfg.alias_hit(msg.text or "")
                if hit:
                    alias_hint = f"(The message mentions an alias of @{hit}.)"
            decision = await self.arbiter.classify(
                msg.text or "", msg.sender_name, context, alias_hint
            )
        if decision.get("urgency", "drop") == "drop" and decision.get("source") != "classifier":
            return  # physical noise: silently skip, no broadcast
        if decision.get("target_bot", "none") == "none":
            return  # semantic drop: silently skip, no broadcast

        payload = {
            "event": "autonomous_decision",
            "chat_id": msg.chat_id,
            "chat_type": msg.chat_type,
            "msg_id": msg.msg_id,
            "sender": msg.sender_name,
            "text": msg.text or "",
            "decide_at": _dt.datetime.now().isoformat(timespec="seconds"),
            **decision,
        }
        # Publish once: IPC broadcast to peers + local symmetric execution.
        if self.relay is not None:
            try:
                await self.relay.broadcast_event(payload)
            except Exception as e:
                logger.warning(f"[ROUTING] Broadcast failed: {e}")
        if self.observer is not None:
            self.observer.on_decision(payload)
