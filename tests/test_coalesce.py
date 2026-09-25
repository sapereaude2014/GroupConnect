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

    async def test_resume_burst_single_coalesced_drain(self):
        """A resume burst parks queue workers until the settle window lapses,
        then the whole batch drains in ONE coalesced pass (one reply)."""
        from types import SimpleNamespace

        chat_id = 5555
        self.engine._handle_triggered_message = AsyncMock()
        self.engine.autonomous = SimpleNamespace(cfg=SimpleNamespace(max_queue_backlog=50))

        with patch("groupconnect.engine.RESUME_BURST_SETTLE_SECS", 0.1):
            for i in range(3):
                await self.engine._dispatch_autonomous({
                    "chat_id": chat_id, "chat_type": "group", "msg_id": 400 + i,
                    "sender": "Zheng Ma", "text": f"补捞任务{i}",
                    "target_bots": ["test_bot"], "urgency": "immediate",
                    "is_resume": True,
                })

            # Inside the settle window: worker parked, nothing processed yet
            self.assertNotIn(chat_id, self.engine.chat_tasks)
            self.assertEqual(self.engine._handle_triggered_message.call_count, 0)

            # Window lapses -> release task starts the worker -> single drain
            await asyncio.sleep(0.4)

        self.assertEqual(self.engine._handle_triggered_message.call_count, 1)
        args, kwargs = self.engine._handle_triggered_message.call_args
        self.assertEqual(args[0].msg_id, 402)  # latest lands in Current Query
        self.assertEqual(len(kwargs.get("coalesced_items", [])), 2)

        # A live (non-resume) dispatch during calm starts the worker immediately
        self.engine._handle_triggered_message.reset_mock()
        await self.engine._dispatch_autonomous({
            "chat_id": chat_id, "chat_type": "group", "msg_id": 410,
            "sender": "Zheng Ma", "text": "实时的活消息",
            "target_bots": ["test_bot"], "urgency": "immediate",
        })
        await asyncio.sleep(0.05)
        self.assertEqual(self.engine._handle_triggered_message.call_count, 1)

    async def test_group_coalesced_marked_inline_not_duplicated(self):
        """In group chats, coalesced messages are marked with ⏳ in the sliding
        window context, NOT listed in a separate Coalesced Pending Instructions
        section (eliminates duplication)."""
        chat_id = 6666
        # Pre-populate buffer with the coalesced messages
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "帮我看下闹钟", msg_id=501)
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "后天去杭州", msg_id=502)

        msg_latest = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=503,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot 还有高铁票帮我查一下", is_triggered=True
        )
        msg_1 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=501,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="帮我看下闹钟", is_triggered=True
        )
        msg_2 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=502,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="后天去杭州", is_triggered=True
        )

        full_prompt, _, _ = self.engine._build_agent_prompt(
            msg_latest, "还有高铁票帮我查一下", True,
            {"conversation_id": None}, None,
            coalesced_items=[(msg_1, "帮我看下闹钟", None), (msg_2, "后天去杭州", None)]
        )

        # The coalesced messages should appear with ⏳ marker in the sliding window
        self.assertIn("⏳", full_prompt)
        self.assertIn("帮我看下闹钟", full_prompt)
        self.assertIn("后天去杭州", full_prompt)

        # The separate Coalesced Pending Instructions section should NOT exist
        self.assertNotIn("Coalesced Pending Instructions", full_prompt)

    async def test_private_chat_coalesced_marked_inline_like_group(self):
        """Private chats use the same sliding-window context as groups, so
        coalesced messages are marked inline with ⏳ too — no separate section."""
        chat_id = 7777
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "帮我看下闹钟", msg_id=601)
        msg_latest = InboundMessage(
            chat_id=chat_id, chat_type="private", msg_id=603,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="还有高铁票", is_triggered=True
        )
        msg_1 = InboundMessage(
            chat_id=chat_id, chat_type="private", msg_id=601,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="帮我看下闹钟", is_triggered=True
        )

        full_prompt, _, _ = self.engine._build_agent_prompt(
            msg_latest, "还有高铁票", False,
            {"conversation_id": None}, None,
            coalesced_items=[(msg_1, "帮我看下闹钟", None)]
        )

        # Private chat: same inline ⏳ marking inside the sliding window
        self.assertIn("⏳", full_prompt)
        self.assertIn("帮我看下闹钟", full_prompt)
        self.assertIn("【Recent Conversation Context (Sliding Window)】", full_prompt)
        # The separate Coalesced Pending Instructions section is gone
        self.assertNotIn("Coalesced Pending Instructions", full_prompt)

    async def test_private_first_turn_gets_full_window(self):
        """Private chat first turn (or expired runtime session) injects the
        full sliding window so the agent has history despite cold start."""
        chat_id = 8888
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "上次聊的杭州出差", msg_id=701)
        self.engine.context_mgr.record_message(chat_id, "Test Bot", "已为您查好车票", msg_id=702, is_bot_reply=True, bot_username="test_bot")
        msg = InboundMessage(
            chat_id=chat_id, chat_type="private", msg_id=703,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="还是改下午的吧", is_triggered=True
        )

        full_prompt, _, _ = self.engine._build_agent_prompt(
            msg, "还是改下午的吧", False,
            {"conversation_id": None}, None
        )

        # Prior history from the buffer must be present (cold-start safety net)
        self.assertIn("上次聊的杭州出差", full_prompt)
        self.assertIn("已为您查好车票", full_prompt)
        self.assertIn("【Recent Conversation Context (Sliding Window)】", full_prompt)
        # Current message itself is excluded from the window (it is the query)
        self.assertIn("【Current Query】", full_prompt)
        self.assertNotIn("⏳", full_prompt)  # no pending items, no markers

    async def test_private_subsequent_turn_incremental_only(self):
        """Private chat with a live runtime conversation sends only the
        incremental slice since the last processed input."""
        chat_id = 8889
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "旧消息一", msg_id=801)
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "旧消息二", msg_id=802)
        self.engine.context_mgr.record_message(chat_id, "Zheng Ma", "排队新消息", msg_id=803)
        msg = InboundMessage(
            chat_id=chat_id, chat_type="private", msg_id=804,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="最新这条", is_triggered=True
        )
        msg_pending = InboundMessage(
            chat_id=chat_id, chat_type="private", msg_id=803,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="排队新消息", is_triggered=True
        )

        full_prompt, _, _ = self.engine._build_agent_prompt(
            msg, "最新这条", False,
            {"conversation_id": "sess-123", "last_input_msg_id": 802}, "sess-123",
            coalesced_items=[(msg_pending, "排队新消息", None)]
        )

        # Incremental slice only: messages at/below the anchor are absent
        self.assertIn("排队新消息", full_prompt)
        self.assertNotIn("旧消息一", full_prompt)
        self.assertNotIn("旧消息二", full_prompt)
        self.assertIn("【New Messages Since Last Response】", full_prompt)
        self.assertIn("⏳", full_prompt)  # pending coalesced marked inline

    async def test_mixed_batch_ordinary_followed_by_command(self):
        """When an ordinary conversational message is followed by a slash command
        in the queue, ordinary message is processed first and the command is NOT
        swallowed, executing independently in subsequent drain."""
        chat_id = 9101
        self.engine._handle_triggered_message = AsyncMock()

        msg_normal = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=901,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot 查一下杭州天气", is_triggered=True
        )
        msg_cmd = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=902,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot /backup", is_triggered=True
        )

        self.engine.chat_queues[chat_id] = asyncio.Queue()
        self.engine.chat_queues[chat_id].put_nowait((msg_normal, "查一下杭州天气", None))
        self.engine.chat_queues[chat_id].put_nowait((msg_cmd, "/backup", "backup"))

        await self.engine._process_chat_queue(chat_id)

        # Both items must be handled across iterations:
        # Call 1: normal message (clean_query="查一下杭州天气", cmd=None)
        # Call 2: slash command (clean_query="/backup", cmd="backup")
        self.assertEqual(self.engine._handle_triggered_message.call_count, 2)
        call1 = self.engine._handle_triggered_message.call_args_list[0]
        call2 = self.engine._handle_triggered_message.call_args_list[1]

        self.assertEqual(call1[0][0].msg_id, 901)
        self.assertIsNone(call1[0][2])
        self.assertEqual(call2[0][0].msg_id, 902)
        self.assertEqual(call2[0][2], "backup")

    async def test_mixed_batch_command_first_not_downgraded_to_prompt(self):
        """When a command is followed by ordinary messages, the command runs
        alone and does NOT get coalesced into ordinary messages as prompt text."""
        chat_id = 9102
        self.engine._handle_triggered_message = AsyncMock()

        msg_cmd = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=911,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot /backup", is_triggered=True
        )
        msg_normal1 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=912,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot 帮我看下方案一", is_triggered=True
        )
        msg_normal2 = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=913,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="@test_bot 还要出张图", is_triggered=True
        )

        self.engine.chat_queues[chat_id] = asyncio.Queue()
        self.engine.chat_queues[chat_id].put_nowait((msg_cmd, "/backup", "backup"))
        self.engine.chat_queues[chat_id].put_nowait((msg_normal1, "帮我看下方案一", None))
        self.engine.chat_queues[chat_id].put_nowait((msg_normal2, "还要出张图", None))

        await self.engine._process_chat_queue(chat_id)

        # Call 1: command alone
        # Call 2: normal messages coalesced
        self.assertEqual(self.engine._handle_triggered_message.call_count, 2)
        call1 = self.engine._handle_triggered_message.call_args_list[0]
        call2 = self.engine._handle_triggered_message.call_args_list[1]

        self.assertEqual(call1[0][0].msg_id, 911)
        self.assertEqual(call1[0][2], "backup")

        self.assertEqual(call2[0][0].msg_id, 913)
        self.assertIsNone(call2[0][2])
        self.assertEqual(len(call2[1].get("coalesced_items", [])), 1)
        self.assertEqual(call2[1]["coalesced_items"][0][0].msg_id, 912)

    async def test_historical_stop_disarmed_on_resume(self):
        """Historical /stop re-dispatched during recovery is disarmed: it does
        NOT terminate the running adapter or wipe queue workers."""
        chat_id = 9103
        self.engine.chat_queues[chat_id] = asyncio.Queue()
        active_msg = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=921,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="正在等待的真实任务", is_triggered=True
        )
        self.engine.chat_queues[chat_id].put_nowait((active_msg, "正在等待的真实任务", None))

        resume_stop = InboundMessage(
            chat_id=chat_id, chat_type="group", msg_id=922,
            sender_name="Zheng Ma", from_user={"id": 1, "first_name": "Zheng Ma"},
            text="/stop", is_triggered=True, is_resume=True
        )

        await self.engine.on_inbound_message(resume_stop, record=False)

        # The active queue must NOT be wiped
        self.assertFalse(self.engine.chat_queues[chat_id].empty())
        # The adapter must NOT be terminated
        self.engine.adapter.terminate.assert_not_called()
