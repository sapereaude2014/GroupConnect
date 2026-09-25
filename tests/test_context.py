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
        # Verify pre-warming: buffer is populated upon __init__ via rehydrate_all()
        self.assertIn(chat_id, mgr2.buffers)
        buf = mgr2.get_buffer(chat_id)
        self.assertEqual(len(buf), 5)
        self.assertEqual(buf[0]["text"], "Message 1")
        self.assertEqual(buf[-1]["text"], "Message 5")

        ctx = mgr2.build_group_context(chat_id)
        self.assertIn("Message 1", ctx)
        self.assertIn("Message 5", ctx)

    def test_rehydration_with_bot_username(self):
        chat_id = -1004324820543
        mgr1 = ContextManager(max_history_len=5, chat_logs_dir=self.test_dir, bot_username="guaguahome_bot")
        mgr1.record_message(chat_id, "User", "Hello bot", msg_id=1)

        # On restart, mgr2 with bot_username should discover and pre-warm the buffer
        mgr2 = ContextManager(max_history_len=5, chat_logs_dir=self.test_dir, bot_username="guaguahome_bot")
        self.assertIn(chat_id, mgr2.buffers)
        self.assertEqual(len(mgr2.buffers[chat_id]), 1)
        self.assertEqual(mgr2.buffers[chat_id][0]["text"], "Hello bot")

    def test_format_sender(self):
        self.assertEqual(format_sender({"first_name": "John", "last_name": "Doe"}), "John Doe")
        self.assertEqual(format_sender({"first_name": "John", "username": "johndoe"}), "John (@johndoe)")
        self.assertEqual(format_sender({}), "Unknown User")

    def test_pending_msg_ids_marked_inline(self):
        """Coalesced pending messages are marked with ⏳ inline in the context
        instead of being duplicated in a separate prompt section."""
        chat_id = 2001
        self.mgr.record_message(chat_id, "Alice", "第一条", msg_id=10)
        self.mgr.record_message(chat_id, "Bob", "第二条", msg_id=11)
        self.mgr.record_message(chat_id, "Alice", "第三条", msg_id=12)

        # Mark msg 10 and 12 as pending (coalesced), 11 is not
        ctx = self.mgr.build_group_context(chat_id, pending_msg_ids={10, 12})
        lines = ctx.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("⏳ "))
        self.assertIn("第一条", lines[0])
        self.assertFalse(lines[1].startswith("⏳ "))
        self.assertIn("第二条", lines[1])
        self.assertTrue(lines[2].startswith("⏳ "))
        self.assertIn("第三条", lines[2])

    def test_no_pending_ids_no_markers(self):
        """Without pending_msg_ids, no entries are marked."""
        chat_id = 2002
        self.mgr.record_message(chat_id, "Alice", "hello", msg_id=20)
        ctx = self.mgr.build_group_context(chat_id)
        self.assertFalse("⏳" in ctx)

    def test_pending_with_exclude_and_since(self):
        """Pending markers work alongside exclude_msg_id and since_msg_id."""
        chat_id = 2003
        self.mgr.record_message(chat_id, "Alice", "old", msg_id=30)
        self.mgr.record_message(chat_id, "Bob", "mid", msg_id=31)
        self.mgr.record_message(chat_id, "Alice", "new1", msg_id=32)
        self.mgr.record_message(chat_id, "Bob", "new2", msg_id=33)

        # since=30, exclude=33, pending={32}
        ctx = self.mgr.build_group_context(
            chat_id, since_msg_id=30, exclude_msg_id=33, pending_msg_ids={32}
        )
        lines = ctx.split("\n")
        self.assertEqual(len(lines), 2)
        self.assertIn("mid", lines[0])
        self.assertFalse(lines[0].startswith("⏳ "))
        self.assertTrue(lines[1].startswith("⏳ "))
        self.assertIn("new1", lines[1])

    def test_since_msg_id_mixed_types(self):
        """since_msg_id provided as a string or int filters older numeric IDs correctly."""
        chat_id = 2004
        self.mgr.record_message(chat_id, "Alice", "msg20", msg_id=20)
        self.mgr.record_message(chat_id, "Bob", "msg30", msg_id=30)
        self.mgr.record_message(chat_id, "Alice", "msg40", msg_id=40)

        # Pass since_msg_id as string "30"
        ctx = self.mgr.build_group_context(chat_id, since_msg_id="30")
        lines = ctx.split("\n")
        self.assertEqual(len(lines), 1)
        self.assertIn("msg40", lines[0])
        self.assertNotIn("msg20", ctx)
        self.assertNotIn("msg30", ctx)


if __name__ == "__main__":
    unittest.main()
