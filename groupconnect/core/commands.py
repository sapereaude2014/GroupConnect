"""
Custom Slash Commands Dispatcher for GroupConnect.
Handles execution, pre-flight checks, concurrency locks, and history synchronization.
"""

import asyncio
import logging
import os
import shlex
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("groupconnect.commands")


class CustomCommandDispatcher:
    """Manages registration, preflight verification, locking, and execution of slash commands."""

    def __init__(
        self,
        commands: List[Dict[str, Any]],
        channel: Any,
        context_mgr: Any,
        bot_name: str,
        bot_username: str,
        relay: Optional[Any] = None
    ):
        self.channel = channel
        self.context_mgr = context_mgr
        self.bot_name = bot_name
        self.bot_username = bot_username
        self.relay = relay
        self.running_commands: Set[str] = set()

        self.commands_map: Dict[str, Dict[str, Any]] = {
            str(c.get("command", "")).strip().lower().lstrip("/"): c
            for c in (commands or [])
            if c.get("command")
        }

    def get_command(self, cmd_name: str) -> Optional[Dict[str, Any]]:
        """Lookup command config by clean lowercase name."""
        return self.commands_map.get(str(cmd_name).strip().lower().lstrip("/"))

    def is_running(self, cmd_name: str) -> bool:
        """Check if command is currently running."""
        return str(cmd_name).strip().lower().lstrip("/") in self.running_commands

    def acquire_lock(self, cmd_name: str) -> bool:
        """Attempt to acquire running lock. Returns True if acquired, False if already running."""
        clean = str(cmd_name).strip().lower().lstrip("/")
        if clean in self.running_commands:
            return False
        self.running_commands.add(clean)
        return True

    def release_lock(self, cmd_name: str) -> None:
        """Release running lock."""
        self.running_commands.discard(str(cmd_name).strip().lower().lstrip("/"))

    async def reply_and_record(
        self,
        chat_id: Any,
        text: str,
        reply_to_msg_id: Any = None,
        chat_type: str = "group"
    ) -> Optional[Any]:
        """Send a terminal command reply and record it in chat history, so startup
        resume sees the conversation as already answered. Also broadcasts via CrossBotRelay."""
        sent_id = await self.channel.send_reply(chat_id, text, reply_to_msg_id=reply_to_msg_id)
        try:
            self.context_mgr.record_message(
                chat_id=chat_id,
                sender_name=f"{self.bot_name} (@{self.bot_username})",
                text=text,
                msg_id=sent_id or 0,
                is_bot_reply=True,
                bot_username=self.bot_username
            )
        except Exception as e:
            logger.warning(f"[CUSTOM_CMD] Failed to record command reply in history: {e}")

        if self.relay:
            try:
                await self.relay.broadcast_reply(
                    chat_id=chat_id,
                    chat_type=chat_type,
                    msg_id=sent_id or 0,
                    text=text,
                    hop_count=0
                )
            except Exception as e:
                logger.warning(f"[CUSTOM_CMD] Failed to broadcast command reply via relay: {e}")

        return sent_id

    async def execute_command(
        self,
        chat_id: Any,
        cmd_cfg: Dict[str, Any],
        args: str,
        reply_to_msg_id: Any = None,
        chat_type: str = "group"
    ) -> None:
        """Executes a custom shell or python script bound to a command."""
        cmd_name = str(cmd_cfg.get("command", "")).strip().lower()
        script = os.path.expanduser(cmd_cfg.get("script", ""))

        if not os.path.isfile(script):
            await self.reply_and_record(
                chat_id, f"❌ 未找到执行脚本: {script}", reply_to_msg_id=reply_to_msg_id, chat_type=chat_type
            )
            return

        # 1. Optional check-only pre-flight inspection
        check_args = cmd_cfg.get("check_args")
        force_arg = cmd_cfg.get("force_arg")
        force_requested = bool(force_arg and force_arg in args) or ("force" in (args or "").lower())
        if check_args and not force_requested:
            try:
                check_exec_args = [script] + list(check_args)
                check_proc = await asyncio.create_subprocess_exec(
                    *check_exec_args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await check_proc.communicate()
                if check_proc.returncode == 0:
                    check_msg = cmd_cfg.get("check_success_message")
                    if check_msg:
                        msg_text = check_msg.format(bot_name=self.bot_name, command=cmd_name)
                        await self.reply_and_record(chat_id, msg_text, reply_to_msg_id=reply_to_msg_id, chat_type=chat_type)
                        return
            except Exception as e:
                logger.warning(f"[CUSTOM_CMD] Pre-check failed for '{cmd_name}': {e}")

        # 2. Optional immediate acknowledgement message
        ack_tmpl = cmd_cfg.get("ack_message")
        if ack_tmpl:
            ack_text = ack_tmpl.format(bot_name=self.bot_name, command=cmd_name)
            await self.channel.send_reply(chat_id, ack_text, reply_to_msg_id=reply_to_msg_id)

        # 3. Build execution arguments
        cmd_args = [script]
        if cmd_cfg.get("default_args"):
            cmd_args.extend(list(cmd_cfg.get("default_args")))
        if force_requested and force_arg:
            if force_arg not in cmd_args:
                cmd_args.append(force_arg)
        elif cmd_cfg.get("pass_args", False) and args:
            try:
                parsed_args = shlex.split(args)
            except ValueError:
                parsed_args = args.split()
            cmd_args.extend(parsed_args)

        logger.info(f"[CUSTOM_CMD] Executing '{cmd_name}' ({cmd_args}) for chat {chat_id}...")
        start_ts = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            duration = max(1, int(time.time() - start_ts))
            out_str = (stdout or b"").decode(errors="ignore").strip()
            err_str = (stderr or b"").decode(errors="ignore").strip()

            format_kwargs = {
                "bot_name": self.bot_name,
                "duration": duration,
                "stdout": out_str,
                "stderr": err_str,
                "returncode": proc.returncode,
                "command": cmd_name
            }

            if proc.returncode == 0:
                success_tmpl = cmd_cfg.get("success_message")
                if success_tmpl:
                    reply_text = success_tmpl.format(**format_kwargs)
                else:
                    reply_text = out_str or f"✅ 指令 `{cmd_name}` 执行完成（耗时 {duration}s）。"
                await self.reply_and_record(chat_id, reply_text, reply_to_msg_id=reply_to_msg_id, chat_type=chat_type)
            else:
                error_tmpl = cmd_cfg.get("error_message")
                if error_tmpl:
                    reply_text = error_tmpl.format(**format_kwargs)
                else:
                    reply_text = f"❌ 指令 `{cmd_name}` 执行失败 (Exit {proc.returncode}): {err_str or out_str}"
                await self.reply_and_record(chat_id, reply_text, reply_to_msg_id=reply_to_msg_id, chat_type=chat_type)
        except Exception as e:
            logger.error(f"[CUSTOM_CMD] Failed to execute '{cmd_name}': {e}", exc_info=True)
            await self.reply_and_record(
                chat_id, f"❌ 执行指令 `{cmd_name}` 时出错: {e}", reply_to_msg_id=reply_to_msg_id, chat_type=chat_type
            )
