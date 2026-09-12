import os
import shutil
import tempfile
import unittest
from groupconnect.core.context import ContextManager, format_sender


class TestContextManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.mgr = ContextManager(max_history_len=10, chat_logs_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_sliding_window_overflow(self):
        small_mgr = ContextManager(max_history_len=3, chat_logs_dir=self.test_dir)
        chat_id = 1001
        small_mgr.record_message(chat_id, "Alice", "msg 1", msg_id=1)
        small_mgr.record_message(chat_id, "Bob", "msg 2", msg_id=2)
        small_mgr.record_message(chat_id, "Charlie", "msg 3", msg_id=3)
        small_mgr.record_message(chat_id, "Alice", "msg 4", msg_id=4)

        buf = small_mgr.get_buffer(chat_id)
        self.assertEqual(len(buf), 3)
        self.assertEqual(buf[0]["text"], "msg 2")
        self.assertEqual(buf[-1]["text"], "msg 4")

    def test_incremental_delta_context(self):
        chat_id = 1002
        self.mgr.record_message(chat_id, "Alice", "msg 1", msg_id=10)
        self.mgr.record_message(chat_id, "Bot", "reply 1", msg_id=11, is_bot_reply=True)
        self.mgr.record_message(chat_id, "Bob", "msg 2", msg_id=12)
        self.mgr.record_message(chat_id, "Charlie", "msg 3", msg_id=13)

        # Full context (all 4 messages)
        full_ctx = self.mgr.build_group_context(chat_id, since_msg_id=0)
        self.assertIn("msg 1", full_ctx)
        self.assertIn("reply 1", full_ctx)
        self.assertIn("msg 2", full_ctx)
        self.assertIn("msg 3", full_ctx)

        # Delta context since msg_id 11 (last bot reply)
        delta_ctx = self.mgr.build_group_context(chat_id, since_msg_id=11)
        self.assertNotIn("msg 1", delta_ctx)
        self.assertNotIn("reply 1", delta_ctx)
        self.assertIn("msg 2", delta_ctx)
        self.assertIn("msg 3", delta_ctx)

        # Delta context excluding the current triggered message (msg_id 13)
        delta_ctx_excluded = self.mgr.build_group_context(chat_id, since_msg_id=11, exclude_msg_id=13)
        self.assertIn("msg 2", delta_ctx_excluded)
        self.assertNotIn("msg 3", delta_ctx_excluded)

    def test_incremental_anchor_last_input_not_last_bot(self):
        """Messages arriving during bot processing must not be lost.
        Simulate: input(10) -> bot processes -> during processing, user sends
        msg(12) -> bot replies(13) -> next input(14) arrives. Incremental
        context anchored to last_input_msg_id(10) should include msg 12,
        not anchored to last_bot_msg_id(13) which would skip it."""
        chat_id = 1004
        self.mgr.record_message(chat_id, "Alice", "trigger msg", msg_id=10)
        # Simulate: bot sets last_input_msg_id = 10 before processing
        sess = self.mgr.get_session(chat_id)
        sess["last_input_msg_id"] = 10

        # During bot processing, a user message arrives
        self.mgr.record_message(chat_id, "Rong", "hidden msg during processing", msg_id=12)

        # Bot finishes and replies (msg_id=13)
        self.mgr.record_message(chat_id, "Bot", "bot reply", msg_id=13, is_bot_reply=True, bot_username="my_bot")
        sess["last_bot_msg_id"] = 13

        # Next triggered message arrives (msg_id=14)
        self.mgr.record_message(chat_id, "Bob", "next trigger", msg_id=14)

        # OLD behavior: anchor to last_bot_msg_id=13 → misses msg 12
        old_delta = self.mgr.build_group_context(chat_id, since_msg_id=13, exclude_msg_id=14)
        self.assertNotIn("hidden msg during processing", old_delta)

        # NEW behavior: anchor to last_input_msg_id=10 → includes msg 12, skips bot reply
        new_delta = self.mgr.build_group_context(
            chat_id, since_msg_id=10, exclude_msg_id=14, skip_bot_username="my_bot"
        )
        self.assertIn("hidden msg during processing", new_delta)
        self.assertNotIn("bot reply", new_delta)  # skip_bot_username excludes bot's own reply

    def test_skip_bot_filter(self):
        """skip_bot_username should exclude only the specified bot's own replies."""
        chat_id = 1005
        self.mgr.record_message(chat_id, "Alice", "hello", msg_id=1)
        self.mgr.record_message(chat_id, "Bot", "hi there", msg_id=2, is_bot_reply=True, bot_username="my_bot")
        self.mgr.record_message(chat_id, "Bob", "world", msg_id=3)

        with_bot = self.mgr.build_group_context(chat_id)
        self.assertIn("hi there", with_bot)

        without_bot = self.mgr.build_group_context(chat_id, skip_bot_username="my_bot")
        self.assertNotIn("hi there", without_bot)
        self.assertIn("hello", without_bot)
        self.assertIn("world", without_bot)

    def test_skip_bot_preserves_partner_bot_messages(self):
        """skip_bot_username must NOT filter partner bot messages — only own replies."""
        chat_id = 1006
        self.mgr.record_message(chat_id, "Alice", "user msg", msg_id=1)
        # Partner bot's message (different bot_username)
        self.mgr.record_message(
            chat_id, "PartnerBot (@partner_bot)", "partner reply",
            msg_id=2, is_bot_reply=True, bot_username="partner_bot"
        )
        # Own bot's reply
        self.mgr.record_message(
            chat_id, "MyBot (@my_bot)", "my reply",
            msg_id=3, is_bot_reply=True, bot_username="my_bot"
        )
        self.mgr.record_message(chat_id, "Bob", "another user msg", msg_id=4)

        ctx = self.mgr.build_group_context(chat_id, skip_bot_username="my_bot")
        # Own reply filtered out
        self.assertNotIn("my reply", ctx)
        # Partner bot reply PRESERVED (the bug was that it was also filtered)
        self.assertIn("partner reply", ctx)
        # User messages preserved
        self.assertIn("user msg", ctx)
        self.assertIn("another user msg", ctx)

    def test_rehydration_after_restart(self):
        chat_id = 1003
        # 1. Record 5 messages with instance 1
        mgr1 = ContextManager(max_history_len=5, chat_logs_dir=self.test_dir)
        for i in range(1, 6):
            mgr1.record_message(chat_id, f"User{i}", f"Message {i}", msg_id=i)

        # 2. Simulate gateway restart: create a new ContextManager instance
        mgr2 = ContextManager(max_history_len=5, chat_logs_dir=self.test_dir)
        buf = mgr2.get_buffer(chat_id)
        self.assertEqual(len(buf), 5)
        self.assertEqual(buf[0]["text"], "Message 1")
        self.assertEqual(buf[-1]["text"], "Message 5")

        ctx = mgr2.build_group_context(chat_id)
        self.assertIn("Message 1", ctx)
        self.assertIn("Message 5", ctx)

    def test_format_sender(self):
        self.assertEqual(format_sender({"first_name": "John", "last_name": "Doe"}), "John Doe")
        self.assertEqual(format_sender({"first_name": "John", "username": "johndoe"}), "John (@johndoe)")
        self.assertEqual(format_sender({}), "Unknown User")


if __name__ == "__main__":
    unittest.main()
