import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from groupconnect.core.config import GatewayConfig
from groupconnect.channels.base import InboundMessage
from groupconnect.engine import GroupConnectEngine


class TestBackupCommandHandling(unittest.IsolatedAsyncioTestCase):
    async def test_fun_bot_explicit_backup(self):
        """guaguahome_fun_bot (antigravity) MUST execute backup when explicitly targeted."""
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "bot_name": "guaguahome_fun",
            "engine_type": "antigravity",
            "allow_open_access": True
        })
        engine = GroupConnectEngine(cfg)
        engine.channel.send_reply = AsyncMock()
        engine._run_backup_command = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=101,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup@guaguahome_fun_bot",
            is_triggered=True
        )

        with patch("os.path.isfile", return_value=True):
            await engine._handle_triggered_message(msg, "/backup", "backup")

        # Must send confirmation and trigger backup
        engine.channel.send_reply.assert_called_once()
        self.assertIn("管家备份", engine.channel.send_reply.call_args[0][1])
        self.assertTrue(engine._backup_running)

    async def test_untargeted_backup_routing(self):
        """Untargeted broadcast /backup only runs on the arbiter bot."""
        # Follower bot
        cfg_follower = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "engine_type": "antigravity",
            "allow_open_access": True
        })
        engine_follower = GroupConnectEngine(cfg_follower)
        engine_follower.autonomous = MagicMock()
        engine_follower.autonomous.is_arbiter = False
        engine_follower.channel.send_reply = AsyncMock()
        engine_follower._run_backup_command = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=102,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup",
            is_triggered=True
        )

        with patch("os.path.isfile", return_value=True):
            await engine_follower._handle_triggered_message(msg, "/backup", "backup")

        # Follower bot must silently drop untargeted /backup
        engine_follower.channel.send_reply.assert_not_called()
        self.assertFalse(engine_follower._backup_running)

        # Arbiter bot
        cfg_arbiter = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_bot",
            "engine_type": "teleagent",
            "allow_open_access": True
        })
        engine_arbiter = GroupConnectEngine(cfg_arbiter)
        engine_arbiter.autonomous = MagicMock()
        engine_arbiter.autonomous.is_arbiter = True
        engine_arbiter.channel.send_reply = AsyncMock()
        engine_arbiter._run_backup_command = AsyncMock()

        with patch("os.path.isfile", return_value=True):
            await engine_arbiter._handle_triggered_message(msg, "/backup", "backup")

        engine_arbiter.channel.send_reply.assert_called_once()
        self.assertTrue(engine_arbiter._backup_running)

    async def test_backup_concurrency_lock(self):
        """Concurrent backup requests must be rejected with busy notice."""
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "engine_type": "antigravity",
            "allow_open_access": True
        })
        engine = GroupConnectEngine(cfg)
        engine._backup_running = True
        engine.channel.send_reply = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=103,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/backup@guaguahome_fun_bot",
            is_triggered=True
        )

        await engine._handle_triggered_message(msg, "/backup", "backup")
        engine.channel.send_reply.assert_called_once()
        self.assertIn("已有备份任务正在执行中", engine.channel.send_reply.call_args[0][1])

    async def test_login_redirect_for_non_teleagent_bot(self):
        """Non-teleagent bot receiving explicitly targeted /login redirects user to guaguahome_bot."""
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "bot_username": "guaguahome_fun_bot",
            "engine_type": "antigravity",
            "allow_open_access": True
        })
        engine = GroupConnectEngine(cfg)
        engine.channel.send_reply = AsyncMock()

        msg = InboundMessage(
            chat_id=12345,
            chat_type="group",
            msg_id=104,
            sender_name="Zheng Ma",
            from_user={"id": 1, "first_name": "Zheng", "username": "zheng"},
            text="/login@guaguahome_fun_bot",
            is_triggered=True
        )

        await engine._handle_triggered_message(msg, "/login", "login")
        engine.channel.send_reply.assert_called_once()
        self.assertIn("@guaguahome_bot", engine.channel.send_reply.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
