import unittest
from unittest.mock import AsyncMock, patch
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
            "bot_token": "mock_token",
            "auto_telegraph_threshold": 60
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
            reply_to_message_id=None
        )

    async def test_long_reply_auto_telegraph(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "auto_telegraph_threshold": 20
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
                reply_to_message_id=None
            )

    async def test_fallback_blockquote_uses_html(self):
        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock_token",
            "auto_telegraph_threshold": 20
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
                reply_to_message_id=None
            )


if __name__ == "__main__":
    unittest.main()
