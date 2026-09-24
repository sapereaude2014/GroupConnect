import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from groupconnect.core.config import GatewayConfig
from groupconnect.channels.base import InboundMessage
from groupconnect.channels.telegram import TelegramChannel
from groupconnect.engine import GroupConnectEngine


class TestCustomCommands(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backup_cfg = {
            "command": "backup",
            "description": "执行全量资产备份",
            "description_en": "Backup assets",
            "script": "/tmp/mock_backup.sh",
            "ack_message": "📦 [{bot_name}] 正在执行备份...",
            "success_message": "✅ [{bot_name}] 备份完成（耗时 {duration}s）。",
            "error_message": "❌ [{bot_name}] 备份失败 (Exit {returncode}): {stderr}",
            "lock": True,
            "arbiter_only_on_broadcast": True
        }

    async def test_explicit_custom_command_dispatch(self):
        """A bot with custom_commands must execute the command when explicitly targeted."""
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "bot_name": "guaguahome_fun",
            "custom_commands": [self.backup_cfg],
            "allow_open_access": True
        })
        engine = GroupConnectEngine(cfg)
        engine.channel.send_reply = AsyncMock()
        engine._run_slash_command = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=101,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup@guaguahome_fun_bot",
            is_triggered=True
        )

        await engine._handle_triggered_message(msg, "/backup", "backup")

        # Lock acquired & command dispatched via wrapper
        self.assertIn("backup", engine._running_custom_commands)
        engine._run_slash_command.assert_called_once()

    async def test_untargeted_broadcast_arbiter_isolation(self):
        """Untargeted broadcast /cmd only runs on the arbiter bot when arbiter_only_on_broadcast is set."""
        # Follower bot
        cfg_follower = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "custom_commands": [self.backup_cfg],
            "allow_open_access": True
        })
        engine_follower = GroupConnectEngine(cfg_follower)
        engine_follower.autonomous = MagicMock()
        engine_follower.autonomous.is_arbiter = False
        engine_follower.channel.send_reply = AsyncMock()
        engine_follower._run_slash_command = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=102,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup",
            is_triggered=True
        )

        await engine_follower._handle_triggered_message(msg, "/backup", "backup")
        # Follower bot drops untargeted command
        engine_follower.channel.send_reply.assert_not_called()
        engine_follower._run_slash_command.assert_not_called()
        self.assertNotIn("backup", engine_follower._running_custom_commands)

        # Arbiter bot
        cfg_arbiter = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_bot",
            "custom_commands": [self.backup_cfg],
            "allow_open_access": True
        })
        engine_arbiter = GroupConnectEngine(cfg_arbiter)
        engine_arbiter.autonomous = MagicMock()
        engine_arbiter.autonomous.is_arbiter = True
        engine_arbiter.channel.send_reply = AsyncMock()
        engine_arbiter._run_slash_command = AsyncMock()

        await engine_arbiter._handle_triggered_message(msg, "/backup", "backup")
        engine_arbiter._run_slash_command.assert_called_once()
        self.assertIn("backup", engine_arbiter._running_custom_commands)

    async def test_concurrency_lock(self):
        """Re-entrant command must be rejected when locked."""
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_bot",
            "custom_commands": [self.backup_cfg],
            "allow_open_access": True
        })
        engine = GroupConnectEngine(cfg)
        engine._running_custom_commands.add("backup")
        engine.channel.send_reply = AsyncMock()
        engine._run_slash_command = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=103,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup@guaguahome_bot",
            is_triggered=True
        )

        await engine._handle_triggered_message(msg, "/backup", "backup")
        engine.channel.send_reply.assert_called_once()
        self.assertIn("正在执行中，请勿重复触发", engine.channel.send_reply.call_args[0][1])
        engine._run_slash_command.assert_not_called()

    async def test_dynamic_telegram_menu(self):
        """TelegramChannel dynamically registers only the commands defined in config."""
        cfg_fun = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "custom_commands": [
                {"command": "backup", "description": "执行全量资产备份", "description_en": "Backup assets"}
            ]
        })
        chan_fun = TelegramChannel(cfg_fun, message_handler=AsyncMock())
        chan_fun._api_call = AsyncMock(return_value={"ok": True})

        await chan_fun._register_bot_commands()

        # Verify setMyCommands calls
        calls = chan_fun._api_call.call_args_list
        zh_call = next(c for c in calls if c[1].get("language_code") == "zh")
        registered_cmds = [cmd["command"] for cmd in zh_call[1]["commands"]]

        self.assertIn("status", registered_cmds)
        self.assertIn("stop", registered_cmds)
        self.assertIn("new", registered_cmds)
        self.assertIn("backup", registered_cmds)
        # /login must NOT be registered because it is not in custom_commands!
        self.assertNotIn("login", registered_cmds)


if __name__ == "__main__":
    unittest.main()
