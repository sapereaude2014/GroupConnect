"""
Central Orchestrator Engine for GroupConnect.
Dynamically resolves Channels and Agent Adapters from registries.
Connects Context Manager, Gatekeeper, and Command Parser.
"""

import asyncio
import collections
from datetime import datetime
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, get_adapter_class
import groupconnect.adapters.antigravity
import groupconnect.adapters.claude_code
import groupconnect.adapters.codex
import groupconnect.adapters.opencode

try:
    import groupconnect.adapters.teleagent
except ImportError:
    pass  # TeleAgent adapter is optional

from groupconnect.channels.base import BaseChannel, InboundMessage, get_channel_class
import groupconnect.channels.telegram
import groupconnect.channels.discord
import groupconnect.channels.slack
import groupconnect.channels.feishu
import groupconnect.channels.wecom

from groupconnect.core.parser import parse_bot_command
from groupconnect.core.config import GatewayConfig
from groupconnect.core.context import ContextManager
from groupconnect.core.gatekeeper import Gatekeeper
from groupconnect.core.relay import CrossBotRelay
from groupconnect.routing import AutonomousController, AutonomousConfig

logger = logging.getLogger("groupconnect.engine")

# Resume-burst settle window: a re-dispatched candidate refreshes it on every
# dispatch; when no new one arrives for this long, the burst is declared
# complete and parked queue workers are released (single coalesced drain).
RESUME_BURST_SETTLE_SECS = 8.0


def _load_soul(config: GatewayConfig) -> str:
    """Load specific bot soul from config.soul_path, config.souls_dir, or default workspace .agents/souls/{bot_username}.md."""
    bot_username = config.bot_username
    if getattr(config, "soul_path", None):
        soul_path = os.path.expanduser(config.soul_path)
    elif getattr(config, "souls_dir", None):
        soul_path = os.path.join(os.path.expanduser(config.souls_dir), f"{bot_username}.md")
    else:
        soul_path = os.path.join(config.workspace_dir, ".agents", "souls", f"{bot_username}.md")

    if os.path.isfile(soul_path):
        try:
            with open(soul_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                logger.info(f"Loaded soul for @{bot_username} from {soul_path}")
                return f"【Your Soul & Persona】\n{content}\n\n"
        except Exception as e:
            logger.warning(f"Failed to load soul from {soul_path}: {e}")
    return ""


from groupconnect.core.commands import CustomCommandDispatcher
from groupconnect.core.delivery import (
    OutboundDelivery,
    SENDFILE_TAG_PATTERN,
    extract_outbound_files,
    strip_sendfile_tags,
)
from groupconnect.core.pattern import PatternExecutor
from groupconnect.core.recovery import ResumeManager

_extract_outbound_files = extract_outbound_files
_strip_sendfile_tags = strip_sendfile_tags


class GroupConnectEngine:
    def __init__(self, config: GatewayConfig):
        self.config = config

        # 1. Context & Gatekeeper (Secure-by-Default with Configurable DM Access)
        self.context_mgr = ContextManager(
            max_history_len=config.max_history_len,
            chat_logs_dir=config.chat_logs_dir,
            bot_username=config.bot_username
        )
        self.gatekeeper = Gatekeeper(
            allowed_chat_ids=config.allowed_chat_ids,
            allowed_user_ids=config.allowed_user_ids,
            allowed_usernames=config.allowed_usernames,
            allow_open_access=config.allow_open_access,
            allow_group_members_dm=config.allow_group_members_dm
        )

        # 2. Agent Adapter Dynamic Factory
        self.adapter: BaseAgentAdapter = self._create_adapter()

        # 3. Channel Dynamic Factory
        self.channel: BaseChannel = self._create_channel()

        # 4. Cross-Bot IPC Relay
        self.relay = CrossBotRelay(
            bot_username=config.bot_username,
            bot_name=config.bot_name,
            ipc_dir=config.ipc_dir,
            on_event=self.on_relay_event
        )

        # Concurrency Locks & Queue State
        self.chat_locks: Dict[Any, asyncio.Lock] = {}
        self.chat_queues: Dict[Any, asyncio.Queue] = {}
        self.chat_tasks: Dict[Any, asyncio.Task] = {}
        # Resume-burst batching: while re-dispatched candidates are still landing,
        # queue workers stay parked so the whole burst coalesces into ONE reply.
        self._resume_hold_until = 0.0
        self._resume_hold_task: Optional[asyncio.Task] = None
        self._triggered_msg_ids: collections.deque = collections.deque(maxlen=200)

        # 5. Modular Subsystems: Commands, Pattern Fast Lane, Delivery, Recovery
        self.command_dispatcher = CustomCommandDispatcher(
            commands=getattr(config, "custom_commands", []),
            channel=self.channel,
            context_mgr=self.context_mgr,
            bot_name=config.bot_name,
            bot_username=config.bot_username,
            relay=self.relay
        )
        self._custom_commands_map = self.command_dispatcher.commands_map
        self._running_custom_commands = self.command_dispatcher.running_commands

        self.pattern_executor = PatternExecutor(
            pattern_configs=getattr(config, "pattern_commands", []),
            custom_commands_map=self._custom_commands_map,
            command_dispatcher=self.command_dispatcher,
            channel=self.channel
        )
        self._pattern_commands = self.pattern_executor.patterns

        resume_secs = int(getattr(config, "resume_unanswered_secs", 300))
        self.resume_manager = ResumeManager(
            context_mgr=self.context_mgr,
            bot_username=config.bot_username,
            window_seconds=resume_secs
        )

        self.outbound_delivery = OutboundDelivery(
            channel=self.channel,
            context_mgr=self.context_mgr,
            workspace_dir=config.workspace_dir,
            bot_name=config.bot_name,
            bot_username=config.bot_username,
            relay=self.relay
        )
        self.is_running = False

        # 5. Autonomous Routing (免@自主唤醒: single-arbiter + symmetric observers)
        self.autonomous: Optional[AutonomousController] = None
        acfg = getattr(config, "autonomous_config", None)
        if acfg is None:
            acfg_path = getattr(config, "autonomous_config_path", "")
            if not acfg_path:
                from groupconnect.routing.router import find_default_config_path
                candidate = find_default_config_path()
                if os.path.exists(candidate):
                    acfg_path = candidate
            if acfg_path and os.path.exists(acfg_path):
                try:
                    acfg = AutonomousConfig(acfg_path)
                except Exception as e:
                    logger.warning(f"Failed to load autonomous config from path: {e}")
        if acfg and getattr(acfg, "enabled", False):
            try:
                self.autonomous = AutonomousController(
                    bot_username=config.bot_username,
                    cfg=acfg,
                    relay=self.relay,
                    dispatch=self._dispatch_autonomous,
                    context_summary_fn=self._build_routing_context,
                )
            except Exception as e:
                logger.warning(f"Autonomous routing disabled: {e}")

    def _create_adapter(self) -> BaseAgentAdapter:
        adapter_cls = get_adapter_class(self.config.engine_type)
        if self.config.engine_type == "antigravity":
            return adapter_cls(
                agy_bin=self.config.agy_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model or "gemini-3.8-flash-high",
                timeout_secs=self.config.timeout_secs
            )
        elif self.config.engine_type in ("claude", "claude_code"):
            return adapter_cls(
                claude_bin=self.config.claude_bin,
                workspace_dir=self.config.workspace_dir,
                timeout_secs=self.config.timeout_secs
            )
        elif self.config.engine_type in ("codex",):
            return adapter_cls(
                codex_bin=self.config.codex_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model,
                timeout_secs=self.config.timeout_secs
            )
        elif self.config.engine_type in ("opencode", "open-code"):
            return adapter_cls(
                opencode_bin=self.config.opencode_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model,
                timeout_secs=self.config.timeout_secs
            )
        elif self.config.engine_type in ("teleagent", "tele-worker", "teleworker"):
            return adapter_cls(
                teleworker_bin=self.config.teleworker_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model,
                timeout_secs=self.config.timeout_secs,
                output_grace_secs=self.config.output_grace_secs
            )
        # --- End local TeleAgent adapter (optional, not in upstream) ---
        else:
            return adapter_cls(workspace_dir=self.config.workspace_dir, timeout_secs=self.config.timeout_secs)

    def _create_channel(self) -> BaseChannel:
        channel_cls = get_channel_class(self.config.platform)
        return channel_cls(self.config, self.on_inbound_message)

    def get_chat_lock(self, chat_id: Any) -> asyncio.Lock:
        if chat_id not in self.chat_locks:
            self.chat_locks[chat_id] = asyncio.Lock()
        return self.chat_locks[chat_id]

    async def start(self) -> None:
        if hasattr(self.config, "validate_credentials"):
            self.config.validate_credentials()
        self.is_running = True
        if not self.gatekeeper.is_whitelist_active() and not self.config.allow_open_access:
            logger.warning(
                "🔒 [SECURITY ALERT] No allowlist configured. Running in Safe Lockdown Mode. "
                "All incoming messages will be rejected until allowed_chat_ids, allowed_user_ids, "
                "or allowed_usernames are configured in config.json."
            )
        logger.info(f"Starting GroupConnect Gateway (Platform: {self.config.platform}, Engine: {self.config.engine_type})...")

        await self.relay.start()
        has_schedules = any("schedule" in c for c in getattr(self.config, "custom_commands", []))
        is_arbiter = (self.autonomous.is_arbiter if self.autonomous else True)
        scheduler_task = asyncio.create_task(self._scheduled_tasks_loop()) if (has_schedules and is_arbiter) else None
        await self._resume_unanswered_messages()
        try:
            await self.channel.start()
        finally:
            self.is_running = False
            if self._resume_hold_task and not self._resume_hold_task.done():
                self._resume_hold_task.cancel()
            if scheduler_task:
                scheduler_task.cancel()
            for task in self.chat_tasks.values():
                if not task.done():
                    task.cancel()
            if hasattr(self.channel, "stop"):
                try:
                    await self.channel.stop()
                except Exception as e:
                    logger.warning(f"Error stopping channel during shutdown: {e}")
            try:
                await self.relay.stop()
            except Exception as e:
                logger.warning(f"Error stopping relay during shutdown: {e}")
            try:
                self.adapter.close()
            except Exception as e:
                logger.warning(f"Error closing adapter during shutdown: {e}")

    async def _scheduled_tasks_loop(self) -> None:
        """Generic scheduled background runner for custom_commands with 'schedule' config."""
        last_run_keys: Set[str] = set()
        while self.is_running:
            try:
                await asyncio.sleep(1800)  # check every 30 mins
                now = datetime.now()
                today_str = now.strftime("%Y%m%d")
                for cmd_cfg in getattr(self.config, "custom_commands", []):
                    sched = cmd_cfg.get("schedule")
                    if not isinstance(sched, dict):
                        continue
                    sched_weekday = sched.get("weekday")
                    sched_hour = sched.get("hour")
                    if sched_weekday is not None and now.weekday() != sched_weekday:
                        continue
                    if sched_hour is not None and now.hour != sched_hour:
                        continue
                    cmd_name = str(cmd_cfg.get("command", "")).strip().lower()
                    run_key = f"{cmd_name}_{today_str}_{sched_hour}"
                    if run_key not in last_run_keys:
                        last_run_keys.add(run_key)
                        logger.info(f"[SCHEDULER] Triggering scheduled task '{cmd_name}'...")
                        script = os.path.expanduser(cmd_cfg.get("script", ""))
                        if os.path.isfile(script):
                            proc = await asyncio.create_subprocess_exec(
                                script,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            stdout, stderr = await proc.communicate()
                            if proc.returncode != 0:
                                err_tail = (stderr or b"").decode("utf-8", "replace").strip()[-300:]
                                logger.error(f"[SCHEDULER] Scheduled task '{cmd_name}' failed (rc={proc.returncode}): {err_tail}")
                                await self._notify_task_failure(cmd_name, proc.returncode, err_tail)
                        else:
                            logger.error(f"[SCHEDULER] Script missing for '{cmd_name}': {script}")
                            await self._notify_task_failure(cmd_name, -1, f"脚本不存在: {script}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in scheduler loop: {e}")

    async def _notify_task_failure(self, task_name: str, returncode: int, err_tail: str) -> None:
        """Alert allowed chats when a scheduled task fails."""
        alert_msg = (
            f"⚠️ **[定时任务告警]** 任务 `{task_name}` 执行异常！\n\n"
            f"- **退出码**: `{returncode}`\n"
            f"- **错误摘要**: `{err_tail or '无输出'}`\n\n"
            f"👉 请检查主机环境与脚本状态。"
        )
        for chat_id in getattr(self.config, "allowed_chat_ids", []):
            try:
                await self.channel.send_reply(chat_id, alert_msg)
            except Exception as e:
                logger.error(f"[SCHEDULER] Failed to deliver alert to {chat_id}: {e}")

    async def on_relay_event(self, event: Dict[str, Any]) -> None:
        """Handles cross-bot broadcast events received via local IPC."""
        if event.get("event") == "autonomous_decision":
            if self.autonomous is not None:
                self.autonomous.on_relay_event(event)
            return
        if event.get("event") != "bot_reply":
            return

        chat_id = event.get("chat_id")
        chat_type = event.get("chat_type", "group")
        sender_bot = (event.get("from_bot") or "").lower().lstrip("@")
        sender_name = event.get("from_name", sender_bot)
        text = event.get("text", "")
        msg_id = event.get("msg_id", 0)
        hop_count = int(event.get("hop_count", 0))

        # 1. Skip self events
        if sender_bot == self.config.bot_username.lower():
            return

        # 2. Gatekeeper authorization check
        if self.gatekeeper.is_whitelist_active() and self.config.allowed_chat_ids:
            matched = (
                chat_id in self.config.allowed_chat_ids
                or str(chat_id) in self.config.allowed_chat_ids
            )
            if not matched:
                try:
                    matched = int(chat_id) in self.config.allowed_chat_ids
                except (ValueError, TypeError):
                    pass
            if not matched:
                return

        # 3. Check trigger conditions (@my_bot_username and within hop limit)
        bot_tag = f"@{self.config.bot_username}".lower()
        is_triggered = (bot_tag in text.lower()) and (hop_count < self.config.max_bot_hops)

        inbound = InboundMessage(
            chat_id=chat_id,
            chat_type=chat_type,
            msg_id=msg_id,
            sender_name=f"{sender_name} (@{sender_bot})",
            from_user={"id": 0, "first_name": sender_name, "username": sender_bot, "is_bot": True},
            text=text,
            reply_to_msg_id=None,  # Standalone relayed broadcast event
            reply_preview="",
            is_triggered=is_triggered,
            attachments=[],
            reply_attachments=[],
            is_bot_relay=True,
            hop_count=hop_count + 1
        )

        logger.info(
            f"CrossBotRelay synced reply from @{sender_bot} in {chat_id} "
            f"(triggered: {is_triggered}, hop: {hop_count})"
        )
        await self.on_inbound_message(inbound)

    async def _resume_unanswered_messages(self) -> None:
        """After a restart, re-dispatch recent human messages that never received any bot reply.
        Delegates to ResumeManager with freshness window and poison message quarantine."""
        window = int(getattr(self.config, "resume_unanswered_secs", 300))
        resumable = self.resume_manager.find_unanswered_messages(
            window_seconds=window,
            allowed_chat_ids=self.config.allowed_chat_ids
        )
        if resumable:
            # Park queue workers until the burst finishes landing so every
            # re-dispatched candidate drains in ONE coalesced batch (a single
            # summarized reply) instead of fragmenting per-dispatch.
            self._extend_resume_hold()
        for chat_id, inbound in resumable:
            await self.on_inbound_message(inbound, record=False)

    def _resume_workers_held(self) -> bool:
        """True while a resume burst is still landing (workers stay parked)."""
        return time.time() < self._resume_hold_until

    def _extend_resume_hold(self) -> None:
        """(Re)arms the resume-burst settle window and ensures a release task."""
        self._resume_hold_until = time.time() + RESUME_BURST_SETTLE_SECS
        task = self._resume_hold_task
        if task is None or task.done():
            self._resume_hold_task = asyncio.create_task(self._release_resume_workers())

    async def _release_resume_workers(self) -> None:
        while True:
            remain = self._resume_hold_until - time.time()
            if remain <= 0:
                break
            await asyncio.sleep(min(remain, 1.0))
        for chat_id, queue in list(self.chat_queues.items()):
            if queue.empty():
                continue
            worker = self.chat_tasks.get(chat_id)
            if worker is None or worker.done():
                self.chat_tasks[chat_id] = asyncio.create_task(self._process_chat_queue(chat_id))

    async def on_inbound_message(self, msg: InboundMessage, record: bool = True) -> None:
        chat_id = msg.chat_id
        chat_type = msg.chat_type

        # 1. Security Gatekeeper Verification (Default-Deny)
        dynamic_checker = getattr(self.channel, "check_user_membership", None)
        authorized, reason = await self.gatekeeper.verify_sender(
            chat_id=chat_id,
            chat_type=chat_type,
            from_user=msg.from_user,
            dynamic_checker=dynamic_checker
        )

        if not authorized:
            if reason == "empty_whitelist_lockdown":
                logger.warning(
                    f"[SECURITY] Blocked request from user {msg.from_user.get('id')} ({msg.sender_name}) "
                    "because allowlist is empty and allow_open_access is false."
                )
                if chat_type == "private" and msg.is_triggered:
                    await self.channel.send_reply(
                        chat_id,
                        "🔒 **Safe Lockdown Mode**\n\n"
                        "No allowlist is configured in `config.json`. To protect local workspace assets, "
                        "access is locked by default.\n\n"
                        "👉 **To authorize yourself**, add your username or numeric ID to `allowed_usernames` "
                        "or `allowed_user_ids` in `config.json`."
                    )
                return
            elif reason == "unauthorized_group":
                logger.warning(f"[SECURITY] Unauthorized group message in {chat_id}. Leaving chat...")
                await self.channel.leave_chat(chat_id)
                return
            elif reason == "unauthorized_user":
                logger.warning(f"[SECURITY] Unauthorized private message from {msg.from_user.get('id')} ({msg.sender_name})")
                if msg.is_triggered:
                    await self.channel.send_reply(
                        chat_id,
                        "⛔ **Access Restricted**\n\nThis bot is a private assistant limited to authorized members only."
                    )
                return

        # 2. Clean query
        raw_text = msg.text
        clean_query = re.sub(rf"@{self.config.bot_username}\b", "", raw_text, flags=re.IGNORECASE).strip()

        # 3. Preemptive /stop Intercept (Bypasses queue & immediately halts in-flight task)
        cmd, target_bot, _ = parse_bot_command(raw_text or "", self.config.bot_username)
        if not cmd and clean_query:
            cmd, target_bot, _ = parse_bot_command(clean_query, self.config.bot_username)
        if cmd == "stop" and msg.is_triggered:
            if getattr(msg, "is_resume", False):
                if self.resume_manager:
                    try:
                        self.resume_manager.mark_completed(chat_id, msg.msg_id, msg.text or "")
                    except Exception:
                        pass
                return
            logger.info(f"Received preemptive /stop command for chat {chat_id}")
            self.adapter.terminate(chat_id)
            if chat_id in self.chat_queues:
                q = self.chat_queues[chat_id]
                while not q.empty():
                    try:
                        q.get_nowait()
                        q.task_done()
                    except (asyncio.QueueEmpty, ValueError):
                        break
            sent_id = await self.channel.send_reply(chat_id, "⏹ Task execution was stopped.", reply_to_msg_id=msg.msg_id)
            clean_sent_id = sent_id if isinstance(sent_id, (int, str)) else 0
            if record:
                self.context_mgr.record_message(
                    chat_id=chat_id,
                    sender_name=msg.sender_name,
                    text=msg.text,
                    msg_id=msg.msg_id,
                    attachments=[]
                )
            try:
                self.context_mgr.record_message(
                    chat_id=chat_id,
                    sender_name=f"{self.config.bot_name} (@{self.config.bot_username})",
                    text="⏹ Task execution was stopped.",
                    msg_id=clean_sent_id,
                    is_bot_reply=True,
                    bot_username=self.config.bot_username,
                    reply_to_msg_id=msg.msg_id or 0
                )
                if self.resume_manager:
                    self.resume_manager.mark_completed(chat_id, msg.msg_id, msg.text or "")
            except Exception:
                pass
            return

        # 4. Immediate Real-Time Context Recording (Unblocked)
        # Resume re-dispatch passes record=False: the message is already the buffer's last entry.
        is_bot = getattr(msg, "is_bot_relay", False) or bool(getattr(msg, "from_user", {}).get("is_bot", False))
        relay_bot_username = msg.from_user.get("username", "") if is_bot else ""
        if record:
            self.context_mgr.record_message(
                chat_id=chat_id,
                sender_name=msg.sender_name,
                text=msg.text,
                msg_id=msg.msg_id,
                reply_preview=msg.reply_preview,
                attachments=msg.attachments,
                is_bot_reply=is_bot,
                bot_username=relay_bot_username
            )

        # 5. Pattern command fast path: regex-matched device control bypasses LLM routing entirely.
        #    Runs in both group and private chats — triggered or untriggered.
        if not is_bot and self._pattern_commands and not getattr(msg, "reply_to_bot_username", ""):
            _fast = clean_query or (msg.text or "").strip()
            if _fast and not _fast.startswith("/"):
                matched = self.pattern_executor.match(_fast)
                if matched:
                    pc, raw = matched
                    asyncio.create_task(
                        self.pattern_executor.execute(chat_id, pc, raw, reply_to_msg_id=msg.msg_id, chat_type=chat_type)
                    )
                    return

        # 6. Untriggered messages complete here (already captured in context buffer)
        if not msg.is_triggered:
            # Source-level filter: if message is directed at another bot or user (via @mention, reply, or slash command),
            # never allow it into autonomous routing pipeline!
            if getattr(msg, "reply_to_bot_username", ""):
                return
            raw_text = (msg.text or "").strip()
            if raw_text.startswith("/"):
                return
            # Telegram usernames are ASCII-only, 5-32 chars, starting with a letter.
            # A bare \w+ would also match CJK particles after '@' (e.g. '不用@呀'),
            # silently dropping legit messages from autonomous routing.
            if re.search(r"@[a-zA-Z][a-zA-Z0-9_]{4,}(?!\.\w)|<@[!&]?\w+>", raw_text):
                return

            # Autonomous routing: local preemption check + single-arbiter evaluation
            au = getattr(self, "autonomous", None)
            if au is not None and au.cfg.enabled and not is_bot:
                au.on_human_message(msg)
                if au.is_arbiter:
                    asyncio.create_task(au.evaluate_and_publish(msg))
            return

        # 7. Enqueue triggered message for latest-driven queue draining execution
        if msg.msg_id:
            self._triggered_msg_ids.append(str(msg.msg_id))

        if chat_id not in self.chat_queues:
            self.chat_queues[chat_id] = asyncio.Queue()

        self.chat_queues[chat_id].put_nowait((msg, clean_query, cmd))

        worker_task = self.chat_tasks.get(chat_id)
        if (worker_task is None or worker_task.done()) and not self._resume_workers_held():
            self.chat_tasks[chat_id] = asyncio.create_task(self._process_chat_queue(chat_id))

    def _build_routing_context(self, chat_id: Any, exclude_msg_id: Any, window: int) -> str:
        """Recent messages (human + bot) for the routing classifier.

        Bot messages are included with a [Bot <name>] prefix so the model
        can see the full conversation flow — essential for detecting
        replies to bot questions (e.g. '方案一吧' answering a bot's proposal).

        Entries are flattened to single lines (bot replies often contain
        newlines; multi-line entries would blur who-said-what boundaries),
        and bot entries keep up to 2000 chars: a bot's questions, advice
        and options usually live deep inside long replies, and truncating
        them at 120 chars hides the very anchors follow-up detection needs.
        Human entries keep the short 120-char form (chitchat is short and
        cheap; long human instructions are rare).

        If an immediate task is still in flight (dispatched, reply not yet
        landed), a synthetic [Bot ...] marker line is appended so the
        classifier knows the sender's task is being processed.
        """
        try:
            buf = self.context_mgr.get_buffer(chat_id)
            lines = []
            for entry in reversed(buf):
                if len(lines) >= max(window, 1):
                    break
                if entry.get("msg_id") == exclude_msg_id:
                    continue
                text = (entry.get("text") or "").strip()
                if not text:
                    continue
                # Flatten: one entry = one context line (newlines -> spaces)
                text = text.replace("\r", " ").replace("\n", " ")
                limit = 2000 if entry.get("is_bot") else 120
                text = text[:limit]
                sender = entry.get("sender", "?")
                if entry.get("is_bot"):
                    lines.append(f"[Bot {sender}]: {text}")
                else:
                    lines.append(f"[{sender}]: {text}")
            ordered = list(reversed(lines))
            au = getattr(self, "autonomous", None)
            if au is not None:
                marker = au.inflight_marker(chat_id, buf)
                if marker:
                    ordered.append(marker)
            return "\n".join(ordered)
        except Exception as e:
            logger.warning(f"[ROUTING] context build error: {e}")
            return ""

    async def _dispatch_autonomous(self, decision: Dict[str, Any]) -> None:
        """Delivers an autonomous decision targeting THIS bot into the normal queue.

        Reuses the full triggered pipeline (session, context, adapter, reply
        anchoring, file delivery, relay sync). Queue backlog guard prevents
        autonomous tasks from starving scheduled jobs (e.g. morning brief).
        """
        au = getattr(self, "autonomous", None)
        if au is None:
            return
        chat_id = decision.get("chat_id")
        msg_id = decision.get("msg_id")
        if msg_id and str(msg_id) in self._triggered_msg_ids:
            logger.info(
                f"[ROUTING] Dropping duplicate autonomous dispatch for chat {chat_id}, "
                f"msg_id {msg_id} (already triggered/handled)"
            )
            return
        if msg_id:
            self._triggered_msg_ids.append(str(msg_id))

        if decision.get("is_resume"):
            # Every landing resume candidate refreshes the settle window so the
            # whole burst drains in one coalesced batch once it goes quiet.
            self._extend_resume_hold()
        else:
            q = self.chat_queues.get(chat_id)
            if q is not None and au is not None and hasattr(au, "cfg") and q.qsize() >= au.cfg.max_queue_backlog:
                logger.warning(
                    f"[ROUTING] Chat {chat_id} queue busy; autonomous task dropped (anti-starvation)."
                )
                return
        inbound = InboundMessage(
            chat_id=chat_id,
            chat_type=decision.get("chat_type", "group"),
            msg_id=decision.get("msg_id"),
            sender_name=decision.get("sender", ""),
            from_user={"id": 0, "first_name": decision.get("sender", ""), "username": "", "is_bot": False},
            text=decision.get("text", ""),
            reply_to_msg_id=None,
            reply_preview="",
            is_triggered=True,  # re-enters the normal triggered pipeline
            attachments=[],
            reply_attachments=[],
            is_bot_relay=False,
            hop_count=0,
        )
        if chat_id not in self.chat_queues:
            self.chat_queues[chat_id] = asyncio.Queue()
        cmd, _, _ = parse_bot_command(inbound.text, self.config.bot_username)
        self.chat_queues[chat_id].put_nowait((inbound, inbound.text, cmd))
        worker_task = self.chat_tasks.get(chat_id)
        if (worker_task is None or worker_task.done()) and not self._resume_workers_held():
            self.chat_tasks[chat_id] = asyncio.create_task(self._process_chat_queue(chat_id))

    async def _process_chat_queue(self, chat_id: Any) -> None:
        queue = self.chat_queues.get(chat_id)
        if not queue:
            return

        while True:
            if queue.empty():
                break

            items = []
            while not queue.empty():
                try:
                    items.append(queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if not items:
                break

            try:
                # 1. Reset command takes precedence over everything in batch
                reset_idx = next((i for i, it in enumerate(items) if it[2] in ("clear", "new", "reset")), -1)
                if reset_idx != -1:
                    if reset_idx > 0:
                        logger.info(f"Discarding {reset_idx} pre-reset queued items in chat {chat_id} due to reset command")
                    reset_msg, reset_query, reset_cmd = items[reset_idx]
                    await self._handle_triggered_message(reset_msg, reset_query, reset_cmd, coalesced_items=[])
                    for it in items[reset_idx + 1:]:
                        queue.put_nowait(it)
                else:
                    # 2. Separate slash commands from ordinary conversational messages
                    first_cmd_idx = next((i for i, it in enumerate(items) if it[2] is not None), -1)
                    if first_cmd_idx == 0:
                        # Leading item is a slash command (e.g. /backup, /status): execute standalone
                        cmd_msg, cmd_query, cmd_name = items[0]
                        await self._handle_triggered_message(cmd_msg, cmd_query, cmd_name, coalesced_items=[])
                        for it in items[1:]:
                            queue.put_nowait(it)
                    elif first_cmd_idx > 0:
                        # Leading items are ordinary messages, followed by a command: coalesce ordinary only
                        normal_items = items[:first_cmd_idx]
                        if len(normal_items) == 1:
                            msg, clean_query, cmd = normal_items[0]
                            await self._handle_triggered_message(msg, clean_query, cmd, coalesced_items=[])
                        else:
                            latest_msg, latest_clean_query, latest_cmd = normal_items[-1]
                            coalesced = normal_items[:-1]
                            logger.info(
                                f"Coalescing {len(normal_items)} triggered messages in chat {chat_id}. "
                                f"Latest query from {latest_msg.sender_name}: '{latest_clean_query[:50]}...'"
                            )
                            await self._handle_triggered_message(
                                latest_msg,
                                latest_clean_query,
                                latest_cmd,
                                coalesced_items=coalesced
                            )
                        for it in items[first_cmd_idx:]:
                            queue.put_nowait(it)
                    elif len(items) == 1:
                        msg, clean_query, cmd = items[0]
                        await self._handle_triggered_message(msg, clean_query, cmd, coalesced_items=[])
                    else:
                        # All items are ordinary messages: coalesce all
                        latest_msg, latest_clean_query, latest_cmd = items[-1]
                        coalesced = items[:-1]
                        logger.info(
                            f"Coalescing {len(items)} triggered messages in chat {chat_id}. "
                            f"Latest query from {latest_msg.sender_name}: '{latest_clean_query[:50]}...'"
                        )
                        await self._handle_triggered_message(
                            latest_msg,
                            latest_clean_query,
                            latest_cmd,
                            coalesced_items=coalesced
                        )
            except Exception as e:
                logger.error(f"Error processing triggered message in chat {chat_id}: {e}", exc_info=True)
            finally:
                for _ in items:
                    try:
                        queue.task_done()
                    except ValueError:
                        pass

    async def _handle_triggered_message(
        self,
        msg: InboundMessage,
        clean_query: str,
        cmd: Optional[str],
        coalesced_items: Optional[List[Tuple[InboundMessage, str, Optional[str]]]] = None
    ) -> None:
        chat_id = msg.chat_id
        is_group = msg.chat_type in ("group", "supergroup")
        session = self.context_mgr.get_session(chat_id)
        cid = session.get("conversation_id")

        # 1. Slash command routing (returns True if handled)
        if await self._route_slash_command(msg, clean_query, cmd):
            return

        # 2. Build agent prompt from attachments, coalesced items, and context
        full_prompt, active_attachments, user_query = self._build_agent_prompt(
            msg, clean_query, is_group, session, cid, coalesced_items
        )

        # 3. Invoke agent and deliver response
        await self._invoke_agent_and_deliver(
            msg, full_prompt, active_attachments, session, cid, coalesced_items=coalesced_items
        )

    async def _route_slash_command(
        self,
        msg: InboundMessage,
        clean_query: str,
        cmd: Optional[str]
    ) -> bool:
        """Routes built-in and custom slash commands. Returns True if handled."""
        chat_id = msg.chat_id
        is_group = msg.chat_type in ("group", "supergroup")
        session = self.context_mgr.get_session(chat_id)
        cid = session.get("conversation_id")

        _, target_bot, _ = parse_bot_command(msg.text or "", self.config.bot_username)
        is_explicitly_targeted = (
            (target_bot is not None and target_bot.lower() == self.config.bot_username.lower())
            or (f"@{self.config.bot_username}".lower() in (msg.text or "").lower())
            or (msg.chat_type == "private")
        )

        async def _reply_builtin(text: str) -> None:
            sent_id = await self.channel.send_reply(chat_id, text, reply_to_msg_id=msg.msg_id)
            clean_sent_id = sent_id if isinstance(sent_id, (int, str)) else 0
            try:
                self.context_mgr.record_message(
                    chat_id=chat_id,
                    sender_name=f"{self.config.bot_name} (@{self.config.bot_username})",
                    text=text,
                    msg_id=clean_sent_id,
                    is_bot_reply=True,
                    bot_username=self.config.bot_username,
                    reply_to_msg_id=msg.msg_id or 0
                )
                if self.resume_manager:
                    self.resume_manager.mark_completed(chat_id, msg.msg_id, msg.text or "")
            except Exception as e:
                logger.warning(f"[COMMAND] Failed to record built-in command reply: {e}")

        if cmd in ("clear", "new", "reset"):
            self.context_mgr.reset_session(chat_id)
            self.adapter.terminate(chat_id)
            await _reply_builtin("🧹 Session reset. Started fresh conversation context.")
            return True
        elif cmd == "status":
            buf = self.context_mgr.get_buffer(chat_id)
            cid_display = f"`{cid[:8]}...{cid[-6:]}` ({session.get('turns', 0)} turns)" if cid else "Fresh / Idle"
            auth_str = "🛡️ Active Allowlist" if self.gatekeeper.is_whitelist_active() else ("⚠️ Open Access" if self.config.allow_open_access else "🔒 Safe Lockdown")
            status_text = (
                f"🤖 **GroupConnect Gateway Status**\n\n"
                f"- **Platform**: `{self.config.platform.title()}` (`@{self.config.bot_username}`)\n"
                f"- **Engine**: `{self.config.engine_type.title()}`\n"
                f"- **Chat Type**: `{'Group Chat' if is_group else 'Private Direct'}`\n"
                f"- **Security**: `{auth_str}`\n"
                f"- **Session**: {cid_display}\n"
                f"- **Sliding Buffer**: `{len(buf)}/{self.config.max_history_len}`\n"
                f"- **Workspace**: `{self.config.workspace_dir}`\n"
                f"- **Service State**: `Active & Running`"
            )
            await _reply_builtin(status_text)
            return True
        elif cmd in ("help", "start"):
            custom_cmd_lines = ""
            if self.config.custom_commands:
                custom_cmd_lines = "\n" + "\n".join(
                    f"• `/{c.get('command')}` - {c.get('description', '')}"
                    for c in self.config.custom_commands if c.get("command")
                )
            help_text = (
                f"👋 Hello! I am **GroupConnect** (`@{self.config.bot_username}`).\n\n"
                f"🎯 **Key Features**:\n"
                f"1. **Silent Group Context**: I track recent discussion in the background and catch up instantly when tagged.\n"
                f"2. **Multimodal Inbox**: Photos, voice notes, and documents are automatically downloaded and parsed.\n"
                f"3. **Persistent Session**: Fluid multi-turn dialogue with continuous memory.\n\n"
                f"🛠 **Commands**:\n"
                f"• `/status` - View current session, engine, and buffer status\n"
                f"• `/stop` - Immediately terminate in-flight generation\n"
                f"• `/new` or `/clear` - Reset context and start fresh\n"
                f"• `/help` - Show this guide{custom_cmd_lines}"
            )
            await _reply_builtin(help_text)
            return True
        elif cmd in self._custom_commands_map:
            cmd_cfg = self._custom_commands_map[cmd]
            clean_cmd_name = str(cmd_cfg.get("command", "")).strip().lower().lstrip("/")
            is_arbiter = (self.autonomous.is_arbiter if getattr(self, "autonomous", None) else True)

            if cmd_cfg.get("arbiter_only_on_broadcast", False):
                if not is_explicitly_targeted and not is_arbiter:
                    return True

            should_lock = cmd_cfg.get("lock", False)
            if should_lock:
                if not self.command_dispatcher.acquire_lock(clean_cmd_name):
                    await self.channel.send_reply(
                        chat_id,
                        f"⏳ 指令 `/{clean_cmd_name}` 正在执行中，请勿重复触发，稍后会自动汇报结果。",
                        reply_to_msg_id=msg.msg_id
                    )
                    return True

            cmd_from_raw, _, raw_args = parse_bot_command(msg.text or "", self.config.bot_username)
            effective_args = raw_args if cmd_from_raw else clean_query
            asyncio.create_task(
                self._run_slash_command(
                    chat_id, cmd_cfg, effective_args, should_lock, clean_cmd_name,
                    reply_to_msg_id=msg.msg_id, chat_type=msg.chat_type, raw_msg_text=msg.text or ""
                )
            )
            return True

        return False

    def _build_agent_prompt(
        self,
        msg: InboundMessage,
        clean_query: str,
        is_group: bool,
        session: Dict[str, Any],
        cid: Optional[str],
        coalesced_items: Optional[List[Tuple[InboundMessage, str, Optional[str]]]] = None
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        """Builds the full agent prompt from attachments, coalesced items, and conversation context.
        Returns (full_prompt, active_attachments, user_query)."""
        chat_id = msg.chat_id

        # Collect attachments
        active_attachments = list(msg.attachments)
        for att in msg.reply_attachments:
            if not any(a.get("path") == att.get("path") for a in active_attachments):
                active_attachments.append(att)

        if coalesced_items:
            for c_msg, _, _ in coalesced_items:
                for att in list(c_msg.attachments) + list(c_msg.reply_attachments):
                    if not any(a.get("path") == att.get("path") for a in active_attachments):
                        active_attachments.append(att)

        attachments_section = ""
        if active_attachments:
            att_lines = [f"- [{a['type']}] File path: {a['path']} (Name: {a.get('name', 'file')})" for a in active_attachments]
            attachments_section = (
                "\n【Attached Media Files】\n"
                + "\n".join(att_lines) + "\n"
                + "👉 Note: Use tools to view or read files at these absolute paths if visual inspection or parsing is needed.\n"
            )

        user_query = clean_query if clean_query else msg.text
        if not user_query or user_query.startswith("[Photo") or user_query.startswith("[Voice"):
            if active_attachments:
                user_query = "Please inspect and analyze the attached media file(s) and provide a detailed structured response."

        # Coalesced items already appear in the sliding-window context (group
        # and private chats alike — the window is now built for both) — mark
        # them inline with ⏳ instead of duplicating them in a separate
        # prompt section.
        coalesce_section = ""
        pending_msg_ids = None
        if coalesced_items:
            pending_msg_ids = {c_msg.msg_id for c_msg, _, _ in coalesced_items}
            coalesce_section = (
                "\n（标注 ⏳ 的消息为排队期间接收到的连续补充要求，"
                "请一并综合响应，以最新【Current Query】为最终准则）\n"
            )

        # Soul prompt (session initialization only)
        soul_section = ""
        if cid is None:
            soul_section = _load_soul(self.config)

        # Unified context building for group AND private chats: the sliding
        # window is the cold-start safety net (the runtime conversation can
        # expire after idle or be lost across restarts).  First turn / expired
        # session → full window; subsequent turns → incremental slice since
        # the last processed input (the runtime conversation holds the rest).
        if is_group:
            window_title = "【Recent Group Discussion Context (Sliding Window)】"
            inc_title = "【New Group Messages Since Last Response】"
            closing = "Please address the current query taking the group discussion background into account."
        else:
            window_title = "【Recent Conversation Context (Sliding Window)】"
            inc_title = "【New Messages Since Last Response】"
            closing = "Please address the current query taking the recent conversation background into account."

        if cid is None:
            context_str = self.context_mgr.build_group_context(
                chat_id,
                since_msg_id=0,
                exclude_msg_id=msg.msg_id,
                pending_msg_ids=pending_msg_ids
            ) or "(No prior history)"
            full_prompt = (
                f"【Role Context】\n"
                f"You are @{self.config.bot_username} ({self.config.bot_name}) in workspace: {self.config.workspace_dir}\n"
                f"{soul_section}"
                f"{attachments_section}\n"
                f"{window_title}\n"
                f"{context_str}\n"
                f"{coalesce_section}"
                f"【Current Query】\n"
                f"Sender: {msg.sender_name}\n"
                f"Content: {user_query}\n\n"
                f"{closing}"
            )
        else:
            last_input_id = session.get("last_input_msg_id", 0)
            inc_context = self.context_mgr.build_group_context(
                chat_id,
                since_msg_id=last_input_id,
                exclude_msg_id=msg.msg_id,
                skip_bot_username=self.config.bot_username,
                pending_msg_ids=pending_msg_ids
            )
            inc_section = f"\n{inc_title}\n{inc_context}\n" if inc_context else ""
            full_prompt = (
                f"【Role Context】\n"
                f"You are @{self.config.bot_username} ({self.config.bot_name})\n"
                f"{attachments_section}"
                f"{inc_section}"
                f"{coalesce_section}"
                f"【Current Query】\n"
                f"Sender: {msg.sender_name}\n"
                f"Content: {user_query}\n\n"
                f"Please continue the conversation naturally."
            )

        return full_prompt, active_attachments, user_query

    async def _invoke_agent_and_deliver(
        self,
        msg: InboundMessage,
        full_prompt: str,
        active_attachments: List[Dict[str, Any]],
        session: Dict[str, Any],
        cid: Optional[str],
        coalesced_items: Optional[List[Tuple[InboundMessage, str, Optional[str]]]] = None
    ) -> None:
        """Invokes the agent with typing heartbeat, then delivers the response."""
        chat_id = msg.chat_id

        # Update incremental context anchor
        session["last_input_msg_id"] = msg.msg_id

        # Typing heartbeat
        stop_typing = asyncio.Event()
        interval = max(self.config.typing_interval_secs, 1.0)

        async def typing_loop():
            while not stop_typing.is_set():
                await self.channel.send_typing_action(chat_id)
                try:
                    await asyncio.wait_for(stop_typing.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass

        typing_task = asyncio.create_task(typing_loop())

        try:
            reply_text, new_cid = await self.adapter.execute_turn(
                prompt=full_prompt,
                conversation_id=cid,
                chat_id=chat_id,
                attachments=active_attachments
            )
        finally:
            stop_typing.set()
            await typing_task

        if reply_text is None:
            if new_cid:
                session["conversation_id"] = new_cid
                session["last_active"] = time.time()
            return

        if new_cid:
            session["conversation_id"] = new_cid
            session["turns"] = session.get("turns", 0) + 1
            session["last_active"] = time.time()
        else:
            session["conversation_id"] = None

        sent_msg_id, clean_reply_text = await self.outbound_delivery.deliver(
            chat_id=chat_id,
            reply_text=reply_text,
            reply_to_msg_id=msg.msg_id,
            chat_type=msg.chat_type,
            hop_count=getattr(msg, "hop_count", 0)
        )
        if sent_msg_id:
            session["last_bot_msg_id"] = sent_msg_id
            try:
                self.resume_manager.mark_completed(msg.chat_id, msg.msg_id, msg.text or "")
                if coalesced_items:
                    for c_msg, _, _ in coalesced_items:
                        self.resume_manager.mark_completed(c_msg.chat_id, c_msg.msg_id, c_msg.text or "")
            except Exception:
                pass

        # Bot reply landed: proactively flush any pending wait_silence for this
        # chat so accumulated messages are processed immediately, without
        # waiting for the countdown to elapse.
        if sent_msg_id:
            au = getattr(self, "autonomous", None)
            if au is not None:
                au.flush_pending(chat_id)

    async def _run_slash_command(
        self,
        chat_id: Any,
        cmd_cfg: Dict[str, Any],
        args: str,
        should_lock: bool,
        cmd_name: str,
        reply_to_msg_id: Any = None,
        chat_type: str = "group",
        raw_msg_text: str = ""
    ) -> None:
        """Execute a slash command with lock release guaranteed by the caller."""
        try:
            await self.command_dispatcher.execute_command(
                chat_id, cmd_cfg, args, reply_to_msg_id=reply_to_msg_id, chat_type=chat_type
            )
        finally:
            if should_lock:
                self.command_dispatcher.release_lock(cmd_name)
            if self.resume_manager and reply_to_msg_id:
                try:
                    self.resume_manager.mark_completed(chat_id, reply_to_msg_id, raw_msg_text)
                except Exception:
                    pass
