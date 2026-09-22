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
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import httpx
 
logger = logging.getLogger("groupconnect.routing")


def find_default_config_path() -> str:
    """Find the default autonomous configuration file path.

    Standard discovery precedence:
    1. GROUPCONNECT_ROUTING_CONFIG environment variable
    2. ~/.config/guaguahome/autonomous_config.json or ~/.config/groupconnect/autonomous_config.json
    3. autonomous_config.json (repository root)
    4. autonomous_config.example.json (repository root, fallback example)
    """
    env_path = os.environ.get("GROUPCONNECT_ROUTING_CONFIG")
    if env_path and os.path.isfile(env_path):
        return env_path

    for xdg_dir in ("guaguahome", "groupconnect"):
        candidate = os.path.expanduser(f"~/.config/{xdg_dir}/autonomous_config.json")
        if os.path.isfile(candidate):
            return candidate

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    for name in ("autonomous_config.json", "autonomous_config.example.json"):
        p = os.path.join(repo_root, name)
        if os.path.isfile(p):
            return p

    return os.path.join(repo_root, "autonomous_config.example.json")


DEFAULT_CONFIG_PATH = find_default_config_path()

# Fail-safe classifier wording, used ONLY when the rules file (single source
# of truth) is missing or malformed. Live wording lives in the family-space
# routing_rules.md, hot-reloaded on every classification call.
DEFAULT_IMMEDIATE_CRITERIA = (
    "Reply to {bot}'s earlier question/offer, or an imperative instruction matching: {role}"
)
DEFAULT_WAIT_CRITERIA = (
    "A question needing data, information, or recommendations matching: {role}"
)
DEFAULT_DROP_CRITERIA = (
    "Interpersonal conversation between group members, not directed at any bot"
)
DEFAULT_GROUP_DESCRIPTION = (
    "Private group chat. Configured assistant bots handle different specialized tasks."
)
DEFAULT_PARALLEL_CRITERIA = (
    "The sender explicitly wants {bot} ({role}) to participate, respond, or collaborate simultaneously alongside other assistants (e.g. coordinative phrases: 'A and B both', 'together'). Not causative dispatch ('A ask B to do X')."
)


def parse_rule_templates(content: str) -> Dict[str, str]:
    """Parses '## <key>' sections of routing_rules.md into a {key: text} dict.

    Keys are single lowercase words (immediate / wait / drop / group).
    Multi-word headings like '## Decision Rules' never match, so the rules
    prose stays out of the template map.
    """
    templates: Dict[str, str] = {}
    current: Optional[str] = None
    buf: list = []
    for line in content.splitlines():
        m = re.match(r"^##\s+([a-z_]+)\s*$", line)
        if m:
            if current:
                templates[current] = "\n".join(buf).strip()
            current, buf = m.group(1), []
        elif current:
            buf.append(line)
    if current:
        templates[current] = "\n".join(buf).strip()
    return templates


class AutonomousConfig:
    """Loads and validates the shared autonomous routing configuration."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or find_default_config_path()
        self._last_mtime: float = 0.0
        self._load()

    def reload_if_modified(self) -> None:
        try:
            if not self.path or not os.path.isfile(self.path):
                return
            mtime = os.path.getmtime(self.path)
            if mtime != self._last_mtime:
                self._load()
        except Exception:
            pass

    def _load(self) -> None:
        raw = {}
        if self.path and os.path.isfile(self.path):
            try:
                self._last_mtime = os.path.getmtime(self.path)
                with open(self.path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                logger.warning("Failed to load autonomous config from %s: %s", self.path, e)
                raw = {}
        else:
            self._last_mtime = 0.0

        cfg = raw.get("autonomous", {})
        self.enabled: bool = bool(cfg.get("enabled", False))
        self.arbiter_bot: str = str(cfg.get("arbiter_bot", "")).lower().lstrip("@")
        self.ipc_dir: str = cfg.get("ipc_dir", "/tmp/groupconnect_ipc")

        windows = cfg.get("windows", {})
        self.immediate_secs: float = float(windows.get("immediate_secs", 1.0))
        self.silence_secs: float = float(windows.get("silence_secs", 4.0))

        ctx = cfg.get("context", {})
        self.context_window_size: int = int(ctx.get("window_size", 3))

        self.aliases: Dict[str, list] = {
            str(bot).lower().lstrip("@"): list(aliases or [])
            for bot, aliases in cfg.get("aliases", {}).items()
        }
        self.alias_mode: str = str(cfg.get("alias_mode", "bypass"))  # bypass | hint
        # Pre-bypass filters: self-referential sentences (e.g. "call me assistant")
        # get dropped BEFORE the alias wake; {alias} is expanded per alias.
        self.alias_drop_regex: list = list(cfg.get("alias_drop_regex", []))
        self.noise_regex: list = [re.compile(p) for p in cfg.get("noise_regex", [])]

        # ---- Classifier provider registry (self-describing) ----
        # classifier.active            -> the switch: which providers entry is live
        # classifier.rules_file        -> shared wording (single source of truth) for ALL engines
        # classifier.providers.<name> -> per-provider params + resources:
        #   engine           "jev" (TypeSafe structured) | "gemini" (free-text JSON prompt)
        #   model / api_key_env / api_key / timeout_ms
        #   prompt_template gemini-engine skeleton file (jev engines need none)
        clf = cfg.get("classifier", {})
        self.confidence_threshold: float = float(clf.get("confidence_threshold", 0.80))
        self.parallel_threshold: float = float(clf.get("parallel_threshold", self.confidence_threshold))
        self.daily_budget: int = int(clf.get("daily_budget", 800))
        self.rules_file: str = str(clf.get("rules_file", cfg.get("rules_file", "")))

        providers = clf.get("providers")
        if not providers:
            # Legacy flat layout (provider/model/api_key_env directly under
            # classifier): synthesize a one-entry registry, warn to migrate.
            legacy = str(clf.get("provider", "google_ai_studio"))
            entry = {
                "engine": "jev" if legacy == "typesafe" else "gemini",
                "model": clf.get("model", "gemini-3.5-flash-lite"),
                "api_key_env": clf.get("api_key_env", "GEMINI_ROUTER_API_KEY"),
                "api_key": clf.get("api_key", ""),
                "timeout_ms": clf.get("timeout_ms", 3000),
            }
            if cfg.get("prompt_file"):
                entry["prompt_template"] = cfg.get("prompt_file")
            providers = {legacy: entry}
            default_active = legacy
            logger.warning(
                "[ROUTING] Flat 'classifier' block is deprecated; migrate to "
                "'classifier.providers' registry (synthesized legacy provider '%s').", legacy
            )
        else:
            default_active = "google_ai_studio"
        self.providers: Dict[str, dict] = {
            str(name).lower().lstrip("@"): (p if isinstance(p, dict) else {})
            for name, p in providers.items()
        }
        self.active_provider: str = str(clf.get("active", default_active)).lower()
        pcfg = self.providers.get(self.active_provider)
        if pcfg is None:
            logger.warning(
                "[ROUTING] classifier.active '%s' not found in providers %s; "
                "classifier fails closed until fixed.",
                self.active_provider, sorted(self.providers),
            )
            pcfg = {}
        self.engine: str = str(pcfg.get("engine", "gemini")).lower()
        self.model: str = str(pcfg.get("model", ""))
        self.api_key: str = os.environ.get(str(pcfg.get("api_key_env", "")), "") \
            or str(pcfg.get("api_key", ""))
        self.timeout_ms: int = int(pcfg.get("timeout_ms", 3000))
        self.prompt_file: str = str(pcfg.get("prompt_template", ""))

        self.roles: Dict[str, str] = {
            str(bot).lower().lstrip("@"): role
            for bot, role in cfg.get("roles", {}).items()
        }
        # Classifier wording (immediate/wait/drop/group) lives in the rules
        # file - the single source of truth - parsed from '## <key>' sections.
        # Code keeps only fail-safe defaults when the file is missing.
        self.rule_templates: Dict[str, str] = {}
        rules_path = self._resolve_rules_path()
        if rules_path and os.path.isfile(rules_path):
            try:
                with open(rules_path, "r", encoding="utf-8") as f:
                    self.rule_templates = parse_rule_templates(f.read())
            except Exception as e:
                logger.warning("[ROUTING] Failed to parse rule templates from %s: %s", rules_path, e)

        conc = cfg.get("concurrency", {})
        self.max_queue_backlog: int = int(conc.get("max_queue_backlog", 2))
        self.degrade: str = cfg.get("degrade", "alias_only")
        self.throttle_min_interval: float = float(conc.get("throttle_min_interval", 1.5))

        self.allowed_chat_ids: set = set(cfg.get("allowed_chat_ids", []))
        self.allowed_senders: set = set(cfg.get("allowed_senders", []))

    def _resolve_rules_path(self) -> str:
        """Absolute path of the rules file, or '' when not resolvable."""
        path = self.rules_file or ""
        if path and not os.path.isabs(path):
            base = os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()
            path = os.path.join(base, path)
        return path

    def is_alias_self_referential(self, alias: str, text: str) -> bool:
        """True if this specific alias is used in a self-referential / banter pattern."""
        for tpl in self.alias_drop_regex:
            try:
                if re.search(tpl.replace("{alias}", re.escape(alias)), text):
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
        else:
            target_set = {target}

        urgency = decision.get("urgency", "drop")
        chat_id = decision.get("chat_id")
        should_act = (self.my_bot in target_set) or ("all" in target_set) or (target == "all")
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
    def _load_prompt(self) -> str:
        path = self.cfg.prompt_file
        if path and not os.path.isabs(path):
            path = os.path.join(os.path.dirname(os.path.abspath(self.cfg.path)), path)
        if not path or not os.path.exists(path):
            logger.warning(f"[ROUTING] Prompt file missing: {path}")
            return ""
        mtime = os.path.getmtime(path)
        if self._prompt_cache is None or mtime != self._prompt_mtime:
            with open(path, "r", encoding="utf-8") as f:
                self._prompt_cache = f.read()
            self._prompt_mtime = mtime
        return self._prompt_cache

    def _render_prompt(self, text: str, sender: str, context: str, alias_hint: str) -> str:
        tpl = self._load_prompt()
        roles = "\n".join(f"  {bot}: {role}" for bot, role in self.cfg.roles.items())
        return (
            tpl.replace("{ROLES}", roles)
               .replace("{RULES_SECTION}", self._load_rules_instructions())
               .replace("{CONTEXT}", context or "(no prior messages)")
               .replace("{SENDER}", sender)
               .replace("{TEXT}", text)
               .replace("{ALIAS_HINT}", alias_hint)
        )

    def _load_rules_instructions(self) -> str:
        """Loads decision instructions for structured classifiers like Jev.

        1. Read from explicit rules_file if configured and exists.
           (Everything below '# Classifier Templates' is wording, not
           instructions, so it is stripped before use.)
        2. Extract the 'Decision Rules' section from prompt_file.
        3. Fallback to default decision rules.
        """
        path = self.cfg._resolve_rules_path()
        if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    if "\n# Classifier Templates" in content:
                        content = content.split("\n# Classifier Templates", 1)[0].strip()
                    if content:
                        return content
                except Exception as e:
                    logger.warning(f"[ROUTING] Failed to read rules_file {path}: {e}")

        prompt = self._load_prompt()
        if prompt and "Decision Rules" in prompt:
            parts = prompt.split("Decision Rules", 1)[1]
            rules_part = parts.split("Output STRICT JSON", 1)[0].strip()
            return f"Decide which bot should reply, or if bots stay silent.\nDecision Rules {rules_part}"

        return (
            "Decide which bot should reply to current_message, or if bots should stay silent. "
            "Rules (first match wins): "
            "1. REPLY TO BOT: If recent_conversation shows a Bot asked a question, offered options, or proposed a plan, "
            "and current_message is an answer, acknowledgment, confirmation (e.g. '可以', '好的', '行', '确定'), "
            "or a follow-up question/feedback directed to that bot, the bot that spoke/asked replies immediately. "
            "2. CHITCHAT: If current_message is interpersonal conversation between group members "
            "(flirting, affection, venting, small talk, private plans between members), or mentions a bot in a third-person narrative/banter, bots stay silent. "
            "3. IMPERATIVE: If current_message is a functional imperative instruction for a bot "
            "(controlling appliances, alarms, setting reminders, clear directives), the matching bot replies immediately. "
            "4. QUESTION: If current_message is an explicit question needing data, lookup, or recommendations "
            "(contains question words like 几点/多少/怎么/什么/吗 or question mark), the matching bot replies after waiting."
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
        drop = {"target_bot": "none", "target_bots": [], "urgency": "drop", "confidence": 0.0, "source": "classifier"}
        if not self.cfg.api_key:
            logger.warning("[ROUTING] No API key configured; fail-closed drop.")
            return drop
        if self._budget_exceeded():
            if self.cfg.degrade == "alias_only":
                logger.warning("[ROUTING] Daily budget exceeded; fail-closed drop (alias bypass still active).")
                return drop
        engine = self.cfg.engine
        if engine == "jev":
            return await self._classify_jev(text, sender, context, alias_hint, drop)
        if engine == "gemini":
            return await self._classify_gemini(text, sender, context, alias_hint, drop)
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
        # Legacy fallback if someone still has all_immediate in templates
        all_imm = t.get("all_immediate", "")
        if all_imm:
            criteria["all_immediate"] = all_imm
            jev_map["all_immediate"] = ("all", "immediate")
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

        url = "https://api.typesafe.ai/v1/systemone"
        timeout = self.cfg.timeout_ms / 1000.0
        payload = {"state": state, "model": self.cfg.model, "questions": questions}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        retryable = {429, 500, 502, 503, 504}
        backoffs = [1.0, 2.0, 4.0]
        async with self._call_lock:
            wait = self._min_interval - (asyncio.get_event_loop().time() - self._last_call_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = asyncio.get_event_loop().time()
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
                all_prob = float(probs.get("all_immediate", 0.0) or 0.0)
                for k, p in probs.items():
                    if k == "all_immediate":
                        continue
                    for b in bot_probs:
                        if k.startswith(b):
                            bot_probs[b] += float(p or 0.0)

                best_bot, best_bot_prob = max(bot_probs.items(), key=lambda x: x[1])
                # Three-way comparison if all_immediate was in Choice (legacy backward-compat)
                if all_prob >= self.cfg.confidence_threshold and all_prob > best_bot_prob and all_prob > none_prob:
                    target_bot = "all"
                    urgency = "immediate"
                    confidence = all_prob
                elif best_bot_prob >= self.cfg.confidence_threshold and best_bot_prob > none_prob:
                    target_bot = best_bot
                    confidence = best_bot_prob
                    p_imm = float(probs.get(f"{best_bot}_immediate", 0.0) or 0.0)
                    p_wait = float(probs.get(f"{best_bot}_wait", 0.0) or 0.0)
                    urgency = "immediate" if p_imm >= p_wait else "wait_silence"
                elif none_prob >= self.cfg.confidence_threshold or best_bot_prob < self.cfg.confidence_threshold:
                    target_bot = "none"
                    urgency = "drop"
                    confidence = max(none_prob, 1.0 - best_bot_prob)

            # Fail-closed check: if below threshold or drop, reject immediately
            if urgency == "drop" or confidence < self.cfg.confidence_threshold or target_bot == "none":
                decision = {
                    "target_bot": "none",
                    "target_bots": [],
                    "urgency": "drop",
                    "confidence": round(confidence, 2),
                    "source": "classifier",
                }
                self._budget_used += 1
                return decision

            # Primary bot succeeded! Check per-bot Noul answers for parallel co-respondents
            if target_bot == "all":
                target_bots = list(self.cfg.roles.keys())
            else:
                target_bots = [target_bot]
                for b in self.cfg.roles:
                    if b == target_bot:
                        continue
                    noul_ans = answers.get(f"parallel_{b}", {})
                    noul_prob = float(noul_ans.get("noul", 0.0) or 0.0)
                    if noul_prob >= self.cfg.parallel_threshold:
                        target_bots.append(b)

            is_all = len(target_bots) == len(self.cfg.roles) and len(self.cfg.roles) > 1
            final_target = "all" if is_all else target_bot

            decision = {
                "target_bot": final_target,
                "target_bots": target_bots,
                "urgency": urgency,
                "confidence": round(confidence, 2),
                "source": "classifier",
            }
            self._budget_used += 1
            return decision

    async def _classify_gemini(self, text: str, sender: str, context: str, alias_hint: str, drop: dict) -> Dict[str, Any]:
        """Gemini Flash-Lite classifier: free-text prompt -> JSON."""
        prompt = self._render_prompt(text, sender, context, alias_hint)
        if not prompt:
            return drop
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.cfg.model}:generateContent?key={self.cfg.api_key}")
        timeout = self.cfg.timeout_ms / 1000.0
        async with self._call_lock:  # throttle: no classifier bursts (anti-429)
            wait = self._min_interval - (asyncio.get_event_loop().time() - self._last_call_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call_ts = asyncio.get_event_loop().time()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(url, json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "response_mime_type": "application/json",
                            "temperature": 0.0,
                        },
                    })
                if res.status_code == 429:  # rate limit: exponential backoff retries
                    for attempt, backoff in enumerate((2.0, 4.0), start=1):
                        logger.warning(f"[ROUTING] Classifier 429; backoff {backoff}s (retry {attempt}/2).")
                        await asyncio.sleep(backoff)
                        async with httpx.AsyncClient(timeout=timeout) as client:
                            res = await client.post(url, json={
                                "contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {
                                    "response_mime_type": "application/json",
                                    "temperature": 0.0,
                                },
                            })
                        if res.status_code != 429:
                            break
                if res.status_code != 200:
                    logger.warning(f"[ROUTING] Classifier HTTP {res.status_code}; fail-closed drop.")
                    return drop
                data = json.loads(res.json()["candidates"][0]["content"]["parts"][0]["text"])
            except Exception as e:
                logger.warning(f"[ROUTING] Classifier failed: {e}; fail-closed drop.")
                return drop

            raw_target = data.get("target_bots") or data.get("target_bot", "none")
            if isinstance(raw_target, list):
                target_bots = [str(t).lower().lstrip("@") for t in raw_target]
            elif isinstance(raw_target, str):
                t_str = str(raw_target).lower().lstrip("@")
                if t_str == "all":
                    target_bots = list(self.cfg.roles.keys())
                elif t_str in self.cfg.roles:
                    target_bots = [t_str]
                else:
                    target_bots = []
            else:
                target_bots = []

            is_all = len(target_bots) == len(self.cfg.roles) and len(self.cfg.roles) > 1
            if is_all:
                primary_target = "all"
            elif target_bots:
                primary_target = target_bots[0]
            else:
                primary_target = "none"

            decision = {
                "target_bot": primary_target,
                "target_bots": target_bots,
                "urgency": str(data.get("urgency", "drop")).lower(),
                "confidence": float(data.get("confidence", 0.0) or 0.0),
                "source": "classifier",
            }
            if decision["urgency"] not in ("immediate", "wait_silence", "drop"):
                decision["urgency"] = "drop"
            if decision["urgency"] != "drop" and decision["confidence"] < self.cfg.confidence_threshold:
                logger.info(f"[ROUTING] Confidence {decision['confidence']} below threshold; drop.")
                decision.update(urgency="drop", target_bot="none", target_bots=[])
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
