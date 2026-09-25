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
                self.assertEqual(gcfg.autonomous_config.api_key, "test_clf_secret")

                # 2. Load directly via AutonomousConfig(tmp_path)
                acfg = AutonomousConfig(tmp_path)
                self.assertAlmostEqual(acfg.confidence_threshold, 0.6)
                self.assertEqual(acfg.api_key, "test_clf_secret")
                self.assertIn("bot_a_user", acfg.roles)
                self.assertIn("小A", acfg.aliases["bot_a_user"])
            finally:
                os.unlink(tmp_path)
        finally:
            os.environ.pop("GC_CLF_KEY", None)

    def test_per_bot_platform_binding_and_cross_platform_isolation(self):
        import tempfile
        import time
        import yaml

        doc = {
            "bots": [
                {
                    "name": "tg_coder",
                    "username": "tg_coder_bot",
                    "platform": "telegram",
                    "token": "tg_tok_1",
                    "role": "TG Coding",
                    "aliases": ["码农"],
                    "agent": {"engine": "codex", "workspace": "./test_workspace"},
                },
                {
                    "name": "dc_helper",
                    "username": "dc_helper_bot",
                    "platform": "discord",
                    "token": "dc_tok_1",
                    "role": "Discord Helper",
                    "aliases": ["小助"],
                    "agent": {"engine": "claude", "workspace": "./test_workspace"},
                },
            ],
            "zero_at": {"enabled": True},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.safe_dump(doc, tf)
            tmp_path = tf.name

        try:
            g_tg = GatewayConfig.from_file(tmp_path, bot_name="tg_coder_bot")
            g_dc = GatewayConfig.from_file(tmp_path, bot_name="dc_helper_bot")

            self.assertEqual(g_tg.platform, "telegram")
            self.assertEqual(g_tg.bot_token, "tg_tok_1")
            self.assertEqual(g_tg.autonomous_config.arbiter_bot, "tg_coder_bot")
            self.assertEqual(set(g_tg.autonomous_config.roles.keys()), {"tg_coder_bot"})

            self.assertEqual(g_dc.platform, "discord")
            self.assertEqual(g_dc.bot_token, "dc_tok_1")
            self.assertEqual(g_dc.autonomous_config.arbiter_bot, "dc_helper_bot")
            self.assertEqual(set(g_dc.autonomous_config.roles.keys()), {"dc_helper_bot"})

            # Verify hot reload preserves platform isolation
            os.utime(tmp_path, (time.time() + 10, time.time() + 10))
            g_dc.autonomous_config.reload_if_modified()
            self.assertEqual(g_dc.autonomous_config.arbiter_bot, "dc_helper_bot")
            self.assertEqual(set(g_dc.autonomous_config.roles.keys()), {"dc_helper_bot"})
        finally:
            os.unlink(tmp_path)

    def test_per_workspace_agents_config_auto_inference(self):
        """When placed at <workspace>/.agents/groupconnect.yaml, workspace, souls_dir, and isolated ipc_dir auto-resolve."""
        import shutil
        import tempfile
        import yaml
        ws_root = tempfile.mkdtemp(prefix="gc_ws_test_")
        try:
            agents_dir = os.path.join(ws_root, ".agents")
            souls_dir = os.path.join(agents_dir, "souls")
            os.makedirs(souls_dir, exist_ok=True)
            cfg_path = os.path.join(agents_dir, "groupconnect.yaml")

            doc = {
                "bots": [
                    {
                        "id": "steward_bot",
                        "name": "管家",
                        "platform": "telegram",
                        "token": "tok_steward",
                        "role_summary": "智能家居与财务审计",
                        "agent": {"engine": "teleagent"},
                    }
                ],
                "security": {"allowed_chat_ids": [-10012345]},
                "zero_at": {"enabled": True},
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(doc, f)

            cfg = GatewayConfig.from_file(cfg_path, bot_name="steward_bot")
            self.assertEqual(cfg.bot_username, "steward_bot")
            self.assertEqual(cfg.workspace_dir, os.path.abspath(ws_root))
            self.assertEqual(cfg.souls_dir, os.path.abspath(souls_dir))
            self.assertTrue(cfg.ipc_dir.endswith(os.path.basename(ws_root)))
            self.assertEqual(cfg.autonomous_config.roles.get("steward_bot"), "智能家居与财务审计")
        finally:
            shutil.rmtree(ws_root, ignore_errors=True)

    def test_autonomous_config_bot_id_fallback(self):
        import tempfile
        import yaml
        from groupconnect.routing.router import AutonomousConfig

        doc = {
            "bots": [
                {
                    "id": "my_bot_id",
                    "role_summary": "Summary role",
                    "aliases": ["id_bot"],
                },
                {
                    "name": "second_bot",
                    "role": "Second role",
                }
            ],
            "zero_at": {
                "enabled": True,
            }
        }
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.safe_dump(doc, tf)
            tmp_path = tf.name

        try:
            acfg = AutonomousConfig(tmp_path)
            self.assertEqual(acfg.arbiter_bot, "my_bot_id")
            self.assertEqual(acfg.roles.get("my_bot_id"), "Summary role")
            self.assertIn("id_bot", acfg.aliases.get("my_bot_id", []))
            self.assertEqual(acfg.roles.get("second_bot"), "Second role")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_bot_resolution_with_none_username_and_id_fallback(self):
        """When username is None or empty, GatewayConfig safely falls back to id without AttributeError."""
        import tempfile
        import yaml
        from groupconnect.core.config import GatewayConfig

        doc = {
            "platform": "telegram",
            "token": "test_token_123",
            "bots": [
                {
                    "id": "my_worker",
                    "username": None,
                    "name": "WorkerBot",
                    "role": "Background Worker",
                },
                {
                    "name": "SecondBot",
                    "id": None,
                    "username": "second_user",
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as tf:
            yaml.safe_dump(doc, tf)
            tmp_path = tf.name

        try:
            cfg = GatewayConfig.from_file(tmp_path, bot_name="my_worker")
            self.assertEqual(cfg.bot_username, "my_worker")
            self.assertEqual(cfg.bot_name, "WorkerBot")

            cfg2 = GatewayConfig.from_file(tmp_path, bot_name="SecondBot")
            self.assertEqual(cfg2.bot_username, "second_user")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
