import asyncio
import os
import shutil
import tempfile
import unittest

from groupconnect.core.relay import CrossBotRelay


class TestCrossBotRelay(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_groupconnect_ipc_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_relay_broadcast_and_receive(self):
        received_events = []

        async def on_b_event(event):
            received_events.append(event)

        relay_a = CrossBotRelay(
            bot_username="guaguahome_bot",
            bot_name="guaguahome",
            ipc_dir=self.test_dir
        )
        relay_b = CrossBotRelay(
            bot_username="guaguahome_fun_bot",
            bot_name="guaguahome_fun",
            ipc_dir=self.test_dir,
            on_event=on_b_event
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            await relay_a.start()
            await relay_b.start()

            self.assertTrue(os.path.exists(relay_a.sock_path))
            self.assertTrue(os.path.exists(relay_b.sock_path))

            # Broadcast from A
            await relay_a.broadcast_reply(
                chat_id=-1004324820543,
                chat_type="supergroup",
                msg_id=1001,
                text="Hello @guaguahome_fun_bot please take over!",
                hop_count=0
            )

            # Wait briefly for async event dispatch
            await asyncio.sleep(0.2)

            self.assertEqual(len(received_events), 1)
            event = received_events[0]
            self.assertEqual(event["event"], "bot_reply")
            self.assertEqual(event["from_bot"], "guaguahome_bot")
            self.assertEqual(event["from_name"], "guaguahome")
            self.assertEqual(event["chat_id"], -1004324820543)
            self.assertEqual(event["msg_id"], 1001)
            self.assertEqual(event["hop_count"], 0)
            self.assertIn("@guaguahome_fun_bot", event["text"])

            await relay_a.stop()
            await relay_b.stop()

            self.assertFalse(os.path.exists(relay_a.sock_path))
            self.assertFalse(os.path.exists(relay_b.sock_path))

        loop.run_until_complete(run_test())
        loop.close()

    def test_stale_socket_cleanup(self):
        # Create a fake dead socket file
        fake_sock = os.path.join(self.test_dir, "dead_bot.sock")
        with open(fake_sock, "w") as f:
            f.write("stale")

        relay_a = CrossBotRelay(
            bot_username="guaguahome_bot",
            bot_name="guaguahome",
            ipc_dir=self.test_dir
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            await relay_a.start()
            # Broadcasting should gracefully handle stale socket
            await relay_a.broadcast_reply(
                chat_id=-1004324820543,
                chat_type="supergroup",
                msg_id=1002,
                text="Test broadcast with stale socket",
                hop_count=0
            )
            await relay_a.stop()

        loop.run_until_complete(run_test())
        loop.close()
