import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from groupconnect.channels.telegram import TelegramChannel
from groupconnect.channels.discord import DiscordChannel
from groupconnect.channels.slack import SlackChannel
from groupconnect.channels.feishu import FeishuChannel
from groupconnect.channels.wecom import WeComChannel
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


class TestChannels(unittest.TestCase):
    def test_all_5_channel_instantiations(self):
        # 1. Telegram
        cfg_tg = GatewayConfig({"platform": "telegram", "bot_token": "mock_token"})
        engine_tg = GroupConnectEngine(cfg_tg)
        self.assertIsInstance(engine_tg.channel, TelegramChannel)

        # 2. Discord
        cfg_discord = GatewayConfig({"platform": "discord", "discord_bot_token": "mock_discord_token"})
        engine_discord = GroupConnectEngine(cfg_discord)
        self.assertIsInstance(engine_discord.channel, DiscordChannel)
        self.assertEqual(engine_discord.channel.bot_token, "mock_discord_token")

        # 3. Slack
        cfg_slack = GatewayConfig({"platform": "slack", "slack_bot_token": "xoxb-mock-token"})
        engine_slack = GroupConnectEngine(cfg_slack)
        self.assertIsInstance(engine_slack.channel, SlackChannel)
        self.assertEqual(engine_slack.channel.bot_token, "xoxb-mock-token")

        # 4. Feishu
        cfg_feishu = GatewayConfig({
            "platform": "feishu",
            "feishu_app_id": "cli_mock_123",
            "feishu_app_secret": "sec_mock_456"
        })
        engine_feishu = GroupConnectEngine(cfg_feishu)
        self.assertIsInstance(engine_feishu.channel, FeishuChannel)
        self.assertEqual(engine_feishu.channel.app_id, "cli_mock_123")

        # 5. WeCom
        cfg_wecom = GatewayConfig({
            "platform": "wecom",
            "wecom_corp_id": "ww_mock_corp",
            "wecom_corp_secret": "sec_mock_corp",
            "wecom_agent_id": "1000002"
        })
        engine_wecom = GroupConnectEngine(cfg_wecom)
        self.assertIsInstance(engine_wecom.channel, WeComChannel)
        self.assertEqual(engine_wecom.channel.corp_id, "ww_mock_corp")


class TestTelegramChannelOutbound(unittest.IsolatedAsyncioTestCase):
    async def test_short_reply_sent_directly(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token"
        })
        channel = TelegramChannel(cfg, AsyncMock())
        channel._api_call = AsyncMock(return_value={"ok": True, "result": {"message_id": 123}})

        msg_id = await channel.send_reply(chat_id=1, text="Hello world")
        self.assertEqual(msg_id, 123)
        channel._api_call.assert_called_once_with(
            "sendMessage",
            chat_id=1,
            text="Hello world",
            parse_mode="Markdown",
            reply_to_message_id=None,
            link_preview_options={"is_disabled": True}
        )

    async def test_long_reply_auto_telegraph(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token"
        })
        channel = TelegramChannel(cfg, AsyncMock())
        channel._api_call = AsyncMock(return_value={"ok": True, "result": {"message_id": 456}})

        long_text = "This is a very long text that exceeds the 20 character threshold easily."
        with patch("groupconnect.channels.telegram.process_outbound_text", AsyncMock(return_value="📄 [Title](https://telegra.ph/xyz)")) as mock_pub:
            msg_id = await channel.send_reply(chat_id=1, text=long_text)
            self.assertEqual(msg_id, 456)
            mock_pub.assert_called_once()
            channel._api_call.assert_called_once_with(
                "sendMessage",
                chat_id=1,
                text="📄 [Title](https://telegra.ph/xyz)",
                parse_mode="Markdown",
                reply_to_message_id=None,
                link_preview_options={"is_disabled": True}
            )

    async def test_fallback_blockquote_uses_html(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token"
        })
        channel = TelegramChannel(cfg, AsyncMock())
        channel._api_call = AsyncMock(return_value={"ok": True, "result": {"message_id": 789}})

        long_text = "This is a very long text that triggers fallback."
        fallback_html = "<blockquote expandable>This is a very long text that triggers fallback.</blockquote>"
        with patch("groupconnect.channels.telegram.process_outbound_text", AsyncMock(return_value=fallback_html)):
            msg_id = await channel.send_reply(chat_id=1, text=long_text)
            self.assertEqual(msg_id, 789)
            channel._api_call.assert_called_once_with(
                "sendMessage",
                chat_id=1,
                text=fallback_html,
                parse_mode="HTML",
                reply_to_message_id=None,
                link_preview_options={"is_disabled": True}
            )

    async def test_download_file_sanitizes_path_traversal(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmp_att:
            cfg = GatewayConfig({
                "platform": "telegram",
                "bot_token": "mock_token",
            })
            cfg.attachments_dir = tmp_att
            channel = TelegramChannel(cfg, AsyncMock())
            channel._api_call = AsyncMock(return_value={"ok": True, "result": {"file_path": "photos/file_0.jpg"}})

            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.content = b"fake image bytes"
            channel.client.get = AsyncMock(return_value=mock_resp)

            # Attempt directory traversal
            malicious_dest = "../../evil.sh"
            saved_path = await channel._download_file("file_id_123", malicious_dest)

            # Must save inside tmp_att as evil.sh, NOT in parent directories
            self.assertEqual(saved_path, os.path.join(tmp_att, "evil.sh"))
            self.assertTrue(os.path.isfile(os.path.join(tmp_att, "evil.sh")))

    def test_sanitize_markdown(self):
        # Indented bullets converted to unicode bullet
        md = "1. Item\n   - Sub A\n   * Sub B\n   + Sub C"
        expected = "1. Item\n   • Sub A\n   • Sub B\n   • Sub C"
        self.assertEqual(TelegramChannel.sanitize_markdown(md), expected)

        # Indented numbers converted to (n)
        md_num = "1. Item\n   1. Sub 1\n   2. Sub 2"
        expected_num = "1. Item\n   (1) Sub 1\n   (2) Sub 2"
        self.assertEqual(TelegramChannel.sanitize_markdown(md_num), expected_num)

        # Top-level lists and code blocks untouched
        preserved = "- Top bullet\n* Star\n1. Top ordered\n```python\n   - code\n   1. code\n```\n---"
        self.assertEqual(TelegramChannel.sanitize_markdown(preserved), preserved)

    async def test_send_reply_sanitizes_nested_lists(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
        })
        channel = TelegramChannel(cfg, AsyncMock())
        channel._api_call = AsyncMock(return_value={"ok": True, "result": {"message_id": 999}})

        raw_text = "1. Title\n   - Sub A\n   - Sub B"
        await channel.send_reply(chat_id=1, text=raw_text)

        channel._api_call.assert_called_once_with(
            "sendMessage",
            chat_id=1,
            text="1. Title\n   • Sub A\n   • Sub B",
            parse_mode="Markdown",
            reply_to_message_id=None,
            link_preview_options={"is_disabled": True}
        )

    async def test_send_reply_custom_link_preview_options(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "channel_options": {
                "link_preview_options": {"is_disabled": False, "prefer_small_media": True}
            }
        })
        channel = TelegramChannel(cfg, AsyncMock())
        channel._api_call = AsyncMock(return_value={"ok": True, "result": {"message_id": 111}})

        await channel.send_reply(chat_id=1, text="Test custom preview")
        channel._api_call.assert_called_once_with(
            "sendMessage",
            chat_id=1,
            text="Test custom preview",
            parse_mode="Markdown",
            reply_to_message_id=None,
            link_preview_options={"is_disabled": False, "prefer_small_media": True}
        )


class TestFeishuChannelOutbound(unittest.IsolatedAsyncioTestCase):
    def _make_channel(self):
        import tempfile
        # Per-test temp ipc_dir so persisted fold caches don't leak between tests
        tmpdir = tempfile.mkdtemp(prefix="feishu_test_ipc_")
        cfg = GatewayConfig({
            "platform": "feishu",
            "feishu_app_id": "cli_mock_123",
            "feishu_app_secret": "sec_mock_456",
            "tuning": {"ipc_dir": tmpdir},
        })
        channel = FeishuChannel(cfg, AsyncMock())
        channel.get_tenant_access_token = AsyncMock(return_value="mock_token")
        return channel

    @staticmethod
    def _mock_resp(payload):
        resp = MagicMock()
        resp.json.return_value = payload
        return resp

    def test_has_markdown_detection(self):
        self.assertFalse(FeishuChannel._has_markdown("你好，今天天气不错。"))
        self.assertTrue(FeishuChannel._has_markdown("**加粗**文本"))
        self.assertTrue(FeishuChannel._has_markdown("## 标题\n正文"))
        self.assertTrue(FeishuChannel._has_markdown("- 列表项"))
        self.assertTrue(FeishuChannel._has_markdown("| 列1 | 列2 |"))
        self.assertTrue(FeishuChannel._has_markdown("> 引用"))
        self.assertTrue(FeishuChannel._has_markdown("```python\ncode\n```"))

    def test_markdown_to_card_schema_v2_passthrough(self):
        md = "# 标题\n正文\n\n| 列1 | 列2 |\n| --- | --- |\n| CPU | 90% |"
        card = FeishuChannel._markdown_to_card(md)
        self.assertEqual(card["schema"], "2.0")
        self.assertIn("elements", card["body"])
        contents = [el["content"] for el in card["body"]["elements"] if el["tag"] == "markdown"]
        joined = "\n".join(contents)
        # Card 2.0 markdown renders headers and tables natively: pass through
        self.assertIn("# 标题", joined)
        self.assertIn("| 列1 | 列2 |", joined)
        self.assertIn("| CPU | 90% |", joined)

    def test_markdown_to_card_code_fence_preserved(self):
        md = "before\n```python\nx = 1\n```\nafter"
        card = FeishuChannel._markdown_to_card(md)
        joined = "\n".join(el["content"] for el in card["body"]["elements"] if el["tag"] == "markdown")
        self.assertIn("```python\nx = 1\n```", joined)
        self.assertIn("before", joined)
        self.assertIn("after", joined)

    async def test_send_reply_markdown_uses_card(self):
        channel = self._make_channel()
        channel.client.post = AsyncMock(return_value=self._mock_resp({"code": 0, "data": {"message_id": "om_1"}}))
        msg_id = await channel.send_reply(chat_id="oc_1", text="**重点**内容")
        self.assertEqual(msg_id, "om_1")
        payload = channel.client.post.call_args.kwargs["json"]
        self.assertEqual(payload["msg_type"], "interactive")
        card = json.loads(payload["content"])
        self.assertEqual(card["schema"], "2.0")
        self.assertIn("elements", card["body"])

    async def test_send_reply_plain_text_becomes_card(self):
        channel = self._make_channel()
        channel.client.post = AsyncMock(return_value=self._mock_resp({"code": 0, "data": {"message_id": "om_2"}}))
        msg_id = await channel.send_reply(chat_id="oc_1", text="纯文本消息")
        self.assertEqual(msg_id, "om_2")
        payload = channel.client.post.call_args.kwargs["json"]
        self.assertEqual(payload["msg_type"], "interactive")
        card = json.loads(payload["content"])
        self.assertEqual(card["schema"], "2.0")
        self.assertIn("elements", card["body"])
        # Plain text is wrapped in a single markdown element
        contents = "\n".join(el.get("content", "") for el in card["body"]["elements"] if el["tag"] == "markdown")
        self.assertIn("纯文本消息", contents)

    async def test_send_reply_card_failure_falls_back_to_text(self):
        channel = self._make_channel()
        channel.client.post = AsyncMock(side_effect=[
            self._mock_resp({"code": 230002, "msg": "bad card"}),
            self._mock_resp({"code": 0, "data": {"message_id": "om_3"}}),
        ])
        msg_id = await channel.send_reply(chat_id="oc_1", text="## 标题\n正文")
        self.assertEqual(msg_id, "om_3")
        self.assertEqual(channel.client.post.call_count, 2)
        first = channel.client.post.call_args_list[0].kwargs["json"]
        second = channel.client.post.call_args_list[1].kwargs["json"]
        self.assertEqual(first["msg_type"], "interactive")
        self.assertEqual(second["msg_type"], "text")
        # Fallback keeps the raw text so the reply is never lost
        self.assertEqual(json.loads(second["content"])["text"], "## 标题\n正文")

    def test_should_fold_threshold(self):
        channel = self._make_channel()
        self.assertFalse(channel._should_fold("短消息"))
        long_text = "这是一段超过一百个字符的长文本，" * 10  # ~150 chars
        self.assertTrue(channel._should_fold(long_text))
        # Blockquotes don't count toward the fold measurement
        quote_only = "> " + "引用内容" * 30 + "\n\n> 更多引用"
        self.assertFalse(channel._should_fold(quote_only))

    def test_fold_cache_persists_across_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = GatewayConfig({
                "platform": "feishu",
                "feishu_app_id": "cli_mock_123",
                "feishu_app_secret": "sec_mock_456",
                "tuning": {"ipc_dir": tmpdir},
            })
            ch1 = FeishuChannel(cfg, AsyncMock())
            ch1._cache_fold("tokA", "全文内容A", "摘要A")
            # Simulate restart: brand-new channel instance, same ipc_dir
            ch2 = FeishuChannel(cfg, AsyncMock())
            self.assertIn("tokA", ch2._fold_cache)
            self.assertEqual(ch2._fold_cache["tokA"]["full"], "全文内容A")
            self.assertEqual(ch2._fold_cache["tokA"]["summary"], "摘要A")

    async def test_send_reply_long_text_folds_with_expand_button(self):
        channel = self._make_channel()
        channel.client.post = AsyncMock(return_value=self._mock_resp({"code": 0, "data": {"message_id": "om_4"}}))
        long_text = "核心结论先行。这是首段摘要内容。\n\n" + "后续详细内容。" * 30
        msg_id = await channel.send_reply(chat_id="oc_1", text=long_text)
        self.assertEqual(msg_id, "om_4")
        payload = channel.client.post.call_args.kwargs["json"]
        card = json.loads(payload["content"])
        buttons = [el for el in card["body"]["elements"] if el["tag"] == "button"]
        self.assertEqual(len(buttons), 1)
        self.assertIn("展开全文", buttons[0]["text"]["content"])
        self.assertEqual(buttons[0]["behaviors"][0]["type"], "callback")
        # Full text cached for in-place expansion
        tokens = [b["behaviors"][0]["value"]["token"] for b in buttons]
        self.assertIn(tokens[0], channel._fold_cache)
        self.assertEqual(channel._fold_cache[tokens[0]]["full"], long_text)

    async def test_send_reply_short_text_does_not_fold(self):
        channel = self._make_channel()
        channel.client.post = AsyncMock(return_value=self._mock_resp({"code": 0, "data": {"message_id": "om_5"}}))
        await channel.send_reply(chat_id="oc_1", text="短回复内容")
        payload = channel.client.post.call_args.kwargs["json"]
        card = json.loads(payload["content"])
        buttons = [el for el in card["body"]["elements"] if el["tag"] == "button"]
        self.assertEqual(buttons, [])
        self.assertEqual(channel._fold_cache, {})

    def test_fold_card_action_expand_and_collapse(self):
        from types import SimpleNamespace
        from groupconnect.channels.feishu import _HAS_LARK_SDK
        if not _HAS_LARK_SDK:
            self.skipTest("lark-oapi not installed")

        channel = self._make_channel()
        full_text = "首段。\n\n" + "正文详情。" * 40
        channel._fold_cache["tok123"] = {"full": full_text, "summary": "首段。"}

        handler = channel._build_event_handler()
        card_action_handler = handler._callback_processor_map["p2.card.action.trigger"].f
        self.assertIsNotNone(card_action_handler, "card action handler not registered")

        fake_data = SimpleNamespace(
            event=SimpleNamespace(
                action=SimpleNamespace(value={"action": "expand", "token": "tok123"}),
                operator=SimpleNamespace(open_id="ou_x"),
                context=SimpleNamespace(open_message_id="om_9", open_chat_id="oc_1"),
            )
        )
        resp = card_action_handler(fake_data)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.card.type, "raw")
        elements = resp.card.data["body"]["elements"]
        self.assertIn(full_text, elements[0]["content"])
        collapse_btn = [el for el in elements if el["tag"] == "button"][0]
        self.assertEqual(collapse_btn["behaviors"][0]["value"]["action"], "collapse")

        fake_data.event.action.value = {"action": "collapse", "token": "tok123"}
        resp2 = card_action_handler(fake_data)
        self.assertIn("首段。", resp2.card.data["body"]["elements"][0]["content"])
        expand_btn = [el for el in resp2.card.data["body"]["elements"] if el["tag"] == "button"][0]
        self.assertEqual(expand_btn["behaviors"][0]["value"]["action"], "expand")

    def test_fold_card_action_invalid_token_shows_toast(self):
        from types import SimpleNamespace
        from groupconnect.channels.feishu import _HAS_LARK_SDK
        if not _HAS_LARK_SDK:
            self.skipTest("lark-oapi not installed")

        channel = self._make_channel()
        handler = channel._build_event_handler()
        card_action_handler = handler._callback_processor_map["p2.card.action.trigger"].f
        fake_data = SimpleNamespace(
            event=SimpleNamespace(
                action=SimpleNamespace(value={"action": "expand", "token": "missing"}),
            )
        )
        resp = card_action_handler(fake_data)
        self.assertIsNotNone(resp.toast)
        self.assertIn("失效", resp.toast.content)


if __name__ == "__main__":
    unittest.main()

