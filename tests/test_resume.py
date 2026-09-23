import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from groupconnect.channels.base import InboundMessage
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


def make_item(text, sender="Zheng Ma", is_bot=False, when=None, msg_id=101):
    t = when or datetime.now()
    return {
        "time": t.strftime("%Y-%m-%d %H:%M:%S"),
        "msg_id": msg_id,
        "sender": sender,
        "text": text,
        "is_bot": is_bot,
    }


class TestResumeUnanswered(unittest.IsolatedAsyncioTestCase):
    """Startup resume: recent unanswered human messages are re-dispatched after a restart."""

    def _make_engine(self, resume_secs=300, allowed_chats=None, mock_inbound=True):
        self.test_dir = tempfile.mkdtemp()
        config = GatewayConfig({
            "platform": "telegram",
            "engine_type": "opencode",
            "bot_username": "test_bot",
            "bot_name": "Test Bot",
            "workspace_dir": self.test_dir,
            "allow_open_access": True,
            "tuning": {"resume_unanswered_secs": resume_secs},
            "security": {"allowed_chat_ids": allowed_chats or []},
        })
        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock()
        with patch.object(GroupConnectEngine, "_create_adapter", return_value=MagicMock()), \
             patch.object(GroupConnectEngine, "_create_channel", return_value=mock_channel):
            engine = GroupConnectEngine(config)
        if mock_inbound:
            engine.on_inbound_message = AsyncMock()
        engine.context_mgr.buffers = {}
        return engine

    def tearDown(self):
        if getattr(self, "test_dir", None):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_fresh_unanswered_message_dispatched(self):
        """Last buffer entry is a recent human message -> re-dispatched through the pipeline."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("旧的聊天记录", msg_id=99),
            make_item("开电脑", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "开电脑")
        self.assertFalse(msg.is_triggered)

    async def test_answered_message_skipped(self):
        """Last buffer entry is a bot reply (answered) -> nothing is resumed."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", msg_id=101),
            make_item("✅ 工作室电脑开机脉冲已下发", sender="bot", is_bot=True, msg_id=102),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_stale_message_skipped(self):
        """A human message older than the freshness window is never resumed."""
        engine = self._make_engine(resume_secs=300)
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", when=datetime.now() - timedelta(minutes=10), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_resume_disabled(self):
        """resume_unanswered_secs=0 disables the feature entirely."""
        engine = self._make_engine(resume_secs=0)
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_disallowed_chat_skipped(self):
        """With an allowlist active, chats outside it are never resumed."""
        engine = self._make_engine(allowed_chats=[-100999])
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_allowed_chat_dispatched(self):
        """Chats inside the allowlist resume normally."""
        engine = self._make_engine(allowed_chats=[-100123])
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()

    async def test_malformed_timestamp_skipped(self):
        """An unparseable timestamp never crashes or resumes the chat."""
        engine = self._make_engine()
        item = make_item("开电脑")
        item["time"] = "not-a-timestamp"
        engine.context_mgr.buffers[-100123] = [item]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_fast_lane_reply_does_not_mask_unanswered_human(self):
        """When a fast-lane ✅ sits after an unanswered human message, the scanner
        skips the bot reply and rescues the earlier unanswered human message.

        Real scenario: slow inference task killed by restart, fast-lane command
        completed and wrote ✅ to buffer. Both human messages are in the buffer
        (recorded before any processing)."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("帮我查明天天气", when=now - timedelta(seconds=60), msg_id=201),
            make_item("开卧室灯", when=now - timedelta(seconds=30), msg_id=202),
            make_item("✅ 卧室灯已打开", sender="bot", is_bot=True, when=now - timedelta(seconds=29), msg_id=203),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "帮我查明天天气")

    async def test_all_answered_chain_skipped(self):
        """Multiple human→bot pairs: every human message has a bot reply after it,
        nothing is resumed."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("开卧室灯", when=now - timedelta(seconds=60), msg_id=301),
            make_item("✅ 卧室灯已打开", sender="bot", is_bot=True, when=now - timedelta(seconds=59), msg_id=302),
            make_item("开电脑", when=now - timedelta(seconds=30), msg_id=303),
            make_item("✅ 电脑已开机", sender="bot", is_bot=True, when=now - timedelta(seconds=29), msg_id=304),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_unanswered_human_between_bot_replies(self):
        """An unanswered human message sandwiched between bot replies is rescued.
        Real scenario: old bot reply, then human asks something (slow), then
        fast-lane command completes with ✅ — restart kills the slow task."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("✅ 旧任务完成", sender="bot", is_bot=True, when=now - timedelta(seconds=90), msg_id=401),
            make_item("查一下美股行情", when=now - timedelta(seconds=40), msg_id=402),
            make_item("开卧室灯", when=now - timedelta(seconds=20), msg_id=403),
            make_item("✅ 卧室灯已打开", sender="bot", is_bot=True, when=now - timedelta(seconds=19), msg_id=404),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "查一下美股行情")

    async def test_trailing_bot_replies_skipped_then_human_rescued(self):
        """Trailing bot messages (e.g. fast-lane ✅) don't prevent rescuing an
        earlier unanswered human message within the freshness window."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("帮我做个计划", when=now - timedelta(seconds=40), msg_id=501),
            make_item("关卧室灯", when=now - timedelta(seconds=20), msg_id=502),
            make_item("✅ 卧室灯已关闭", sender="bot", is_bot=True, when=now - timedelta(seconds=19), msg_id=503),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "帮我做个计划")

    async def test_re_dispatch_skips_history_re_recording(self):
        """The resumed message is already the buffer's last entry, so the re-dispatch
        must flow through the pipeline without writing a duplicate history entry."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        self.assertFalse(engine.on_inbound_message.await_args[1].get("record", True))

    async def test_record_false_skips_context_recording(self):
        """on_inbound_message(record=False) leaves the history buffer untouched while
        the default still records — this is what keeps resume re-dispatch duplicate-free."""
        engine = self._make_engine(mock_inbound=False)
        msg = InboundMessage(
            chat_id=-100123, chat_type="group", msg_id=101,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng"},
            text="开电脑", is_triggered=False,
        )
        await engine.on_inbound_message(msg, record=False)
        self.assertEqual(len(engine.context_mgr.get_buffer(-100123)), 0)
        await engine.on_inbound_message(msg)
        self.assertEqual(len(engine.context_mgr.get_buffer(-100123)), 1)


if __name__ == "__main__":
    unittest.main()
