import os
import unittest

from groupconnect.core.relay import CrossBotRelay
from groupconnect.routing import AutonomousConfig, AutonomousController


class TestAutonomousRouting(unittest.TestCase):
    def setUp(self):
        self.cfg = AutonomousConfig({
            "enabled": True,
            "arbiter_bot": "primary_bot",
            "ipc_dir": "/tmp/test_ipc",
            "windows": {
                "immediate_secs": 1.0,
                "silence_secs": 4.0
            },
            "context": {
                "window_size": 5
            },
            "aliases": {
                "primary_bot": ["assistant", "bot"],
                "ops_bot": ["ops", "helper"]
            },
            "classifier": {
                "active": "typesafe",
                "confidence_threshold": 0.8,
                "parallel_threshold": 0.6,
                "daily_budget": 800,
                "providers": {
                    "typesafe": {
                        "engine": "jev",
                        "model": "jev-latest",
                        "api_key_env": "JEV_API_KEY",
                        "timeout_ms": 5000
                    },
                    "google_ai_studio": {
                        "engine": "gemini",
                        "model": "gemini-2.5-flash-lite",
                        "api_key_env": "GEMINI_ROUTER_API_KEY",
                        "timeout_ms": 3000
                    }
                }
            },
            "roles": {
                "primary_bot": "Home automation, device control, finance, objective data lookup, alarms and scheduling.",
                "ops_bot": "Travel, leisure, dining recommendations, entertainment, and general life assistance."
            },
            "allowed_chat_ids": [-1001234567890]
        })
        self.relay = CrossBotRelay("primary_bot", "Primary", ipc_dir="/tmp/test_ipc")
        self.ctrl = AutonomousController(
            bot_username="primary_bot",
            cfg=self.cfg,
            relay=self.relay,
            dispatch=lambda d: None,
            context_summary_fn=lambda c, m, w: ""
        )

    def test_config_loaded(self):
        self.assertTrue(self.cfg.enabled)
        self.assertEqual(self.cfg.arbiter_bot, "primary_bot")
        self.assertTrue(self.ctrl.is_arbiter)
        self.assertEqual(self.cfg.immediate_secs, 1.0)
        self.assertEqual(self.cfg.silence_secs, 4.0)

    def test_noise_filter(self):
        # Empty or standard noise strings
        self.assertTrue(self.cfg.is_noise(""))
        self.assertTrue(self.cfg.is_noise("   "))
        self.assertTrue(self.cfg.is_noise("好的"))
        self.assertTrue(self.cfg.is_noise("收到！"))
        self.assertTrue(self.cfg.is_noise("ok"))
        self.assertTrue(self.cfg.is_noise("???"))
        self.assertTrue(self.cfg.is_noise("/stop@guaguahome_fun_bot"))
        self.assertTrue(self.cfg.is_noise("/restart"))
        # Meaningful text should not be filtered
        self.assertFalse(self.cfg.is_noise("帮我查一下明天的天气"))

    def test_alias_matching(self):
        # Direct alias match
        target = self.cfg.alias_hit("assistant 帮我查天气")
        self.assertEqual(target, "primary_bot")

        # Self-reference should be detected by alias_self_reference
        self.assertTrue(self.cfg.alias_self_reference("call me assistant"))
        self.assertTrue(self.cfg.alias_self_reference("I am assistant"))
        self.assertFalse(self.cfg.alias_self_reference("assistant please check this"))

        # Synchronous evaluation bypass
        decision = self.ctrl.arbiter.evaluate_sync("assistant 帮我查天气", "Alice")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_bot"], "primary_bot")
        self.assertEqual(decision["urgency"], "immediate")

    def test_single_alias_bypasses_to_classifier(self):
        self.cfg.aliases = {
            "bot_a": ["alpha", "小迷妹"],
            "bot_b": ["beta", "管家"]
        }

        # Single bot hit -> bypass (unchanged behavior)
        decision = self.ctrl.arbiter.evaluate_sync("alpha please check this", "Alice")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_bot"], "bot_a")
        self.assertEqual(decision["urgency"], "immediate")

        decision = self.ctrl.arbiter.evaluate_sync("beta please check this", "Alice")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_bot"], "bot_b")

    def test_multi_alias_defers_to_classifier(self):
        self.cfg.aliases = {
            "bot_a": ["alpha", "小迷妹"],
            "bot_b": ["beta", "管家"]
        }

        # Multiple bots hit -> defer to classifier (return None)
        decision = self.ctrl.arbiter.evaluate_sync("alpha please ask beta to check this", "Alice")
        self.assertIsNone(decision)

        decision = self.ctrl.arbiter.evaluate_sync("beta please ask alpha to check this", "Alice")
        self.assertIsNone(decision)

        # Multi-alias self-referential banter also defers (not auto-drop)
        decision = self.ctrl.arbiter.evaluate_sync("小迷妹给蓉汇报，最大的问题是管家", "Alice")
        self.assertIsNone(decision)

    def test_alias_hits_uses_earliest_position_across_aliases(self):
        # Regression: the same bot matched by MULTIPLE aliases must use the
        # earliest TEXT position, not the first alias in the registration list.
        self.cfg.aliases = {
            "bot_a": ["管家", "老铁"],
            "bot_b": ["小迷妹"]
        }
        # "老铁" (pos 0, bot_a) precedes "小迷妹" (bot_b); "管家" (later) must
        # not shadow "老铁" when computing bot_a's earliest position.
        text = "老铁和小迷妹聊下，管家听着"
        self.assertEqual(self.cfg.alias_hit(text), "bot_a")
        hits = self.cfg.alias_hits(text)
        self.assertEqual(hits, ["bot_a", "bot_b"])

    def test_observer_accepts_explicit_target_bots(self):
        import asyncio
        from groupconnect.routing.router import AutonomousObserver

        async def run():
            obs = AutonomousObserver("primary_bot", self.cfg, lambda d: None)
            obs.on_decision({"target_bot": "primary_bot", "target_bots": ["primary_bot", "ops_bot"], "urgency": "immediate", "chat_id": 123})
            self.assertIn(123, obs.pending)
            obs._cancel(123)

        asyncio.run(run())

    def test_classifier_registry(self):
        # Self-describing registry: active switch + per-provider params.
        self.assertEqual(self.cfg.active_provider, "typesafe")
        self.assertIn("typesafe", self.cfg.providers)
        self.assertIn("google_ai_studio", self.cfg.providers)
        self.assertEqual(self.cfg.engine, "jev")
        self.assertEqual(self.cfg.model, "jev-latest")
        self.assertEqual(self.cfg.api_key, os.environ.get("JEV_API_KEY", ""))

    def test_classifier_providers_config(self):
        import json
        import tempfile

        cfg_json = {"autonomous": {
            "classifier": {
                "active": "typesafe",
                "providers": {
                    "typesafe": {
                        "engine": "jev",
                        "model": "jev-custom",
                        "api_key_env": "JEV_API_KEY",
                        "timeout_ms": 5000,
                    }
                },
            }
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            self.assertEqual(cfg.active_provider, "typesafe")
            self.assertEqual(cfg.engine, "jev")
            self.assertEqual(cfg.model, "jev-custom")

    def test_classifier_active_missing_fails_closed(self):
        import json
        import tempfile

        # active points at an unregistered provider -> empty params, no key
        cfg_json = {"autonomous": {"classifier": {
            "active": "nonexistent",
            "providers": {"typesafe": {"engine": "jev", "model": "m"}}
        }}}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            self.assertEqual(cfg.active_provider, "nonexistent")
            self.assertEqual(cfg.model, "")
            self.assertEqual(cfg.api_key, "")

    def test_jev_and_llm_use_inline_rules_overrides(self):
        from groupconnect.routing.router import AutonomousArbiter

        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {"bot_a": "RoleA"},
            "rules": {
                "immediate": "IMM {bot}|{role}",
                "wait": "WAIT {bot}",
                "drop": "DROP_CUSTOM",
                "group": "GRP_CUSTOM",
            },
        })
        arb = AutonomousArbiter(cfg)
        criteria, jev_map, group = arb._jev_criteria()
        self.assertEqual(criteria["bot_a_immediate"], "IMM bot_a|RoleA")
        self.assertEqual(criteria["bot_a_wait"], "WAIT bot_a")
        self.assertEqual(criteria["none_drop"], "DROP_CUSTOM")
        self.assertEqual(group, "GRP_CUSTOM")
        self.assertEqual(jev_map["none_drop"], ("none", "drop"))
        # LLM instructions must also include the inline overrides
        instructions = arb._load_rules_instructions()
        self.assertIn("Group-Specific Overrides:", instructions)
        self.assertIn("DROP_CUSTOM", instructions)

    def test_jev_criteria_falls_back_to_defaults(self):
        from groupconnect.routing.router import (
            AutonomousArbiter, DEFAULT_IMMEDIATE_CRITERIA, DEFAULT_DROP_CRITERIA,
        )

        # Config with no custom rules -> built-in defaults kick in
        arb = AutonomousArbiter(self.cfg)
        criteria, _, _ = arb._jev_criteria()
        self.assertEqual(criteria["none_drop"], DEFAULT_DROP_CRITERIA)
        bot = next(iter(self.cfg.roles))
        self.assertEqual(
            criteria[f"{bot}_immediate"],
            DEFAULT_IMMEDIATE_CRITERIA.replace("{bot}", bot).replace("{role}", self.cfg.roles[bot]),
        )

    def test_jev_parallel_templates(self):
        from groupconnect.routing.router import AutonomousArbiter

        # Fallback to default
        arb = AutonomousArbiter(self.cfg)
        pt = arb._jev_parallel_templates()
        self.assertIn("primary_bot", pt)
        self.assertIn("Home automation", pt["primary_bot"])

        # Custom from inline zero_at.rules
        cfg = AutonomousConfig({
            "roles": {"bot_a": "RoleA", "bot_b": "RoleB"},
            "rules": {"parallel": "PARALLEL {bot} as {role}"},
        })
        arb2 = AutonomousArbiter(cfg)
        pt2 = arb2._jev_parallel_templates()
        self.assertEqual(pt2["bot_a"], "PARALLEL bot_a as RoleA")
        self.assertEqual(pt2["bot_b"], "PARALLEL bot_b as RoleB")

    def test_jev_classify_choice_and_noul_parallel(self):
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA", "bot_b": "RoleB", "bot_c": "RoleC"},
            "classifier": {
                "active": "typesafe",
                "providers": {
                    "typesafe": {
                        "engine": "jev",
                        "model": "jev-latest",
                        "api_key": "test_key"
                    }
                }
            },
            "confidence_threshold": 0.6,
            "parallel_threshold": 0.6,
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            arb = AutonomousArbiter(cfg)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "answers": {
                    "routing": {
                        "type": "choice",
                        "choice": "bot_a_immediate",
                        "confidence": 0.95,
                        "probabilities": {"bot_a_immediate": 0.95, "none_drop": 0.05},
                    },
                    "parallel_bot_b": {
                        "type": "noul",
                        "noul": 0.88,
                    },
                    "parallel_bot_c": {
                        "type": "noul",
                        "noul": 0.12,
                    },
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Bot A and Bot B look at this", "Alice", "")
                    self.assertEqual(res["target_bot"], "bot_a")
                    self.assertEqual(res["target_bots"], ["bot_a", "bot_b"])
                    self.assertEqual(res["urgency"], "immediate")

            asyncio.run(run())

    def test_jev_classify_fail_closed_ignores_noul(self):
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA", "bot_b": "RoleB"},
            "classifier": {
                "active": "typesafe",
                "providers": {
                    "typesafe": {
                        "engine": "jev",
                        "model": "jev-latest",
                        "api_key": "test_key"
                    }
                }
            },
            "confidence_threshold": 0.6,
            "parallel_threshold": 0.6,
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            arb = AutonomousArbiter(cfg)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "answers": {
                    "routing": {
                        "type": "choice",
                        "choice": "none_drop",
                        "confidence": 0.9,
                        "probabilities": {"none_drop": 0.9, "bot_a_immediate": 0.1},
                    },
                    "parallel_bot_b": {
                        "type": "noul",
                        "noul": 0.99,
                    },
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Spouse talk", "Alice", "")
                    self.assertEqual(res["target_bot"], "none")
                    self.assertEqual(res["target_bots"], [])
                    self.assertEqual(res["urgency"], "drop")

            asyncio.run(run())

    def test_observer_target_bots_subset(self):
        import asyncio
        from groupconnect.routing.router import AutonomousObserver

        async def run():
            dispatched = []
            obs_b = AutonomousObserver("bot_b", self.cfg, lambda d: dispatched.append("b"))
            obs_c = AutonomousObserver("bot_c", self.cfg, lambda d: dispatched.append("c"))

            dec = {
                "target_bot": "bot_a",
                "target_bots": ["bot_a", "bot_b"],
                "urgency": "immediate",
                "chat_id": 456,
            }
            obs_b.on_decision(dec)
            obs_c.on_decision(dec)

            self.assertIn(456, obs_b.pending)
            self.assertNotIn(456, obs_c.pending)
            obs_b._cancel(456)

        asyncio.run(run())

    def test_evaluate_sync_target_bots(self):
        # Noise
        d_noise = self.ctrl.arbiter.evaluate_sync("好的", "Alice")
        self.assertEqual(d_noise["target_bots"], [])
        self.assertEqual(d_noise["target_bot"], "none")

        # Alias bypass
        d_alias = self.ctrl.arbiter.evaluate_sync("assistant 帮我查天气", "Alice")
        self.assertEqual(d_alias["target_bots"], ["primary_bot"])
        self.assertEqual(d_alias["target_bot"], "primary_bot")

    def test_llm_classify_openai_compatible(self):
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA", "bot_b": "RoleB", "bot_c": "RoleC"},
            "classifier": {
                "engine": "openai",
                "model": "deepseek-chat",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "test_key",
            },
            "confidence_threshold": 0.7,
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            self.assertEqual(cfg.engine, "openai")
            self.assertEqual(cfg.base_url, "https://api.deepseek.com/v1")
            arb = AutonomousArbiter(cfg)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{
                    "message": {
                        "content": '```json\n{"target_bots": ["bot_a", "bot_b"], "target_bot": "bot_a", "urgency": "immediate", "confidence": 0.92}\n```'
                    }
                }]
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp) as mock_post:
                    res = await arb.classify("Bot A and Bot B check this", "Alice", "")
                    self.assertEqual(res["target_bot"], "bot_a")
                    self.assertEqual(res["target_bots"], ["bot_a", "bot_b"])
                    self.assertEqual(res["urgency"], "immediate")
                    self.assertEqual(mock_post.call_args[0][0], "https://api.deepseek.com/v1/chat/completions")

            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()


