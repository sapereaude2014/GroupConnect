import asyncio
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from groupconnect.channels.base import InboundMessage
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine

DEVICE_PATTERN = (
    "^(开|关)(电脑|卧室空调|卧室灯)(开|关|\\d{1,2})?$"
    "|^(电脑|卧室空调|卧室灯)(开|关|\\d{1,2})$"
)


class TestPatternCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.custom_cmds = []

    async def asyncTearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_engine(self, pattern_cfg):
        config = GatewayConfig({
            "platform": "telegram",
            "engine_type": "opencode",
            "bot_username": "test_bot",
            "bot_name": "Test Bot",
            "workspace_dir": self.test_dir,
            "custom_commands": self.custom_cmds,
            "pattern_commands": pattern_cfg,
            "allow_open_access": True
        })
        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock()
        with patch.object(GroupConnectEngine, "_create_adapter", return_value=MagicMock()), \
             patch.object(GroupConnectEngine, "_create_channel", return_value=mock_channel):
            engine = GroupConnectEngine(config)
        engine._run_pattern_command = AsyncMock()
        return engine

    @staticmethod
    def _msg(text, msg_id=101):
        return InboundMessage(
            chat_id=9999, chat_type="group", msg_id=msg_id,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng"},
            text=text, is_triggered=False
        )

    async def test_standalone_script_registration(self):
        """A pattern with its own script registers without any custom_commands entry."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
            "pass_args": True,
            "lock": True,
        }])
        self.assertEqual(len(engine._pattern_commands), 1)
        pc = engine._pattern_commands[0]
        self.assertEqual(pc["command"], "pattern_1")
        self.assertEqual(pc["_cmd_cfg"]["script"], "/tmp/device.py")
        self.assertTrue(pc["_cmd_cfg"]["pass_args"])

    async def test_legacy_binding_to_custom_command(self):
        """A pattern bound via 'command' still resolves to the custom command cfg."""
        self.custom_cmds = [{"command": "device", "script": "/tmp/device.py", "pass_args": True}]
        engine = self._make_engine([{"pattern": DEVICE_PATTERN, "command": "device"}])
        self.assertEqual(len(engine._pattern_commands), 1)
        self.assertEqual(engine._pattern_commands[0]["_cmd_cfg"]["script"], "/tmp/device.py")

    async def test_pattern_without_command_or_script_skipped(self):
        """A pattern referencing neither a custom command nor a script is skipped."""
        engine = self._make_engine([{"pattern": DEVICE_PATTERN}])
        self.assertEqual(engine._pattern_commands, [])

    async def test_short_device_command_hits_fast_lane(self):
        """A clean short command bypasses autonomous routing and dispatches directly."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
            "pass_args": True,
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        await engine.on_inbound_message(self._msg("关卧室灯"))
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_awaited_once()
        au.on_human_message.assert_not_called()

    async def test_scene_word_no_longer_hits_fast_lane(self):
        """A scene word absent from the pattern falls through to autonomous routing."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        await engine.on_inbound_message(self._msg("睡觉"))
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_not_awaited()
        au.on_human_message.assert_called_once()

    async def test_chatter_bypasses_fast_lane(self):
        """Long conversational text never triggers the fast lane."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        await engine.on_inbound_message(self._msg("今晚开电脑打游戏吗"))
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_not_awaited()

    async def test_trailing_punctuation_stripped_before_match(self):
        """Trailing punctuation is stripped so voice-to-text output still matches."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        await engine.on_inbound_message(self._msg("开电脑。"))
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_awaited_once()
        args = engine._run_pattern_command.await_args
        self.assertEqual(args[0][2], "开电脑")

    async def test_max_length_config_respected(self):
        """A per-pattern max_length tighter than the default gates the fast lane."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
            "max_length": 4,
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        # 5 chars > max_length 4 -> falls through to autonomous routing
        await engine.on_inbound_message(self._msg("开卧室空调"))
        await asyncio.sleep(0)
        engine._run_pattern_command.assert_not_awaited()

        # 3 chars <= max_length 4 -> fast lane fires
        await engine.on_inbound_message(self._msg("开电脑"))
        await asyncio.sleep(0)
        engine._run_pattern_command.assert_awaited_once()
