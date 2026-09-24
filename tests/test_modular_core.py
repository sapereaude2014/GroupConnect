import asyncio
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from groupconnect.core.commands import CustomCommandDispatcher
from groupconnect.core.delivery import OutboundDelivery, extract_outbound_files, strip_sendfile_tags
from groupconnect.core.pattern import PatternExecutor
from groupconnect.core.recovery import ResumeManager


class TestModularCoreComponents(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    # 1. Delivery & SendFile Tests
    def test_outbound_file_extraction_and_stripping(self):
        sample_file = os.path.join(self.workspace, "doc.pdf")
        with open(sample_file, "w") as f:
            f.write("content")

        text = f"Here is the report:\n【SendFile: {sample_file} | 财务报表】\nHave a nice day!"
        extracted = extract_outbound_files(text, self.workspace)
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0], (sample_file, "财务报表"))

        stripped = strip_sendfile_tags(text)
        self.assertNotIn("SendFile", stripped)
        self.assertIn("Here is the report:", stripped)
        self.assertIn("Have a nice day!", stripped)

    async def test_outbound_delivery_dispatch(self):
        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock(return_value=1234)
        mock_channel.send_file = AsyncMock()
        mock_context = MagicMock()
        mock_relay = MagicMock()
        mock_relay.broadcast_reply = AsyncMock()

        delivery = OutboundDelivery(
            channel=mock_channel,
            context_mgr=mock_context,
            workspace_dir=self.workspace,
            bot_name="TestBot",
            bot_username="test_bot",
            relay=mock_relay
        )

        sent_id, clean_text = await delivery.deliver(
            chat_id=1001,
            reply_text="Test reply message",
            reply_to_msg_id=555
        )
        self.assertEqual(sent_id, 1234)
        self.assertEqual(clean_text, "Test reply message")
        mock_channel.send_reply.assert_awaited_once_with(1001, "Test reply message", reply_to_msg_id=555)
        mock_context.record_message.assert_called_once()
        mock_relay.broadcast_reply.assert_awaited_once()

    # 2. PatternExecutor Tests
    def test_pattern_matching_and_filtering(self):
        pattern_cfg = [{
            "pattern": r"^(开|关)(电脑|空调)$",
            "script": "/tmp/dummy.py",
            "max_length": 10
        }]
        executor = PatternExecutor(
            pattern_configs=pattern_cfg,
            custom_commands_map={},
            command_dispatcher=MagicMock(),
            channel=MagicMock()
        )
        # Clean match
        match = executor.match("开电脑。")
        self.assertIsNotNone(match)
        pc, raw = match
        self.assertEqual(raw, "开电脑")

        # Exceeds max length
        self.assertIsNone(executor.match("开电脑而且请顺便帮我把空调也一起开一下谢谢"))

        # No regex match
        self.assertIsNone(executor.match("打游戏"))

    async def test_pattern_per_device_concurrency_lock(self):
        mock_dispatcher = MagicMock()
        mock_dispatcher.running_commands = set()
        mock_dispatcher.execute_command = AsyncMock()

        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock()

        pattern_cfg = [{
            "pattern": r"^(开|关)(电脑|空调)$",
            "script": "/tmp/dummy.py"
        }]
        executor = PatternExecutor(
            pattern_configs=pattern_cfg,
            custom_commands_map={},
            command_dispatcher=mock_dispatcher,
            channel=mock_channel
        )
        pc = executor.patterns[0]

        # Simulate lock already held for '开电脑'
        cmd_name = pc["_cmd_cfg"]["command"]
        executor.running_locks.add(f"{cmd_name}:开电脑")

        await executor.execute(chat_id=1001, pc=pc, text="开电脑")
        # Blocked by lock
        mock_channel.send_reply.assert_awaited_once()
        mock_dispatcher.execute_command.assert_not_called()

        # Different device '开空调' is NOT blocked
        await executor.execute(chat_id=1001, pc=pc, text="开空调")
        mock_dispatcher.execute_command.assert_awaited_once()

    async def test_command_chat_type_propagation_to_relay(self):
        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock(return_value=999)
        mock_context = MagicMock()
        mock_relay = MagicMock()
        mock_relay.broadcast_reply = AsyncMock()

        # Dummy script
        script_file = os.path.join(self.workspace, "test.sh")
        with open(script_file, "w") as f:
            f.write("#!/bin/sh\necho 'ok'\n")
        os.chmod(script_file, 0o755)

        cmd_cfg = {
            "command": "testcmd",
            "script": script_file
        }
        dispatcher = CustomCommandDispatcher(
            commands=[cmd_cfg],
            channel=mock_channel,
            context_mgr=mock_context,
            bot_name="TestBot",
            bot_username="test_bot",
            relay=mock_relay
        )

        # 1. CustomCommandDispatcher propagates chat_type to relay
        await dispatcher.execute_command(
            chat_id=1001,
            cmd_cfg=cmd_cfg,
            args="",
            chat_type="private"
        )
        mock_relay.broadcast_reply.assert_awaited_once()
        self.assertEqual(mock_relay.broadcast_reply.await_args.kwargs["chat_type"], "private")

        # 2. PatternExecutor propagates chat_type to dispatcher & relay
        mock_relay.broadcast_reply.reset_mock()
        executor = PatternExecutor(
            pattern_configs=[{"pattern": r"^测试$", "command": "testcmd"}],
            custom_commands_map={"testcmd": cmd_cfg},
            command_dispatcher=dispatcher,
            channel=mock_channel
        )
        pc = executor.patterns[0]
        await executor.execute(chat_id=1001, pc=pc, text="测试", chat_type="private")
        mock_relay.broadcast_reply.assert_awaited_once()
        self.assertEqual(mock_relay.broadcast_reply.await_args.kwargs["chat_type"], "private")

    # 3. ResumeManager & Poison Message Quarantine Tests
    def test_resume_quarantines_poison_message(self):
        now = datetime.now()
        mock_context = MagicMock()
        mock_context.buffers = {
            1001: [
                {"sender": "User", "text": "bad toxic message", "is_bot": False, "msg_id": 999, "time": now.strftime("%Y-%m-%d %H:%M:%S")}
            ]
        }
        manager = ResumeManager(
            context_mgr=mock_context,
            bot_username="test_bot",
            window_seconds=60,
            max_retries=2
        )

        # Attempt 1
        res1 = manager.find_unanswered_messages()
        self.assertEqual(len(res1), 1)

        # Attempt 2
        res2 = manager.find_unanswered_messages()
        self.assertEqual(len(res2), 1)

        # Attempt 3: exceeds max_retries=2 -> quarantined and skipped!
        res3 = manager.find_unanswered_messages()
        self.assertEqual(len(res3), 0)
        self.assertEqual(len(manager._poison_quarantine), 1)

    def test_resume_quarantine_persists_across_restarts(self):
        import tempfile
        import shutil
        temp_dir = tempfile.mkdtemp()
        try:
            now = datetime.now()
            mock_context = MagicMock()
            mock_context.chat_logs_dir = temp_dir
            mock_context.buffers = {
                1001: [
                    {"sender": "User", "text": "crash message", "is_bot": False, "msg_id": 888, "time": now.strftime("%Y-%m-%d %H:%M:%S")}
                ]
            }

            # Run 1: First startup before crash
            mgr1 = ResumeManager(context_mgr=mock_context, bot_username="bot", window_seconds=60, max_retries=2)
            res1 = mgr1.find_unanswered_messages()
            self.assertEqual(len(res1), 1)

            # Run 2: Process restarted after crash, state rehydrated from disk
            mgr2 = ResumeManager(context_mgr=mock_context, bot_username="bot", window_seconds=60, max_retries=2)
            self.assertEqual(mgr2._retry_counts.get("1001:888:crash message"), 1)
            res2 = mgr2.find_unanswered_messages()
            self.assertEqual(len(res2), 1)

            # Run 3: Second restart after another crash -> hit max_retries=2, quarantined!
            mgr3 = ResumeManager(context_mgr=mock_context, bot_username="bot", window_seconds=60, max_retries=2)
            res3 = mgr3.find_unanswered_messages()
            self.assertEqual(len(res3), 0)
            self.assertIn("1001:888:crash message", mgr3._poison_quarantine)

            # Run 4: Subsequent restart maintains quarantine immediately
            mgr4 = ResumeManager(context_mgr=mock_context, bot_username="bot", window_seconds=60, max_retries=2)
            self.assertIn("1001:888:crash message", mgr4._poison_quarantine)
            res4 = mgr4.find_unanswered_messages()
            self.assertEqual(len(res4), 0)

            # Completing a message clears retry state
            mgr4.mark_completed(1001, 888, "crash message")
            mgr5 = ResumeManager(context_mgr=mock_context, bot_username="bot", window_seconds=60, max_retries=2)
            self.assertNotIn("1001:888:crash message", mgr5._retry_counts)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
