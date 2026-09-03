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
