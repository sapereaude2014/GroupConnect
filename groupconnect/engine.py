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
from typing import Any, Dict, List, Optional, Tuple

from groupconnect.adapters.base import BaseAgentAdapter, get_adapter_class
import groupconnect.adapters.antigravity
import groupconnect.adapters.claude_code
import groupconnect.adapters.codex
import groupconnect.adapters.opencode

try:
    import groupconnect.adapters.teleagent
except ImportError:
    pass  # TeleAgent adapter is optional (local-only, not in upstream)

from groupconnect.channels.base import BaseChannel, InboundMessage, get_channel_class
import groupconnect.channels.telegram
import groupconnect.channels.discord
import groupconnect.channels.slack
import groupconnect.channels.feishu
import groupconnect.channels.wecom

from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig
from groupconnect.core.context import ContextManager
from groupconnect.core.gatekeeper import Gatekeeper
from groupconnect.core.relay import CrossBotRelay
from groupconnect.core.telegraph import process_outbound_text
from groupconnect.routing import AutonomousController, AutonomousConfig

logger = logging.getLogger("groupconnect.engine")


def _load_soul(workspace_dir: str, bot_username: str) -> str:
    """Load specific bot soul from .agents/souls/{bot_username}.md if present."""
    soul_path = os.path.join(workspace_dir, ".agents", "souls", f"{bot_username}.md")
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


SENDFILE_TAG_PATTERN = re.compile(
    r"[【\[](?:send_?file|file|send_document|发文件):\s*([^\s`\"'<>|\]】]+)(?:\s*\|\s*([^\]】]+))?[】\]]",
    re.IGNORECASE
)


def _extract_outbound_files(reply_text: str, workspace_dir: str) -> List[Tuple[str, Optional[str]]]:
    """
    Extract outbound file attachments from bot reply text.
    Only explicit send tags are recognized:
      【SendFile: /path/to/file】
      【SendFile: /path/to/file | caption】
      [SendFile: /path/to/file]
      [SendFile: /path/to/file | caption]
    Markdown file links ([doc](file:///...)) and bare file:// URIs are NOT extracted
    to prevent accidental spamming of referenced source code or documentation files.
    Returns a list of (file_path, caption) tuples.
    """
    if not reply_text:
        return []

    found = []
    seen = set()

    for m in SENDFILE_TAG_PATTERN.finditer(reply_text):
        raw_path = m.group(1).strip().strip("`'\"")
        caption = m.group(2).strip() if m.group(2) else None
        path = raw_path if os.path.isabs(raw_path) else os.path.join(workspace_dir, raw_path)
        if os.path.isfile(path) and path not in seen:
            seen.add(path)
            found.append((path, caption))

    return found


def _strip_sendfile_tags(text: str) -> str:
    """
    Remove outbound send tags from reply text so internal markup doesn't appear in chat.
    """
    if not text:
        return ""
    cleaned = SENDFILE_TAG_PATTERN.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


class GroupConnectEngine:
    def __init__(self, config: GatewayConfig):
        self.config = config

        # 1. Context & Gatekeeper (Secure-by-Default with Configurable DM Access)
        self.context_mgr = ContextManager(
            max_history_len=config.max_history_len,
            chat_logs_dir=config.chat_logs_dir,
            idle_timeout_mins=config.session_idle_timeout_mins,
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
        self._triggered_msg_ids: collections.deque = collections.deque(maxlen=200)
        self._backup_running: bool = False
        self.is_running = False

        # 5. Autonomous Routing (免@自主唤醒: single-arbiter + symmetric observers)
        self.autonomous: Optional[AutonomousController] = None
        acfg_path = getattr(config, "autonomous_config_path", "")
        if not acfg_path:
            from groupconnect.routing.router import find_default_config_path
            candidate = find_default_config_path()
            if os.path.exists(candidate):
                acfg_path = candidate
        if acfg_path and os.path.exists(acfg_path):
            try:
                acfg = AutonomousConfig(acfg_path)
                if acfg.enabled:
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
                timeout_secs=self.config.timeout_secs,
                idle_timeout_mins=self.config.session_idle_timeout_mins
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
                idle_timeout_mins=self.config.session_idle_timeout_mins,
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
        self.is_running = True
        if not self.gatekeeper.is_whitelist_active() and not self.config.allow_open_access:
            logger.warning(
                "🔒 [SECURITY ALERT] No allowlist configured. Running in Safe Lockdown Mode. "
                "All incoming messages will be rejected until allowed_chat_ids, allowed_user_ids, "
                "or allowed_usernames are configured in config.json."
            )
        logger.info(f"Starting GroupConnect Gateway (Platform: {self.config.platform}, Engine: {self.config.engine_type})...")

        await self.relay.start()
        reaper_task = asyncio.create_task(self._reaper_loop())
        is_arbiter = (self.autonomous.is_arbiter if self.autonomous else True)
        backup_task = asyncio.create_task(self._backup_scheduler_loop()) if is_arbiter else None
        try:
            await self.channel.start()
        finally:
            reaper_task.cancel()
            if backup_task:
                backup_task.cancel()
            for task in self.chat_tasks.values():
                if not task.done():
                    task.cancel()
            await self.relay.stop()
            self.adapter.close()

    async def _reaper_loop(self) -> None:
        while self.is_running:
            try:
                await asyncio.sleep(300)
                if hasattr(self.adapter, "reap_idle_workers"):
                    self.adapter.reap_idle_workers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in reaper loop: {e}")

    async def _backup_scheduler_loop(self) -> None:
        """Weekly scheduled background backup to Samsung T7 (runs Sundays at 04:xx AM)."""
        last_run_day = ""
        while self.is_running:
            try:
                await asyncio.sleep(1800)  # check every 30 mins
                now = datetime.now()
                # Run weekly on Sunday (weekday 6) at 04:xx AM
                if now.weekday() == 6 and now.hour == 4:
                    today_str = now.strftime("%Y%m%d")
                    if today_str != last_run_day:
                        last_run_day = today_str
                        backup_script = os.path.expanduser("~/.local/bin/guagua-backup")
                        if os.path.isfile(backup_script):
                            logger.info("[BACKUP] Triggering scheduled Sunday weekly backup...")
                            proc = await asyncio.create_subprocess_exec(
                                backup_script,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE
                            )
                            stdout, stderr = await proc.communicate()
                            if proc.returncode != 0:
                                err_tail = (stderr or b"").decode("utf-8", "replace").strip()[-300:]
                                logger.error(f"[BACKUP] Weekly backup FAILED (rc={proc.returncode}): {err_tail}")
                                await self._notify_backup_failure(proc.returncode, err_tail)
                        else:
                            logger.error(f"[BACKUP] Backup script missing: {backup_script}")
                            await self._notify_backup_failure(-1, f"备份脚本不存在: {backup_script}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Error in backup scheduler loop: {e}")

    async def _notify_backup_failure(self, returncode: int, err_tail: str) -> None:
        """Alert the family group when the weekly backup fails (never fail silently)."""
        try:
            chat_ids = list(self.config.allowed_chat_ids) if self.config.allowed_chat_ids else []
            if not chat_ids:
                return
            text = (
                f"⚠️ 周日凌晨自动备份失败 (exit={returncode})，请检查 T7 硬盘是否挂载/磁盘空间。"
                f"\n错误摘要: {err_tail or '无输出'}"
            )
            for cid in chat_ids:
                await self.channel.send_reply(cid, text)
        except Exception as e:
            logger.error(f"[BACKUP] Failed to deliver backup-failure alert to group: {e}")

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
        if self.gatekeeper.is_whitelist_active():
            try:
                cid_int = int(chat_id)
                if self.config.allowed_chat_ids and cid_int not in self.config.allowed_chat_ids:
                    return
            except (ValueError, TypeError):
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
            reply_to_msg_id=None,  # bot-relay messages are invisible on Telegram, reply-to would 400
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

    async def on_inbound_message(self, msg: InboundMessage) -> None:
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
            await self.channel.send_reply(chat_id, "⏹ Task execution was stopped.", reply_to_msg_id=msg.msg_id)
            self.context_mgr.record_message(
                chat_id=chat_id,
                sender_name=msg.sender_name,
                text=msg.text,
                msg_id=msg.msg_id,
                attachments=[]
            )
            return

        # 4. Immediate Real-Time Context Recording (Unblocked)
        is_bot = getattr(msg, "is_bot_relay", False) or bool(getattr(msg, "from_user", {}).get("is_bot", False))
        relay_bot_username = msg.from_user.get("username", "") if is_bot else ""
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

        # 5. Untriggered messages complete here (already captured in context buffer)
        if not msg.is_triggered:
            # Source-level filter: if message is directed to another bot (via @bot, reply, or slash command),
            # never allow it into autonomous routing pipeline!
            if getattr(msg, "reply_to_bot_username", ""):
                return
            raw_text = (msg.text or "").strip()
            if raw_text.startswith("/"):
                return
            if re.search(r"@\w+bot\b", raw_text, re.IGNORECASE):
                return

            # Autonomous routing: local preemption check + single-arbiter evaluation
            au = getattr(self, "autonomous", None)
            if au is not None and au.cfg.enabled and not is_bot:
                au.on_human_message(msg)
                if au.is_arbiter:
                    asyncio.create_task(au.evaluate_and_publish(msg))
            return

        # 6. Enqueue triggered message for latest-driven queue draining execution
        if msg.msg_id:
            self._triggered_msg_ids.append(str(msg.msg_id))

        if chat_id not in self.chat_queues:
            self.chat_queues[chat_id] = asyncio.Queue()

        self.chat_queues[chat_id].put_nowait((msg, clean_query, cmd))

        worker_task = self.chat_tasks.get(chat_id)
        if worker_task is None or worker_task.done():
            self.chat_tasks[chat_id] = asyncio.create_task(self._process_chat_queue(chat_id))

    def _build_routing_context(self, chat_id: Any, exclude_msg_id: Any, window: int) -> str:
        """Recent messages (human + bot) for the routing classifier.

        Bot messages are included with a [Bot <name>] prefix so the model
        can see the full conversation flow — essential for detecting
        replies to bot questions (e.g. '方案一吧' answering a bot's proposal).
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
                sender = entry.get("sender", "?")
                if entry.get("is_bot"):
                    lines.append(f"[Bot {sender}]: {text[:120]}")
                else:
                    lines.append(f"[{sender}]: {text[:120]}")
            return "\n".join(reversed(lines))
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

        q = self.chat_queues.get(chat_id)
        if q is not None and q.qsize() >= au.cfg.max_queue_backlog:
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
        if worker_task is None or worker_task.done():
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
                # Handle reset/clear command if present in batch
                reset_idx = next((i for i, it in enumerate(items) if it[2] in ("clear", "new", "reset")), -1)
                if reset_idx != -1:
                    reset_msg, reset_query, reset_cmd = items[reset_idx]
                    await self._handle_triggered_message(reset_msg, reset_query, reset_cmd, coalesced_items=[])
                    remaining = items[reset_idx + 1:]
                    for it in remaining:
                        queue.put_nowait(it)
                elif len(items) == 1:
                    msg, clean_query, cmd = items[0]
                    await self._handle_triggered_message(msg, clean_query, cmd, coalesced_items=[])
                else:
                    # Latest-driven coalescing: latest message is the primary target
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

        # Determine whether command was explicitly targeted at this bot
        _, target_bot, _ = parse_bot_command(msg.text or "", self.config.bot_username)
        is_explicitly_targeted = (
            (target_bot is not None and target_bot.lower() == self.config.bot_username.lower())
            or (f"@{self.config.bot_username}".lower() in (msg.text or "").lower())
            or (msg.chat_type == "private")
        )

        # Built-in Slash Commands
        if cmd in ("clear", "new", "reset"):
            self.context_mgr.reset_session(chat_id)
            self.adapter.terminate(chat_id)
            await self.channel.send_reply(chat_id, "🧹 Session reset. Started fresh conversation context.", reply_to_msg_id=msg.msg_id)
            return
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
            await self.channel.send_reply(chat_id, status_text, reply_to_msg_id=msg.msg_id)
            return
        elif cmd in ("help", "start"):
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
                f"• `/help` - Show this guide"
            )
            await self.channel.send_reply(chat_id, help_text, reply_to_msg_id=msg.msg_id)
            return
        elif cmd in ("login", "vnc"):
            if self.config.engine_type not in ("teleagent", "tele-worker", "teleworker"):
                if is_explicitly_targeted:
                    await self.channel.send_reply(
                        chat_id,
                        "ℹ️ TeleAgent 网页/VNC 登录仅由 @guaguahome_bot 负责，请向 @guaguahome_bot 发送 `/login` 指令。",
                        reply_to_msg_id=msg.msg_id
                    )
                return
            script_path = os.path.expanduser("~/.local/share/TeleAgent/scripts/autologin.py")
            if os.path.isfile(script_path):
                force = "force" in (clean_query or "").lower()
                asyncio.create_task(
                    self._run_autologin_command(chat_id, script_path, force=force, reply_to_msg_id=msg.msg_id)
                )
            else:
                await self.channel.send_reply(chat_id, f"❌ 未找到登录脚本: {script_path}", reply_to_msg_id=msg.msg_id)
            return
        elif cmd in ("backup", "sync_backup"):
            is_arbiter = (self.autonomous.is_arbiter if getattr(self, "autonomous", None) else True)
            if not is_explicitly_targeted and not is_arbiter:
                return

            if getattr(self, "_backup_running", False):
                await self.channel.send_reply(
                    chat_id,
                    "⏳ 当前已有备份任务正在执行中，请勿重复触发，稍后会自动汇报结果。",
                    reply_to_msg_id=msg.msg_id
                )
                return

            await self.channel.send_reply(
                chat_id,
                "📦 [管家备份] 收到小马哥指令！正在执行全量资产备份至三星 T7 固态盘，请稍候...",
                reply_to_msg_id=msg.msg_id
            )
            backup_script = os.path.expanduser("~/.local/bin/guagua-backup")
            if os.path.isfile(backup_script):
                self._backup_running = True
                asyncio.create_task(
                    self._run_backup_command(chat_id, backup_script, reply_to_msg_id=msg.msg_id)
                )
            else:
                await self.channel.send_reply(chat_id, f"❌ 未找到备份脚本: {backup_script}", reply_to_msg_id=msg.msg_id)
            return

        # Prepare Attachments Prompt Section
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

        coalesce_section = ""
        if coalesced_items:
            coalesce_lines = []
            for c_msg, c_query, _ in coalesced_items:
                c_text = c_query if c_query else c_msg.text
                coalesce_lines.append(f"- [{c_msg.sender_name}]: {c_text}")
            coalesce_section = (
                "\n【Coalesced Pending Instructions / 排队期间接收到的连续补充要求】\n"
                "（重要提示：在处理上一任务期间，用户在群内连续发送了以下指令。请结合这些补充要求，以最新的【Current Query】为最终准则一并综合响应）：\n"
                + "\n".join(coalesce_lines) + "\n"
            )

        # Prepare Soul Prompt Section (Session Initialization only)
        soul_section = ""
        if cid is None:
            soul_section = _load_soul(self.config.workspace_dir, self.config.bot_username)

        # Build Full Prompt with Context
        if not is_group:
            if cid is None:
                full_prompt = (
                    f"【Role Context】\n"
                    f"You are @{self.config.bot_username} ({self.config.bot_name}) in workspace: {self.config.workspace_dir}\n"
                    f"{soul_section}"
                    f"{attachments_section}\n"
                    f"{coalesce_section}"
                    f"【Sender】: {msg.sender_name}\n"
                    f"【Query】: {user_query}\n\n"
                    f"Please provide a helpful, accurate, and structured response."
                )
            else:
                full_prompt = (
                    f"【Role Context】\n"
                    f"You are @{self.config.bot_username} ({self.config.bot_name})\n"
                    f"{attachments_section}\n"
                    f"{coalesce_section}"
                    f"【Sender】: {msg.sender_name}\n"
                    f"【Query】: {user_query}\n\n"
                    f"Please continue the conversation naturally."
                )
        else:
            if cid is None:
                context_str = self.context_mgr.build_group_context(
                    chat_id,
                    since_msg_id=0,
                    exclude_msg_id=msg.msg_id
                ) or "(No prior history)"
                full_prompt = (
                    f"【Role Context】\n"
                    f"You are @{self.config.bot_username} ({self.config.bot_name}) in workspace: {self.config.workspace_dir}\n"
                    f"{soul_section}"
                    f"{attachments_section}\n"
                    f"【Recent Group Discussion Context (Sliding Window)】\n"
                    f"{context_str}\n"
                    f"{coalesce_section}\n"
                    f"【Current Query】\n"
                    f"Sender: {msg.sender_name}\n"
                    f"Content: {user_query}\n\n"
                    f"Please address the current query taking the group discussion background into account."
                )
            else:
                last_input_id = session.get("last_input_msg_id", 0)
                inc_context = self.context_mgr.build_group_context(
                    chat_id,
                    since_msg_id=last_input_id,
                    exclude_msg_id=msg.msg_id,
                    skip_bot_username=self.config.bot_username
                )
                inc_section = f"\n【New Group Messages Since Last Response】\n{inc_context}\n" if inc_context else ""
                full_prompt = (
                    f"【Role Context】\n"
                    f"You are @{self.config.bot_username} ({self.config.bot_name})\n"
                    f"{attachments_section}"
                    f"{inc_section}"
                    f"{coalesce_section}\n"
                    f"【Current Query】\n"
                    f"Sender: {msg.sender_name}\n"
                    f"Content: {user_query}\n\n"
                    f"Please continue the conversation naturally."
                )

        # Update incremental context anchor to current input message,
        # so messages arriving during processing are included next turn.
        session["last_input_msg_id"] = msg.msg_id

        # Typing Heartbeat Loop
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
            # Request was cancelled via /stop
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

        # Outbound Text Processing (Telegraph auto-publisher for long text / tables / explicit tags)
        processed_reply_text = reply_text
        try:
            processed_reply_text = await process_outbound_text(
                reply_text=reply_text,
                threshold=self.config.auto_telegraph_threshold,
                author_name=self.config.telegraph_author_name
            )
        except Exception as e:
            logger.warning(f"Error in process_outbound_text: {e}")

        # Outbound Multimedia / File Delivery (searches raw reply_text)
        outbound_files = _extract_outbound_files(reply_text, self.config.workspace_dir)
        if outbound_files:
            processed_reply_text = _strip_sendfile_tags(processed_reply_text)

        sent_msg_id = None
        try:
            if processed_reply_text and processed_reply_text.strip():
                sent_msg_id = await self.channel.send_reply(chat_id, processed_reply_text, reply_to_msg_id=msg.msg_id)
                if sent_msg_id:
                    session["last_bot_msg_id"] = sent_msg_id
            elif not outbound_files:
                # No files and empty text: trigger default fallback message
                sent_msg_id = await self.channel.send_reply(chat_id, processed_reply_text, reply_to_msg_id=msg.msg_id)
                if sent_msg_id:
                    session["last_bot_msg_id"] = sent_msg_id
        except Exception as e:
            logger.error(f"Failed to deliver reply to chat {chat_id}: {e}")

        for file_path, file_caption in outbound_files:
            try:
                logger.info(f"Delivering outbound attachment: {file_path} (caption={file_caption}) to chat {chat_id}")
                await self.channel.send_file(
                    chat_id=chat_id,
                    file_path=file_path,
                    caption=file_caption,
                    reply_to_msg_id=sent_msg_id or msg.msg_id
                )
            except Exception as e:
                logger.error(f"Failed to deliver outbound attachment {file_path} to chat {chat_id}: {e}")

        self.context_mgr.record_message(
            chat_id=chat_id,
            sender_name=f"{self.config.bot_name} (@{self.config.bot_username})",
            text=processed_reply_text,
            msg_id=sent_msg_id,
            is_bot_reply=True,
            bot_username=self.config.bot_username
        )

        # Broadcast reply to local peer bots via CrossBotRelay
        if getattr(self, "relay", None):
            try:
                await self.relay.broadcast_reply(
                    chat_id=chat_id,
                    chat_type=msg.chat_type,
                    msg_id=sent_msg_id or 0,
                    text=processed_reply_text,
                    hop_count=getattr(msg, "hop_count", 0)
                )
            except Exception as e:
                logger.warning(f"Failed to broadcast reply via relay: {e}")

    async def _run_autologin_command(
        self, chat_id: Any, script_path: str, force: bool = False, reply_to_msg_id: Any = None
    ) -> None:
        try:
            logger.info(f"[LOGIN] Checking TeleAgent status for chat {chat_id}...")
            # 1. Quick status check
            check_proc = await asyncio.create_subprocess_exec(
                "python3", script_path, "--check-only",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await check_proc.communicate()
            if check_proc.returncode == 0 and not force:
                status_msg = (
                    "✅ [管家状态]\n"
                    "TeleAgent 核心引擎当前处于健康在线状态（ONLINE），会话健康在席，无需重复登录！\n\n"
                    "💡 如遇界面卡死或需强制重新呼出 VNC 控制台，请输入：`/login force`"
                )
                await self.channel.send_reply(chat_id, status_msg, reply_to_msg_id=reply_to_msg_id)
                return

            # 2. Needs login or force requested
            await self.channel.send_reply(
                chat_id,
                "🚀 [管家指令] 收到指令！正在准备 TeleAgent 登录环境并拉起 VNC 控制台...",
                reply_to_msg_id=reply_to_msg_id
            )
            cmd_args = ["python3", script_path, "--timeout", "600"]
            if force:
                cmd_args.append("--force")

            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode == 0:
                logger.info("[LOGIN] Autologin script completed successfully.")
            else:
                err_msg = stderr.decode(errors="ignore").strip()
                logger.warning(f"[LOGIN] Autologin exited with code {proc.returncode}: {err_msg}")
        except Exception as e:
            logger.error(f"[LOGIN] Failed to execute autologin script: {e}", exc_info=True)

    async def _run_backup_command(
        self, chat_id: Any, script_path: str, reply_to_msg_id: Any = None
    ) -> None:
        try:
            logger.info(f"[BACKUP] Executing backup script for chat {chat_id}...")
            start_ts = time.time()
            proc = await asyncio.create_subprocess_exec(
                script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            duration = max(1, int(time.time() - start_ts))
            if proc.returncode == 0:
                report = (
                    f"✅ [管家报告 · 备份完成]\n"
                    f"全量资产已成功备份至三星 T7 固态盘（耗时 {duration}s）！\n\n"
                    f"• 📁 **家庭档案**：已完成 1:1 实时增量镜像（`T7/mama_family_files`）\n"
                    f"• 🗜️ **核心配置**：已生成轻量快照单包（保留最新 3 份历史，自动轮转）\n"
                    f"• 💾 **存储状态**：三星 T7 局域网物理冷备在席"
                )
                await self.channel.send_reply(chat_id, report, reply_to_msg_id=reply_to_msg_id)
            else:
                err_msg = stderr.decode(errors="ignore").strip()
                await self.channel.send_reply(
                    chat_id, f"❌ [管家警报] 备份执行失败 (Exit {proc.returncode}): {err_msg}",
                    reply_to_msg_id=reply_to_msg_id
                )
        except Exception as e:
            logger.error(f"[BACKUP] Failed to execute backup script: {e}", exc_info=True)
        finally:
            self._backup_running = False
