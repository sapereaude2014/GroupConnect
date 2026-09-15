import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from groupconnect.channels.base import InboundMessage
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


class TestQueueCoalescing(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config = GatewayConfig({
            "platform": "telegram",
            "engine_type": "opencode",
            "bot_username": "test_bot",
            "bot_name": "Test Bot",
            "workspace_dir": self.test_dir,
            "allow_open_access": True
        })
        mock_channel = MagicMock()
        mock_channel.send_reply = AsyncMock()
        with patch.object(GroupConnectEngine, "_create_adapter", return_value=MagicMock()), \
             patch.object(GroupConnectEngine, "_create_channel", return_value=mock_channel):
            self.engine = GroupConnectEngine(self.config)

    async def asyncTearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    async def test_queue_coalescing_multiple_messages(self):
        chat_id = 9999
        self.engine._handle_triggered_message = AsyncMock()

        # Simulate enqueueing 3 triggered messages rapidly
        msg1 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=101,
            sender_name="xiaorou", from_user={"id": 1, "first_name": "xiaorou"},
            text="@test_bot 第一条爬升数据也要写一下", is_triggered=True
        )
        msg2 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=102,
            sender_name="xiaorou", from_user={"id": 1, "first_name": "xiaorou"},
            text="@test_bot 第二条重新做一下html不需要liv", is_triggered=True
        )
        msg3 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=103,
            sender_name="Zheng Ma", from_user={"id": 2, "first_name": "Zheng Ma"},
            text="@test_bot 第三条画成图", is_triggered=True
        )

        # Enqueue msg1, msg2, msg3 into chat_queues
        self.engine.chat_queues[chat_id] = asyncio.Queue()
        self.engine.chat_queues[chat_id].put_nowait((msg1, "第一条爬升数据也要写一下", None))
        self.engine.chat_queues[chat_id].put_nowait((msg2, "第二条重新做一下html不需要liv", None))
        self.engine.chat_queues[chat_id].put_nowait((msg3, "第三条画成图", None))

        # Process queue
        await self.engine._process_chat_queue(chat_id)

        # Should have called _handle_triggered_message ONCE with msg3 as latest and msg1, msg2 coalesced
        self.assertEqual(self.engine._handle_triggered_message.call_count, 1)
        call_args = self.engine._handle_triggered_message.call_args
        latest_msg, clean_query, cmd = call_args[0]
        coalesced_items = call_args[1].get("coalesced_items", [])

        self.assertEqual(latest_msg.msg_id, 103)
        self.assertEqual(clean_query, "第三条画成图")
        self.assertEqual(len(coalesced_items), 2)
        self.assertEqual(coalesced_items[0][0].msg_id, 101)
        self.assertEqual(coalesced_items[1][0].msg_id, 102)

    async def test_untriggered_message_recorded_immediately_without_blocking(self):
        chat_id = 8888
        untriggered = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=201,
            sender_name="xiaorou", from_user={"id": 1, "first_name": "xiaorou"},
            text="我们白天还上班呢", is_triggered=False
        )
        await self.engine.on_inbound_message(untriggered)
        buf = self.engine.context_mgr.get_buffer(chat_id)
        self.assertEqual(len(buf), 1)
        self.assertEqual(buf[0]["text"], "我们白天还上班呢")
        # Ensure it didn't create a queue or worker task
        self.assertNotIn(chat_id, self.engine.chat_tasks)

    async def test_preemptive_stop_clears_queue(self):
        chat_id = 7777
        self.engine.chat_queues[chat_id] = asyncio.Queue()
        dummy_msg = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=301,
            sender_name="xiaorou", from_user={"id": 1, "first_name": "xiaorou"},
            text="@test_bot 正在跑的任务", is_triggered=True
        )
        self.engine.chat_queues[chat_id].put_nowait((dummy_msg, "正在跑的任务", None))

        stop_msg = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=302,
            sender_name="Zheng Ma", from_user={"id": 2, "first_name": "Zheng Ma"},
            text="@test_bot /stop", is_triggered=True
        )
        await self.engine.on_inbound_message(stop_msg)

        # Queue should be completely empty
        self.assertTrue(self.engine.chat_queues[chat_id].empty())
        self.engine.adapter.terminate.assert_called_with(chat_id)
