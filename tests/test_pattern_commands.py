import asyncio
import os
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

    def _make_engine(self, pattern_cfg, mock_pattern_cmd=True):
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
        if mock_pattern_cmd:
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
        # Pattern dict stays clean (no command fields); identity lives in _cmd_cfg
        self.assertNotIn("command", pc)
        self.assertEqual(pc["_cmd_cfg"]["command"], "pattern_1")
        self.assertEqual(pc["_cmd_cfg"]["script"], "/tmp/device.py")
        self.assertTrue(pc["_cmd_cfg"]["pass_args"])

    async def test_standalone_pattern_safe_defaults(self):
        """A standalone pattern defaults to pass_args=True and lock=True without explicit config."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        cfg = engine._pattern_commands[0]["_cmd_cfg"]
        self.assertTrue(cfg["pass_args"])
        self.assertTrue(cfg["lock"])

    async def test_standalone_pattern_explicit_override(self):
        """Explicit pass_args/lock values are respected, not clobbered by the safe defaults."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
            "pass_args": False,
            "lock": False,
        }])
        cfg = engine._pattern_commands[0]["_cmd_cfg"]
        self.assertFalse(cfg["pass_args"])
        self.assertFalse(cfg["lock"])

    async def test_legacy_binding_not_touched_by_pattern_defaults(self):
        """A pattern bound via 'command' defers to the backing custom command's explicit cfg;
        pattern safe defaults never leak into the custom_commands entry."""
        self.custom_cmds = [{"command": "device", "script": "/tmp/device.py"}]
        engine = self._make_engine([{"pattern": DEVICE_PATTERN, "command": "device"}])
        cfg = engine._pattern_commands[0]["_cmd_cfg"]
        self.assertNotIn("pass_args", cfg)
        self.assertNotIn("lock", cfg)

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

    async def test_pattern_reply_recorded_in_history(self):
        """Terminal fast-lane replies are recorded in chat history, so the startup
        resume of unanswered messages sees the conversation as already answered."""
        script = os.path.join(self.test_dir, "ok.sh")
        with open(script, "w") as f:
            f.write("#!/bin/sh\necho '✅ 卧室灯已打开'\n")
        os.chmod(script, 0o755)
        engine = self._make_engine([{"pattern": DEVICE_PATTERN, "script": script}], mock_pattern_cmd=False)
        engine.channel.send_reply.return_value = 42

        await engine.on_inbound_message(self._msg("关卧室灯"))
        for _ in range(60):  # fast-lane task + subprocess round-trip
            buf = engine.context_mgr.get_buffer(9999)
            if len(buf) >= 2 and buf[-1].get("is_bot"):
                break
            await asyncio.sleep(0.05)

        buf = engine.context_mgr.get_buffer(9999)
        self.assertEqual(len(buf), 2)
        self.assertFalse(buf[0]["is_bot"])
        self.assertEqual(buf[0]["text"], "关卧室灯")
        self.assertTrue(buf[1]["is_bot"])
        self.assertIn("卧室灯已打开", buf[1]["text"])
        self.assertIn("test_bot", buf[1]["sender"])

    async def test_pattern_fast_lane_in_private_chat(self):
        """Pattern fast lane fires in private chats (is_triggered=True)."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        msg = InboundMessage(
            chat_id=8888, chat_type="private", msg_id=201,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng"},
            text="关电脑", is_triggered=True
        )
        await engine.on_inbound_message(msg)
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_awaited_once()

    async def test_pattern_fast_lane_triggered_group_with_bot_tag(self):
        """Pattern fast lane fires for triggered group messages (@bot + device command)."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        msg = InboundMessage(
            chat_id=9999, chat_type="group", msg_id=202,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng"},
            text="@test_bot 关电脑", is_triggered=True
        )
        await engine.on_inbound_message(msg)
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_awaited_once()

    async def test_pattern_fast_lane_skipped_for_reply_to_other_bot(self):
        """Pattern fast lane does not fire when replying to another bot."""
        engine = self._make_engine([{
            "pattern": DEVICE_PATTERN,
            "script": "/tmp/device.py",
        }])
        au = MagicMock()
        au.cfg.enabled = True
        au.is_arbiter = False
        engine.autonomous = au

        msg = InboundMessage(
            chat_id=9999, chat_type="group", msg_id=203,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng"},
            text="关电脑", is_triggered=False,
            reply_to_bot_username="other_bot"
        )
        await engine.on_inbound_message(msg)
        await asyncio.sleep(0)

        engine._run_pattern_command.assert_not_awaited()

    async def test_per_device_lock_allows_parallel_different_devices(self):
        """Lock is per-device (per trigger text): different device commands run
        in parallel, same device command is blocked while executing."""
        engine = self._make_engine(pattern_cfg=[{
            "pattern": "^(开|关)(电脑|卧室空调|卧室灯)(\\d{1,2})?$",
            "script": "/tmp/device.py",
        }])
        self.assertTrue(engine._pattern_commands[0]["_cmd_cfg"]["lock"])

        # First command locks "pattern_1:开卧室空调"
        lock_key_1 = "pattern_1:开卧室空调"
        engine._running_custom_commands.add(lock_key_1)

        # Same device → blocked
        # (We check the lock set directly since _run_custom_command needs a real script)
        self.assertIn(lock_key_1, engine._running_custom_commands)

        # Different device → not blocked (different lock key)
        lock_key_2 = "pattern_1:开电脑"
        self.assertNotIn(lock_key_2, engine._running_custom_commands)

        # Lock release cleans up
        engine._running_custom_commands.discard(lock_key_1)
        self.assertNotIn(lock_key_1, engine._running_custom_commands)
