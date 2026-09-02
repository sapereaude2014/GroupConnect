"""
Central Orchestrator Engine for GroupConnect.
Connects Channel, Agent Adapter, Context Manager, Gatekeeper, and Command Parser.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, Optional

from groupconnect.adapters.base import BaseAgentAdapter
from groupconnect.adapters.antigravity import AntigravityAdapter
from groupconnect.adapters.claude_code import ClaudeCodeAdapter
from groupconnect.adapters.codex import CodexAdapter
from groupconnect.adapters.opencode import OpenCodeAdapter
from groupconnect.channels.base import BaseChannel, InboundMessage
from groupconnect.channels.telegram import TelegramChannel
from groupconnect.core.command import parse_bot_command
from groupconnect.core.config import GatewayConfig
from groupconnect.core.context import ContextManager
from groupconnect.core.gatekeeper import Gatekeeper

logger = logging.getLogger("groupconnect.engine")


class GroupConnectEngine:
    def __init__(self, config: GatewayConfig):
        self.config = config

        # 1. Context & Gatekeeper
        self.context_mgr = ContextManager(
            max_history_len=config.max_history_len,
            chat_logs_dir=config.chat_logs_dir,
            idle_timeout_mins=config.session_idle_timeout_mins
        )
        self.gatekeeper = Gatekeeper(
            allowed_chat_ids=config.allowed_chat_ids,
            allowed_user_ids=config.allowed_user_ids,
            allowed_usernames=config.allowed_usernames
        )

        # 2. Agent Adapter Factory
        self.adapter: BaseAgentAdapter = self._create_adapter()

        # 3. Channel Factory
        self.channel: BaseChannel = self._create_channel()

        # Concurrency Locks & State
        self.chat_locks: Dict[int, asyncio.Lock] = {}
        self.is_running = False

    def _create_adapter(self) -> BaseAgentAdapter:
        engine_type = self.config.engine_type
        if engine_type == "antigravity":
            return AntigravityAdapter(
                agy_bin=self.config.agy_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model or "gemini-3.7-flash-high",
                timeout_secs=self.config.timeout_secs,
                idle_timeout_mins=self.config.session_idle_timeout_mins
            )
        elif engine_type in ("claude", "claude_code"):
            return ClaudeCodeAdapter(
                claude_bin=self.config.claude_bin,
                workspace_dir=self.config.workspace_dir,
                timeout_secs=self.config.timeout_secs
            )
        elif engine_type in ("codex",):
            return CodexAdapter(
                codex_bin=self.config.codex_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model,
                timeout_secs=self.config.timeout_secs
            )
        elif engine_type in ("opencode", "open-code"):
            return OpenCodeAdapter(
                opencode_bin=self.config.opencode_bin,
                workspace_dir=self.config.workspace_dir,
                model=self.config.model,
                timeout_secs=self.config.timeout_secs
            )
        else:
            raise ValueError(
                f"Unsupported engine_type: '{engine_type}'. "
                f"Supported adapters: 'antigravity', 'claude', 'codex', 'opencode'"
            )

    def _create_channel(self) -> BaseChannel:
        if self.config.platform == "telegram":
            return TelegramChannel(self.config, self.on_inbound_message)
        else:
            raise ValueError(f"Unsupported platform channel: {self.config.platform}. Supported: 'telegram'")

    def get_chat_lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self.chat_locks:
            self.chat_locks[chat_id] = asyncio.Lock()
        return self.chat_locks[chat_id]

    async def start(self) -> None:
        self.is_running = True
        logger.info(f"Starting GroupConnect Gateway (Platform: {self.config.platform}, Engine: {self.config.engine_type})...")

        reaper_task = asyncio.create_task(self._reaper_loop())
        try:
            await self.channel.start()
        finally:
            reaper_task.cancel()
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

    async def on_inbound_message(self, msg: InboundMessage) -> None:
        chat_id = msg.chat_id
        chat_type = msg.chat_type

        # 1. Security Gatekeeper Verification
        dynamic_checker = getattr(self.channel, "check_user_membership", None)
        authorized, reason = await self.gatekeeper.verify_sender(
            chat_id=chat_id,
            chat_type=chat_type,
            from_user=msg.from_user,
            dynamic_checker=dynamic_checker
        )

        if not authorized:
            if reason == "unauthorized_group":
                logger.warning(f"[SECURITY] Unauthorized group message in {chat_id}. Leaving chat...")
                await self.channel.leave_chat(chat_id)
                return
            elif reason == "unauthorized_user":
                logger.warning(f"[SECURITY] Unauthorized private message from {msg.from_user.get('id')} ({msg.sender_name})")
                await self.channel.send_reply(
                    chat_id,
                    "⛔ **Access Restricted**\n\nThis bot is a private assistant limited to authorized members only."
                )
                return

        # 2. Clean query
        raw_text = msg.text
        clean_query = re.sub(rf"@{self.config.bot_username}\b", "", raw_text, flags=re.IGNORECASE).strip()

        # 3. Preemptive /stop Intercept (Bypasses lock)
        cmd, target_bot, _ = parse_bot_command(clean_query if clean_query else raw_text, self.config.bot_username)
        if cmd == "stop" and msg.is_triggered:
            logger.info(f"Received preemptive /stop command for chat {chat_id}")
            self.adapter.terminate(chat_id)
            await self.channel.send_reply(chat_id, "⏹ Task execution was stopped.", reply_to_msg_id=msg.msg_id)
            self.context_mgr.record_message(
                chat_id=chat_id,
                sender_name=msg.sender_name,
                text=msg.text,
                msg_id=msg.msg_id,
                attachments=[]
            )
            return

        # 4. Message processing under chat lock
        lock = self.get_chat_lock(chat_id)
        async with lock:
            self.context_mgr.record_message(
                chat_id=chat_id,
                sender_name=msg.sender_name,
                text=msg.text,
                msg_id=msg.msg_id,
                reply_preview=msg.reply_preview,
                attachments=msg.attachments
            )

            if msg.is_triggered:
                await self._handle_triggered_message(msg, clean_query, cmd)

    async def _handle_triggered_message(self, msg: InboundMessage, clean_query: str, cmd: Optional[str]) -> None:
        chat_id = msg.chat_id
        is_group = msg.chat_type in ("group", "supergroup")
        session = self.context_mgr.get_session(chat_id)
        cid = session.get("conversation_id")

        # Built-in Slash Commands
        if cmd in ("clear", "new", "reset"):
            self.context_mgr.reset_session(chat_id)
            self.adapter.terminate(chat_id)
            await self.channel.send_reply(chat_id, "🧹 Session reset. Started fresh conversation context.", reply_to_msg_id=msg.msg_id)
            return
        elif cmd == "status":
            buf = self.context_mgr.get_buffer(chat_id)
            cid_display = f"`{cid[:8]}...{cid[-6:]}` ({session.get('turns', 0)} turns)" if cid else "Fresh / Idle"
            auth_str = "🛡️ Active Whitelist" if self.gatekeeper.is_whitelist_active() else "⚠️ Open Access"
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

        # Prepare Attachments Prompt Section
        active_attachments = list(msg.attachments)
        for att in msg.reply_attachments:
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

        # Build Full Prompt with Context
        if not is_group:
            full_prompt = (
                f"{attachments_section}\n"
                f"【Sender】: {msg.sender_name}\n"
                f"【Query】: {user_query}\n\n"
                f"Please provide a helpful, accurate, and structured response."
            )
        else:
            if cid is None:
                context_str = self.context_mgr.build_group_context(chat_id, since_msg_id=0) or "(No prior history)"
                full_prompt = (
                    f"【Role Context】\n"
                    f"You are the intelligent group assistant in workspace: {self.config.workspace_dir}\n"
                    f"{attachments_section}\n"
                    f"【Recent Group Discussion Context (Sliding Window)】\n"
                    f"{context_str}\n\n"
                    f"【Current Query】\n"
                    f"Sender: {msg.sender_name}\n"
                    f"Content: {user_query}\n\n"
                    f"Please address the current query taking the group discussion background into account."
                )
            else:
                last_bot_id = session.get("last_bot_msg_id", 0)
                inc_context = self.context_mgr.build_group_context(chat_id, since_msg_id=last_bot_id)
                inc_section = f"\n【New Group Messages Since Last Response】\n{inc_context}\n" if inc_context else ""
                full_prompt = (
                    f"{attachments_section}"
                    f"{inc_section}\n"
                    f"【Current Query】\n"
                    f"Sender: {msg.sender_name}\n"
                    f"Content: {user_query}\n\n"
                    f"Please continue the conversation naturally."
                )

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

        sent_msg_id = await self.channel.send_reply(chat_id, reply_text, reply_to_msg_id=msg.msg_id)
        if sent_msg_id:
            session["last_bot_msg_id"] = sent_msg_id

        self.context_mgr.record_message(
            chat_id=chat_id,
            sender_name=f"{self.config.bot_name} (@{self.config.bot_username})",
            text=reply_text,
            msg_id=sent_msg_id,
            is_bot_reply=True
        )
