import unittest
from groupconnect.channels.telegram import TelegramChannel
from groupconnect.channels.feishu import FeishuChannel
from groupconnect.channels.wecom import WeComChannel
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


class TestChannels(unittest.TestCase):
    def test_channel_instantiations(self):
        # 1. Telegram
        cfg_tg = GatewayConfig({"platform": "telegram", "bot_token": "mock_token"})
        engine_tg = GroupConnectEngine(cfg_tg)
        self.assertIsInstance(engine_tg.channel, TelegramChannel)

        # 2. Feishu
        cfg_feishu = GatewayConfig({
            "platform": "feishu",
            "feishu_app_id": "cli_mock_123",
            "feishu_app_secret": "sec_mock_456"
        })
        engine_feishu = GroupConnectEngine(cfg_feishu)
        self.assertIsInstance(engine_feishu.channel, FeishuChannel)
        self.assertEqual(engine_feishu.channel.app_id, "cli_mock_123")

        # 3. WeCom
        cfg_wecom = GatewayConfig({
            "platform": "wecom",
            "wecom_corp_id": "ww_mock_corp",
            "wecom_corp_secret": "sec_mock_corp",
            "wecom_agent_id": "1000002"
        })
        engine_wecom = GroupConnectEngine(cfg_wecom)
        self.assertIsInstance(engine_wecom.channel, WeComChannel)
        self.assertEqual(engine_wecom.channel.corp_id, "ww_mock_corp")


if __name__ == "__main__":
    unittest.main()
