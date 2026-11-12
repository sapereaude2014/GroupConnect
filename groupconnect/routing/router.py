"""
Core implementation of Autonomous Routing (免@自主感知唤醒).

Decision pipeline (arbiter side only):
    L0 physical noise  - empty / punctuation-only / emoji-only  (0 token)
    L1 alias bypass    - contains a bot alias -> direct wake    (0 token)
    L2 classifier     - active provider engine (jev|decisions) judgment (1 API call)

Tri-state output:
    {"target_bot": <bot|none>, "urgency": "immediate"|"wait_silence"|"drop"}

Fail-closed iron rule: no key / timeout / bad JSON / low confidence -> drop.
"""

import asyncio
import datetime as _dt
import inspect
import json
import logging
import math
import os
import re
import time
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

import httpx
 
logger = logging.getLogger("groupconnect.routing")


def find_default_config_path() -> str:
    """Find the default autonomous configuration file path.

    Standard discovery precedence:
    1. GROUPCONNECT_ROUTING_CONFIG environment variable
    2. ~/.config/groupconnect/groupconnect.yaml
    3. groupconnect.yaml (repository root)
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
    ):
        p = os.path.join(repo_root, name)
        if os.path.isfile(p):
            return p

    return ""


from groupconnect.routing.defaults import (
    DEFAULT_NOISE_PATTERNS,
    DEFAULT_ALIAS_DROP_PATTERNS,
    DEFAULT_RULE_TEMPLATES,
    DEFAULT_JEV_CHOICE_INSTRUCTIONS,
    DEFAULT_IMMEDIATE_CRITERIA,
    DEFAULT_WAIT_CRITERIA,
    DEFAULT_DROP_CRITERIA,
    DEFAULT_GROUP_DESCRIPTION,
    DEFAULT_ASSIGNMENT_CRITERIA,
    DECISIONS_BASE_URL,
    DECISIONS_DEFAULT_MODEL,
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
                uname = (b.get("username") or b.get("id") or b.get("name") or "").lower().lstrip("@")
                role_val = b.get("role") or b.get("role_summary")
                if uname:
                    if uname not in roles and role_val:
                        roles[uname] = role_val
                    if uname not in aliases and "aliases" in b:
                        aliases[uname] = list(b["aliases"])
            cfg["roles"] = roles
            cfg["aliases"] = aliases
            if same_platform_bots and not cfg.get("arbiter_bot"):
                first = same_platform_bots[0] if isinstance(same_platform_bots[0], dict) else {}
                cfg["arbiter_bot"] = (first.get("username") or first.get("id") or first.get("name") or "").lower().lstrip("@")

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
            ctx.get("window_size", cfg.get("context_window_size", 5))
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
        _raw_ct = float(
            clf.get("confidence_threshold", cfg.get("confidence_threshold", 0.60))
        )
        if not (0.0 < _raw_ct <= 1.0):
            logger.warning(
                "[ROUTING] confidence_threshold %s out of (0, 1]; falling back to 0.60.", _raw_ct,
            )
            _raw_ct = 0.60
        self.confidence_threshold: float = _raw_ct
        self.daily_budget: int = int(
            clf.get("daily_budget", cfg.get("daily_budget", 800))
        )

        providers = clf.get("providers")
        if not providers:
            clf_engine = str(clf.get("engine", cfg.get("engine", "jev"))).lower()
            if clf_engine == "jev":
                default_model = "jev-latest"
                default_env = "JEV_API_KEY"
            elif clf_engine == "decisions":
                default_model = DECISIONS_DEFAULT_MODEL
                default_env = "GEMINI_ROUTER_API_KEY"
            else:
                logger.warning(
                    "[ROUTING] Unknown classifier engine '%s' "
                    "(expected jev|decisions); "
                    "classifier fails closed until fixed.", clf_engine,
                )
                default_model = ""
                default_env = ""
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
        self.engine: str = str(pcfg.get("engine", "jev")).lower()
        if pcfg:
            if self.engine == "jev":
                default_engine_model = "jev-latest"
            elif self.engine == "decisions":
                default_engine_model = DECISIONS_DEFAULT_MODEL
            else:
                logger.warning(
                    "[ROUTING] Unknown classifier engine '%s'; classifier fails closed until fixed.",
                    self.engine,
                )
                default_engine_model = ""
        else:
            default_engine_model = ""
        self.model: str = str(pcfg.get("model") or default_engine_model)
        self.base_url: str = _expand_env(str(pcfg.get("base_url", clf.get("base_url", "")))).strip().rstrip("/")
        if self.engine == "decisions" and not self.base_url:
            self.base_url = DECISIONS_BASE_URL
        raw_api_key = os.environ.get(str(pcfg.get("api_key_env") or ""), "") or str(pcfg.get("api_key") or "")
        self.api_key: str = _expand_env(raw_api_key).strip()
        self.timeout_ms: int = int(pcfg.get("timeout_ms", 3000))

        self.roles: Dict[str, str] = {
            str(bot).lower().lstrip("@"): role
            for bot, role in cfg.get("roles", {}).items()
        }

        # Classifier wording (immediate/wait/drop/group/assignment):
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
        if decision.get("is_resume"):
            # Resume re-dispatch is a historical replay: the live grace window
            # already elapsed in real time, and consecutive batch members must
            # not cancel each other (pending holds ONE window per chat — arming
            # the next would silently eat the previous candidate). Dispatch at
            # decision time instead of arming a cancellable countdown.
            logger.info(
                f"[ROUTING] Resume decision in chat {chat_id}; dispatching {self.my_bot} "
                f"without grace window (urgency={urgency})."
            )
            asyncio.create_task(self.dispatch(decision))
            return
        secs = self.cfg.immediate_secs if urgency == "immediate" else self.cfg.silence_secs
        self._cancel(chat_id)  # always cancel stale pending first: no orphan tasks
        task = asyncio.create_task(self._countdown(decision, secs))
        self.pending[chat_id] = {"task": task, "sender": decision.get("sender", ""), "decision": decision}
        logger.info(
            f"[ROUTING] Armed {urgency} window ({secs}s) for chat {chat_id}, "
            f"target {self.my_bot} (targets={sorted(target_set)})."
        )

    def _cancel(self, chat_id: Any) -> None:
        p = self.pending.pop(chat_id, None)
        if p and p.get("task") and not p["task"].done():
            p["task"].cancel()

    def flush_pending(self, chat_id: Any) -> None:
        """Bot finished replying; immediately dispatch any pending wait_silence
        instead of waiting for the countdown to elapse.

        Called from the engine after a bot reply lands. If a wait_silence
        countdown is still running for this chat, cancel it and dispatch
        right away — the accumulated messages are visible in the sliding
        window and the bot is now free to process them."""
        p = self.pending.pop(chat_id, None)
        if p and p.get("task") and not p["task"].done():
            p["task"].cancel()
            decision = p.get("decision")
            if decision:
                logger.info(
                    f"[ROUTING] Flushed pending wait_silence for chat {chat_id} "
                    f"after bot reply landed (skipping remaining countdown)."
                )
                asyncio.create_task(self.dispatch(decision))

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

    # ---------- decision questionnaire ----------
    def _load_choice_instructions(self) -> str:
        """Renders Jev Choice timing instructions.

        Only {group} is injected here — the immediate/wait/drop criteria texts
        live exclusively in the Choice `criteria` object, avoiding duplicate
        tokens in the same question."""
        t = self.cfg.rule_templates
        return (
            DEFAULT_JEV_CHOICE_INSTRUCTIONS.strip()
            .replace("{group}", t.get("group", DEFAULT_GROUP_DESCRIPTION))
        )

    # ---------- pipeline ----------
    def evaluate_sync(self, text: str, sender: str, context: str = "") -> Optional[Dict[str, Any]]:
        """L0 (physical noise) + L1 (alias bypass). Returns a decision or None.
        Synchronous & 0-token. A None result means "proceed to L2 classifier".
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
        return None  # -> L2

    async def classify(self, text: str, sender: str, context: str, alias_hint: str = "") -> Dict[str, Any]:
        """L2: single classifier tri-state call. Fail-closed -> drop.
        Dispatches on the ACTIVE provider's engine (jev | decisions)."""
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
        if engine == "decisions":
            return await self._classify_decisions(text, sender, context, alias_hint, drop)
        logger.warning(f"[ROUTING] Unknown classifier engine '{engine}'; fail-closed drop.")
        return drop

    def _assignment_templates(self) -> Dict[str, str]:
        t = self.cfg.rule_templates
        assignment = t.get("assignment", DEFAULT_ASSIGNMENT_CRITERIA)
        templates = {}
        for bot, role in self.cfg.roles.items():
            aliases = ", ".join(self.cfg.aliases.get(bot, []))
            templates[bot] = (
                assignment.replace("{bot}", bot)
                .replace("{role}", role)
                .replace("{aliases}", aliases or bot)
            )
        return templates

    def _decision_criteria(self) -> Tuple[dict, dict, str]:
        """Builds the decision Choice criteria (3-option: immediate/wait/drop),
        the option->urgency map, and the group description.

        Engine-agnostic — shared by every decision-model classifier
        (jev | decisions). Choice is orthogonal to bot identity: it only
        judges timing/social context; bot assignment is fully delegated
        to the per-bot Noul questions."""
        t = self.cfg.rule_templates
        group = t.get("group", DEFAULT_GROUP_DESCRIPTION)
        criteria = {
            "immediate": t.get("immediate", DEFAULT_IMMEDIATE_CRITERIA),
            "wait": t.get("wait", DEFAULT_WAIT_CRITERIA),
            "drop": t.get("drop", DEFAULT_DROP_CRITERIA),
        }
        decision_map = {
            "immediate": ("none", "immediate"),
            "wait": ("none", "wait_silence"),
            "drop": ("none", "drop"),
        }
        return criteria, decision_map, group

    def _decision_questions(self) -> Tuple[dict, dict, str]:
        """Builds the engine-agnostic decision questionnaire:
        1 orthogonal Choice question (timing) + 1 Noul question per bot
        (assignment). Every decision-model engine speaks this same wire
        contract, so adding a provider never touches question semantics
        or arbitration."""
        criteria, decision_map, group = self._decision_criteria()
        assignment_templates = self._assignment_templates()

        questions = {
            "routing": {
                "type": "choice",
                "instructions": self._load_choice_instructions(),
                "criteria": criteria,
            }
        }
        # Per-bot Noul: 'does this message need {bot} to handle it?'
        for bot in self.cfg.roles:
            p_inst = assignment_templates.get(bot)
            if p_inst:
                questions[f"assignment_{bot}"] = {
                    "type": "noul",
                    "instructions": p_inst,
                }
        return questions, decision_map, group

    def _decision_state(
        self, text: str, sender: str, context: str, alias_hint: str, group: str
    ) -> dict:
        """Builds the shared decision context evaluated by all questions."""
        return {
            "group": group,
            "bot_roles": dict(self.cfg.roles),
            "recent_conversation": context or "(no prior messages)",
            "current_message": {"sender": sender, "text": text},
            "alias_hint": alias_hint or "(no alias detected)",
        }

    def _build_jev_payload(
        self, text: str, sender: str, context: str, alias_hint: str
    ) -> Tuple[str, dict, dict, float, dict]:
        """TypeSafe Jev systemone transport payload: structured state +
        the engine-agnostic questionnaire."""
        questions, decision_map, group = self._decision_questions()
        state = self._decision_state(text, sender, context, alias_hint, group)

        api_root = getattr(self.cfg, "base_url", "") or "https://api.typesafe.ai/v1"
        url = api_root if api_root.endswith("/systemone") else f"{api_root}/systemone"
        timeout = self.cfg.timeout_ms / 1000.0
        payload = {"state": state, "model": self.cfg.model, "questions": questions}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        return url, payload, headers, timeout, decision_map

    def _build_decisions_payload(
        self, text: str, sender: str, context: str, alias_hint: str
    ) -> Tuple[str, dict, dict, float, dict]:
        """Google Gemini Decisions API transport payload: the SAME
        questionnaire with the shared state serialized as the multimodal
        `input` string."""
        questions, decision_map, group = self._decision_questions()
        state = self._decision_state(text, sender, context, alias_hint, group)

        api_root = getattr(self.cfg, "base_url", "") or DECISIONS_BASE_URL
        url = f"{api_root.rstrip('/')}/decisions"
        timeout = self.cfg.timeout_ms / 1000.0
        payload = {
            "model": self.cfg.model or DECISIONS_DEFAULT_MODEL,
            "input": json.dumps(state, ensure_ascii=False),
            "questions": questions,
        }
        headers = {"x-goog-api-key": self.cfg.api_key}
        return url, payload, headers, timeout, decision_map

    async def _post_decision_api(
        self, url: str, payload: dict, headers: dict, timeout: float, tag: str
    ) -> Optional[dict]:
        """Shared transport for all decision-model engines: throttled POST
        with bounded retry on 429/5xx (1/2/4s backoff). Returns the parsed
        JSON body, or None on exhaustion — callers fail closed -> drop."""
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
                        logger.warning(f"[ROUTING] {tag} attempt {attempt+1} failed: {e}; retry in {backoffs[attempt]}s.")
                        await asyncio.sleep(backoffs[attempt])
                        continue
                    logger.warning(f"[ROUTING] {tag} failed after {attempt+1} attempts: {e}; fail-closed drop.")
                    return None
                if res.status_code in retryable and attempt < len(backoffs):
                    logger.warning(f"[ROUTING] {tag} HTTP {res.status_code} (attempt {attempt+1}); retry in {backoffs[attempt]}s.")
                    await asyncio.sleep(backoffs[attempt])
            if res is None or res.status_code != 200:
                logger.warning(f"[ROUTING] {tag} exhausted retries; fail-closed drop.")
                return None
            self._budget_used += 1
            try:
                return res.json()
            except Exception as e:
                logger.warning(f"[ROUTING] {tag} response parsing failed: {e}; fail-closed drop.")
                return None

    def _arbitrate_decision(self, answers: dict, decision_map: dict, drop: dict) -> Dict[str, Any]:
        try:
            # --- Choice: timing/social context (orthogonal to bot identity) ---
            routing_ans = answers.get("routing") or {}
            choice_key = routing_ans.get("choice", "drop")
            confidence = float(routing_ans.get("confidence", 0.0) or 0.0)
            _, choice_urgency = decision_map.get(choice_key, ("none", "drop"))

            # --- Noul: per-bot assignment (domain experts) ---
            noul_results: list = []  # (bot, prob) pairs
            for b in self.cfg.roles:
                noul_ans = answers.get(f"assignment_{b}") or {}
                noul_prob = float(noul_ans.get("noul", 0.0) or 0.0)
                noul_results.append((b, noul_prob))

            # --- Dynamic threshold (one knob, derived) ---
            strict = self.cfg.confidence_threshold
            relaxed = self.cfg.confidence_threshold * 2 / 3
            if not isinstance(confidence, (int, float)) or math.isnan(confidence) or confidence < 0.0:
                conf_c = 0.0
            else:
                conf_c = min(float(confidence), 1.0)

            if choice_urgency == "drop":
                noul_threshold = relaxed + (strict - relaxed) * conf_c
            else:
                noul_threshold = relaxed

            # Sanitize noul probabilities against NaN
            clean_noul = []
            for b, p in noul_results:
                if not isinstance(p, (int, float)) or math.isnan(p) or p < 0.0:
                    clean_p = 0.0
                else:
                    clean_p = min(float(p), 1.0)
                clean_noul.append((b, clean_p))
            noul_results = clean_noul

            # Sort descending by score first so candidate_bots preserves score order
            noul_results.sort(key=lambda x: x[1], reverse=True)
            candidate_bots = [b for b, p in noul_results if p >= noul_threshold]

            # Full decision-input audit line: makes every arbitration branch
            # (silence / rescue / normal / fallback) reconstructible from logs.
            logger.info(
                f"[ROUTING] Choice={choice_key} (conf={conf_c:.2f}); "
                f"Noul={{{', '.join(f'{b}:{p:.2f}' for b, p in noul_results)}}}; "
                f"line={noul_threshold:.2f}."
            )

            # --- Final decision (layered arbitration) ---
            if not candidate_bots:
                if choice_urgency == "drop" or not noul_results:
                    # Both gates say silence, or no bots configured → true silence
                    logger.info(
                        f"[ROUTING] No bot claimed message "
                        f"(noul_threshold={noul_threshold:.2f}, "
                        f"scores={{{', '.join(f'{b}:{p:.2f}' for b, p in noul_results)}}})."
                    )
                    target_bot = "none"
                    target_bots = []
                    urgency = "drop"
                    confidence = 0.0
                else:
                    # Choice says respond but nobody claimed → fallback dispatch:
                    # the highest-scoring bot takes it with a wait_silence grace
                    # window (4s social buffer; a human reply cancels the dispatch).
                    target_bot = noul_results[0][0]
                    target_bots = [target_bot]
                    urgency = "wait_silence"
                    confidence = noul_results[0][1]
                    logger.info(
                        f"[ROUTING] No bot claimed message but Choice said "
                        f"'{choice_urgency}'; fallback dispatch to {target_bot} "
                        f"with wait_silence grace (top score {confidence:.2f} "
                        f"below threshold {noul_threshold:.2f})."
                    )
            elif choice_urgency == "drop":
                # Domain expert overrides the global screen: rescue with 4s grace
                logger.info(
                    f"[ROUTING] Rescue: Choice=drop (conf={conf_c:.2f}) "
                    f"overridden by top claim {noul_results[0][1]:.2f} "
                    f">= line {noul_threshold:.2f}."
                )
                target_bots = candidate_bots
                target_bot = candidate_bots[0]
                urgency = "wait_silence"
                confidence = noul_results[0][1]
            else:
                # Both gates passed: use Choice's timing directly
                target_bots = candidate_bots
                target_bot = candidate_bots[0]
                urgency = choice_urgency
                confidence = noul_results[0][1]

            return {
                "target_bot": target_bot,
                "target_bots": target_bots,
                "urgency": urgency,
                "confidence": round(confidence, 2),
                "source": "classifier",
            }
        except Exception as e:
            logger.warning(f"[ROUTING] Decision response parsing failed: {e}; fail-closed drop.")
            return drop

    async def _classify_jev(self, text: str, sender: str, context: str, alias_hint: str, drop: dict) -> Dict[str, Any]:
        """TypeSafe Jev classifier: orthogonal Choice (timing) + Noul×N (assignment).

        Choice is a fixed 3-option question (immediate/wait/drop) that only
        evaluates social context and urgency — independent of bot identity.
        Each bot gets an independent Noul question: 'does this message need {bot}?'
        """
        url, payload, headers, timeout, decision_map = self._build_jev_payload(text, sender, context, alias_hint)
        data = await self._post_decision_api(url, payload, headers, timeout, "Jev")
        if data is None:
            return drop
        return self._arbitrate_decision(data.get("answers", {}) or {}, decision_map, drop)

    async def _classify_decisions(self, text: str, sender: str, context: str, alias_hint: str, drop: dict) -> Dict[str, Any]:
        """Google Gemini Decisions API classifier: the SAME orthogonal
        questionnaire contract as Jev (1 Choice timing question + N per-bot
        Noul assignment questions) evaluated in one batched, calibrated,
        output-free request. Calibrated probabilities feed the shared
        arbitration (dynamic threshold lines / rescue / fallback) unchanged."""
        url, payload, headers, timeout, decision_map = self._build_decisions_payload(text, sender, context, alias_hint)
        data = await self._post_decision_api(url, payload, headers, timeout, "Decisions")
        if data is None:
            return drop
        return self._arbitrate_decision(data.get("answers", {}) or {}, decision_map, drop)


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
        inflight_ttl: float = 600.0,
        resume_drop_fn: Optional[Callable[[Any, Any, str], None]] = None,
    ):
        self.my_bot = str(bot_username).lower().lstrip("@")
        self.cfg = cfg
        self.relay = relay
        self.resume_drop_fn = resume_drop_fn
        self.observer = AutonomousObserver(self.my_bot, cfg, dispatch) if dispatch else None
        self.is_arbiter = (self.my_bot == cfg.arbiter_bot)
        # In-flight tasks: chat_id -> {sender, msg_id, bot, ts}.
        # Feeds a synthetic context line so the classifier knows a dispatched
        # task is still being processed (its reply has not landed in the
        # buffer yet) — otherwise follow-ups from the same sender read like
        # human small talk and get dropped.
        self._inflight: Dict[Any, Dict[str, Any]] = {}
        self._inflight_ttl: float = inflight_ttl
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

    def flush_pending(self, chat_id: Any) -> None:
        """Delegate to observer: flush any pending wait_silence after bot reply."""
        if self.observer is not None:
            self.observer.flush_pending(chat_id)

    def inflight_marker(self, chat_id: Any, buffer: Any) -> str:
        """Synthetic context line for a still-running immediate task, or "".

        Cleared once the target bot has spoken after the dispatched msg_id
        (reply landed) or after a TTL fallback (lost reply / crash safety).
        """
        rec = self._inflight.get(chat_id)
        if rec is None:
            return ""
        if time.time() - rec.get("ts", 0.0) > self._inflight_ttl:
            self._inflight.pop(chat_id, None)
            return ""
        try:
            for entry in reversed(buffer):
                if not entry.get("is_bot"):
                    continue
                # Only the target bot's own reply clears its in-flight task marker.
                # Other bots speaking in the group must not prematurely erase it.
                entry_bot = str(entry.get("bot_username") or "").lower().lstrip("@")
                target_b = str(rec.get("bot") or "").lower().lstrip("@")
                if entry_bot and target_b and entry_bot != target_b:
                    continue
                # Prefer precise matching via reply_to_msg_id: only the reply that
                # actually answers the in-flight message should clear the marker.
                # A bot reply for a DIFFERENT message (e.g. finishing a prior task
                # while a wait_silence countdown is still running) must not erase
                # the marker — the in-flight task hasn't been dispatched yet.
                reply_to = str(entry.get("reply_to_msg_id") or "")
                in_flight_mid = str(rec.get("msg_id") or "")
                if reply_to and reply_to != "0":
                    if reply_to == in_flight_mid:
                        self._inflight.pop(chat_id, None)
                        return ""
                    # Reply answers a different message; don't clear
                    continue
                # Fallback for entries without reply_to_msg_id (pre-linkage data):
                # use msg_id comparison as before
                mid, rid = entry.get("msg_id", 0), rec.get("msg_id", 0)
                try:
                    newer = int(mid) > int(rid)
                except (TypeError, ValueError):
                    newer = str(mid) != str(rid)
                if newer:
                    self._inflight.pop(chat_id, None)
                    return ""
        except Exception:
            pass
        return (
            f"[Bot @{rec.get('bot', '')}]: (currently processing "
            f"{rec.get('sender', '?')}'s last task request; the reply has "
            f"not been posted yet)"
        )

    def chat_allowed(self, chat_id: Any) -> bool:
        if self.cfg.allowed_chat_ids:
            return (
                chat_id in self.cfg.allowed_chat_ids
                or str(chat_id) in {str(x) for x in self.cfg.allowed_chat_ids}
            )
        return True

    def sender_allowed(self, sender_name: str) -> bool:
        if self.cfg.allowed_senders:
            return any(s in sender_name for s in self.cfg.allowed_senders)
        return True

    def _drop_resume(self, msg, log_warning: bool = False) -> None:
        """Mark dropped or delegated resume messages as completed so they don't linger."""
        if getattr(msg, "is_resume", False) and self.resume_drop_fn:
            try:
                self.resume_drop_fn(msg.chat_id, msg.msg_id, msg.text or "")
            except Exception as e:
                if log_warning:
                    logger.warning(f"[ROUTING] Failed to mark dropped resume completed: {e}")

    def _is_message_routable(self, msg) -> bool:
        """Filter out non-routable messages (bots, bare attachments without caption, permissions)."""
        if getattr(msg, "is_bot_relay", False) or bool(getattr(msg, "from_user", {}).get("is_bot", False)):
            return False
        text = (getattr(msg, "text", "") or "").strip()
        if getattr(msg, "attachments", None):
            # Bare media messages with no real text/caption cannot be routed autonomously
            if not text or text in (
                "[Photo Attachment]",
                "[Voice Audio Attachment]",
                "[Document Attachment]",
            ) or (text.startswith("[Document Attachment:") and text.endswith("]")):
                self._drop_resume(msg)
                return False
        if not self.chat_allowed(msg.chat_id) or not self.sender_allowed(msg.sender_name):
            self._drop_resume(msg)
            return False
        return True

    async def _publish_decision(self, msg, decision: Dict[str, Any]) -> None:
        """Broadcast autonomous routing decision and update local in-flight tracking."""
        payload = {
            "event": "autonomous_decision",
            "chat_id": msg.chat_id,
            "chat_type": msg.chat_type,
            "msg_id": msg.msg_id,
            "sender": msg.sender_name,
            "text": msg.text or "",
            "attachments": getattr(msg, "attachments", []) or [],
            "reply_attachments": getattr(msg, "reply_attachments", []) or [],
            "reply_to_msg_id": getattr(msg, "reply_to_msg_id", None),
            "reply_preview": getattr(msg, "reply_preview", "") or "",
            "reply_to_bot_username": getattr(msg, "reply_to_bot_username", "") or "",
            "decide_at": _dt.datetime.now().isoformat(timespec="seconds"),
            "is_resume": bool(getattr(msg, "is_resume", False)),
            **decision,
        }
        # If this was a resume candidate and this bot is NOT a target,
        # arbiter's job is complete (delegated to peer bot via relay).
        # Clear arbiter's retry state so it doesn't linger or turn into poison.
        if getattr(msg, "is_resume", False):
            target_set = {str(t).lower().lstrip("@") for t in decision.get("target_bots", [])}
            if self.my_bot not in target_set:
                self._drop_resume(msg, log_warning=True)

        # Track non-drop dispatches as in-flight tasks for the routing context.
        # Covers both immediate and wait_silence: a wait_silence task that fires
        # after the 4s grace window is still being processed by the bot, and
        # same-sender follow-ups need the marker to avoid being read as chitchat.
        if decision.get("urgency") != "drop" and decision.get("target_bots"):
            self._inflight[msg.chat_id] = {
                "sender": msg.sender_name,
                "msg_id": msg.msg_id,
                "bot": decision["target_bots"][0],
                "ts": time.time(),
            }
        # Publish once: IPC broadcast to peers + local symmetric execution.
        if self.relay is not None:
            try:
                res = self.relay.broadcast_event(payload)
                if inspect.isawaitable(res):
                    await res
            except Exception as e:
                logger.warning(f"[ROUTING] Broadcast failed: {e}")
        if self.observer is not None:
            self.observer.on_decision(payload)

    async def evaluate_and_publish(self, msg) -> None:
        """Arbiter-only entry: run the pipeline and broadcast the decision once."""
        if not self.is_arbiter or self.arbiter is None:
            return
        self.cfg.reload_if_modified()
        if not self._is_message_routable(msg):
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
            self._drop_resume(msg)
            return  # physical noise: silently skip, no broadcast
        if decision.get("target_bot", "none") == "none":
            self._drop_resume(msg)
            return  # semantic drop: silently skip, no broadcast

        # Resume messages: timing already settled (confirmed unanswered by the
        # watermark scan). Override any wait/drop from Choice to immediate so
        # the candidate is dispatched without a grace window or timeout delay,
        # while keeping the Noul-based bot assignment intact.
        if getattr(msg, "is_resume", False) and decision.get("urgency") != "immediate":
            logger.info(
                f"[ROUTING] Resume override: {decision.get('urgency')}→immediate "
                f"for chat {msg.chat_id} (target={decision.get('target_bot')})."
            )
            decision["urgency"] = "immediate"

        await self._publish_decision(msg, decision)
