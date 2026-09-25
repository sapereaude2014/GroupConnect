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


    async def test_mention_message_resumed_as_triggered(self):
        """A restart-killed @bot message keeps its triggered status on resume,
        instead of being demoted to untriggered and silently dropped by the
        source-level mention filter before Jev ever sees it.

        Real scenario: 23:21 @bot question, reply killed by a 23:24 restart,
        resume then re-injected it as untriggered and it vanished."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("@test_bot 怎么这么久", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.chat_type, "group")
        self.assertTrue(msg.is_triggered)

    async def test_private_chat_resumed_as_triggered(self):
        """Private-chat messages resume as triggered (all private messages are)."""
        engine = self._make_engine()
        engine.context_mgr.buffers[8148123619] = [
            make_item("关电脑", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.chat_type, "private")
        self.assertTrue(msg.is_triggered)

    async def test_slash_command_resumed_as_triggered(self):
        """A restart-killed slash command resumes as triggered so it reaches
        command dispatch instead of dying at the untriggered '/' guard."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("/backup", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertTrue(msg.is_triggered)

    async def test_mention_of_other_bot_resumed_untriggered(self):
        """A message @-mentioning someone else must NOT become triggered on resume:
        it belongs to the mention filter (directed at another bot/user)."""
        engine = self._make_engine()
        engine.context_mgr.buffers[-100123] = [
            make_item("@other_bot 去看看", when=datetime.now() - timedelta(seconds=30), msg_id=101),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertFalse(msg.is_triggered)

    # ---------- Watermark scan (reply_to linkage) ----------

    @staticmethod
    def _bot_item(text, when, msg_id, reply_to):
        """Bot reply entry WITH reply_to_msg_id linkage (post-2026-09-25 data)."""
        item = make_item(text, sender="Test Bot (@test_bot)", is_bot=True, when=when, msg_id=msg_id)
        item["reply_to_msg_id"] = reply_to
        item["bot_username"] = "test_bot"
        return item

    async def test_watermark_collects_all_after_quoted(self):
        """Watermark = the human message quoted by the newest linked bot reply.
        Every human message after the watermark is resumed (multi-candidate)."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("查明天天气", when=now - timedelta(seconds=90), msg_id=601),
            make_item("再帮我定闹钟", when=now - timedelta(seconds=80), msg_id=602),
            self._bot_item("✅ 天气已查", now - timedelta(seconds=70), 603, reply_to=601),
            make_item("对了还有高铁票", when=now - timedelta(seconds=50), msg_id=604),
            make_item("再查下美股", when=now - timedelta(seconds=40), msg_id=605),
        ]
        await engine._resume_unanswered_messages()
        # 601 is quoted by the bot reply -> settled (watermark).
        # 602, 604, 605 are all AFTER the watermark -> all resumed, oldest first.
        self.assertEqual(engine.on_inbound_message.await_count, 3)
        texts = [call.args[0].text for call in engine.on_inbound_message.await_args_list]
        self.assertEqual(texts, ["再帮我定闹钟", "对了还有高铁票", "再查下美股"])

    async def test_watermark_burst_answered_not_resumed(self):
        """User sends 5 messages, bot answers quoting the last one -> nothing
        before the quoted message is resumed (already crossed-over)."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("A", when=now - timedelta(seconds=100), msg_id=701),
            make_item("B", when=now - timedelta(seconds=95), msg_id=702),
            make_item("C", when=now - timedelta(seconds=90), msg_id=703),
            make_item("D", when=now - timedelta(seconds=85), msg_id=704),
            make_item("E", when=now - timedelta(seconds=80), msg_id=705),
            self._bot_item("✅ 已全部处理", now - timedelta(seconds=70), 706, reply_to=705),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_not_awaited()

    async def test_watermark_tonight_2218_case(self):
        """Real 2026-09-25 22:29 case: two human messages, bot reply quotes the
        FIRST one and lands after both -> the second (sandwiched, unanswered)
        is correctly resumed."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("对啊 刚这个应该是 immediate", when=now - timedelta(seconds=60), msg_id=801),
            make_item("写函数的设想怎么样", when=now - timedelta(seconds=50), msg_id=802),
            self._bot_item("✅ 三件事交付完毕", now - timedelta(seconds=30), 803, reply_to=801),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "写函数的设想怎么样")

    async def test_watermark_unlinked_bot_entries_skipped(self):
        """Bot replies without reply_to (fast-lane receipts, legacy data) do NOT
        set the watermark; the scan skips them and uses the newest LINKED reply."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("开电脑", when=now - timedelta(seconds=100), msg_id=901),
            self._bot_item("✅ 电脑已开机", now - timedelta(seconds=99), 902, reply_to=901),
            make_item("帮我查天气", when=now - timedelta(seconds=60), msg_id=903),
            make_item("✅ 卧室灯已打开", sender="bot", is_bot=True, when=now - timedelta(seconds=30), msg_id=904),
        ]
        await engine._resume_unanswered_messages()
        # The fast-lane receipt (904, no reply_to) doesn't block: newest LINKED
        # reply (902, quotes 901) is the watermark -> 903 is after it -> resumed.
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "帮我查天气")

    async def test_watermark_resumes_oldest_first_for_coalescing(self):
        """Resume order is oldest-first so the coalescer puts the LATEST message
        into Current Query downstream (mirrors the live dispatch semantics)."""
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("已回答的旧问题", when=now - timedelta(seconds=120), msg_id=1009),
            self._bot_item("✅ 旧问题已答", now - timedelta(seconds=110), 1000, reply_to=1009),
            make_item("第一条", when=now - timedelta(seconds=60), msg_id=1010),
            make_item("第二条", when=now - timedelta(seconds=50), msg_id=1011),
            make_item("第三条最新的", when=now - timedelta(seconds=40), msg_id=1012),
        ]
        await engine._resume_unanswered_messages()
        self.assertEqual(engine.on_inbound_message.await_count, 3)
        texts = [call.args[0].text for call in engine.on_inbound_message.await_args_list]
        self.assertEqual(texts, ["第一条", "第二条", "第三条最新的"])

    async def test_watermark_stale_candidates_filtered(self):
        """Only candidates inside the freshness window are resumed; older ones
        beyond the watermark stay behind even after a linked reply."""
        engine = self._make_engine(resume_secs=300)
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("水位线锚点", when=now - timedelta(seconds=130), msg_id=1109),
            self._bot_item("✅ 已答", now - timedelta(seconds=120), 1100, reply_to=1109),
            make_item("新鲜的问题", when=now - timedelta(seconds=60), msg_id=1110),
            make_item("太旧的没人管", when=now - timedelta(minutes=10), msg_id=1111),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        msg = engine.on_inbound_message.await_args[0][0]
        self.assertEqual(msg.text, "新鲜的问题")

    async def test_watermark_candidates_marked_is_resume(self):
        """Both scan paths mark candidates is_resume so downstream skips live
        grace windows (no sibling-cancel eating) and batches the burst."""
        # Watermark path (linked reply quotes a real anchor message)
        engine = self._make_engine()
        now = datetime.now()
        engine.context_mgr.buffers[-100123] = [
            make_item("已答的锚点", when=now - timedelta(seconds=80), msg_id=1199),
            self._bot_item("✅ 已答", now - timedelta(seconds=70), 1200, reply_to=1199),
            make_item("水位线后的新任务", when=now - timedelta(seconds=40), msg_id=1201),
        ]
        await engine._resume_unanswered_messages()
        engine.on_inbound_message.assert_awaited_once()
        self.assertTrue(engine.on_inbound_message.await_args[0][0].is_resume)

        # Legacy path (no linked reply anywhere in buffer)
        engine2 = self._make_engine()
        engine2.context_mgr.buffers[-100123] = [
            make_item("旧数据时代的任务", when=datetime.now() - timedelta(seconds=30), msg_id=1301),
        ]
        await engine2._resume_unanswered_messages()
        engine2.on_inbound_message.assert_awaited_once()
        self.assertTrue(engine2.on_inbound_message.await_args[0][0].is_resume)


if __name__ == "__main__":
    unittest.main()
