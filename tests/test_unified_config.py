import os
import unittest
from groupconnect.core.config import GatewayConfig, expand_env_vars


class TestUnifiedConfig(unittest.TestCase):
    def tearDown(self):
        import shutil
        shutil.rmtree("./test_workspace", ignore_errors=True)

    def test_env_var_expansion(self):
        os.environ["GC_TEST_KEY"] = "my_secret_token"
        try:
            self.assertEqual(expand_env_vars("${GC_TEST_KEY}"), "my_secret_token")
            self.assertEqual(expand_env_vars("${NONEXISTENT_VAR:-fallback}"), "fallback")
            self.assertEqual(expand_env_vars("prefix_${GC_TEST_KEY}_suffix"), "prefix_my_secret_token_suffix")
        finally:
            os.environ.pop("GC_TEST_KEY", None)

    def test_unified_single_bot_schema(self):
        data = {
            "channel": {
                "platform": "telegram",
                "token": "123456:ABC-DEF",
            },
            "agent": {
                "engine": "codex",
                "workspace": "./test_workspace",
                "role": "Python expert",
            },
            "security": {
                "users": ["alice", "bob"],
                "groups": [-10012345],
            },
            "zero_at": True
        }
        cfg = GatewayConfig(data)
        self.assertEqual(cfg.platform, "telegram")
        self.assertEqual(cfg.bot_token, "123456:ABC-DEF")
        self.assertEqual(cfg.engine_type, "codex")
        self.assertIn("alice", cfg.allowed_usernames)
        self.assertIn(-10012345, cfg.allowed_chat_ids)
        self.assertIsNotNone(cfg.autonomous_config)
        self.assertTrue(cfg.autonomous_config.enabled)
        self.assertEqual(cfg.autonomous_config.silence_secs, 4.0)

    def test_unified_multi_bot_schema(self):
        data = {
            "channel": {
                "platform": "telegram",
            },
            "bots": [
                {
                    "name": "coder",
                    "username": "coder_bot",
                    "token": "token_1",
                    "agent": "codex",
                    "role": "Coding assistant",
                    "aliases": ["码农", "coder"],
                },
                {
                    "name": "reviewer",
                    "username": "reviewer_bot",
                    "token": "token_2",
                    "agent": "claude",
                    "role": "Code reviewer",
                    "aliases": ["评审"],
                }
            ],
            "security": {
                "users": ["admin"],
            },
            "zero_at": {
                "enabled": True,
            }
        }
        # Load bot 1
        cfg1 = GatewayConfig._merge_bot_entry(data, data["bots"][0])
        g1 = GatewayConfig(cfg1)
        self.assertEqual(g1.bot_username, "coder_bot")
        self.assertEqual(g1.bot_token, "token_1")
        self.assertEqual(g1.engine_type, "codex")
        self.assertEqual(g1.autonomous_config.arbiter_bot, "coder_bot")
        self.assertIn("coder_bot", g1.autonomous_config.roles)
        self.assertIn("reviewer_bot", g1.autonomous_config.roles)
        self.assertIn("码农", g1.autonomous_config.aliases["coder_bot"])

        # Load bot 2
        cfg2 = GatewayConfig._merge_bot_entry(data, data["bots"][1])
        g2 = GatewayConfig(cfg2)
        self.assertEqual(g2.bot_username, "reviewer_bot")
        self.assertEqual(g2.bot_token, "token_2")
        self.assertEqual(g2.engine_type, "claude")
        self.assertEqual(g2.autonomous_config.arbiter_bot, "coder_bot")

    def test_zero_at_thresholds_and_direct_file_load(self):
        import tempfile
        import yaml
        from groupconnect.routing.router import AutonomousConfig

        os.environ["GC_CLF_KEY"] = "test_clf_secret"
        try:
            doc = {
                "bots": [
                    {
                        "name": "bot_a",
                        "username": "bot_a_user",
                        "token": "t1",
                        "agent": "codex",
                        "role": "Role A",
                        "aliases": ["小A"],
                    },
                    {
                        "name": "bot_b",
                        "username": "bot_b_user",
                        "token": "t2",
                        "agent": "claude",
                        "role": "Role B",
                        "aliases": ["小B"],
                    },
                ],
                "zero_at": {
                    "enabled": True,
                    "confidence_threshold": 0.6,
                    "parallel_threshold": 0.65,
                    "classifier": {
                        "api_key": "${GC_CLF_KEY}",
                    },
                },
            }
            with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
                yaml.safe_dump(doc, tf)
                tmp_path = tf.name

            try:
                # 1. Load via GatewayConfig
                gcfg = GatewayConfig.from_file(tmp_path, bot_name="bot_a")
                self.assertAlmostEqual(gcfg.autonomous_config.confidence_threshold, 0.6)
                self.assertAlmostEqual(gcfg.autonomous_config.parallel_threshold, 0.65)
                self.assertEqual(gcfg.autonomous_config.api_key, "test_clf_secret")

                # 2. Load directly via AutonomousConfig(tmp_path)
                acfg = AutonomousConfig(tmp_path)
                self.assertAlmostEqual(acfg.confidence_threshold, 0.6)
                self.assertAlmostEqual(acfg.parallel_threshold, 0.65)
                self.assertEqual(acfg.api_key, "test_clf_secret")
                self.assertIn("bot_a_user", acfg.roles)
                self.assertIn("小A", acfg.aliases["bot_a_user"])
            finally:
                os.unlink(tmp_path)
        finally:
            os.environ.pop("GC_CLF_KEY", None)


if __name__ == "__main__":
    unittest.main()
