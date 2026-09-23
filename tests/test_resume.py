import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

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

    def _make_engine(self, resume_secs=300, allowed_chats=None):
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


if __name__ == "__main__":
    unittest.main()
