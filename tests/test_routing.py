import asyncio
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

    def test_resume_decision_dispatches_without_grace_window(self):
        """Resume re-dispatches are historical replays: they must not arm the
        cancellable per-chat window, and batch members must not eat each other."""
        import asyncio
        from groupconnect.routing.router import AutonomousObserver

        async def run():
            dispatched = []

            async def spy(decision):
                dispatched.append(decision.get("msg_id"))

            obs = AutonomousObserver("primary_bot", self.cfg, spy)
            base = {
                "target_bot": "primary_bot", "target_bots": ["primary_bot"],
                "urgency": "wait_silence", "chat_id": 123, "sender": "Zheng Ma",
            }
            obs.on_decision({**base, "msg_id": 1, "is_resume": True})
            obs.on_decision({**base, "msg_id": 2, "is_resume": True})
            self.assertNotIn(123, obs.pending)  # no cancellable window armed
            await asyncio.sleep(0.05)  # let create_task(dispatch) settle
            self.assertEqual(sorted(dispatched), [1, 2])  # neither sibling ate the other
            # Live decisions still arm the grace window (regression guard)
            obs.on_decision({**base, "msg_id": 3})
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
        from groupconnect.routing.router import (
            AutonomousArbiter, DEFAULT_DROP_CRITERIA, DEFAULT_GROUP_DESCRIPTION,
        )

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
        self.assertEqual(criteria["immediate"], "IMM {bot}|{role}")
        self.assertEqual(criteria["wait"], "WAIT {bot}")
        self.assertEqual(criteria["drop"], "DROP_CUSTOM")
        self.assertEqual(group, "GRP_CUSTOM")
        self.assertEqual(jev_map["drop"], ("none", "drop"))
        # LLM instructions must perform true in-place replacement (default wording gone)
        instructions = arb._load_rules_instructions()
        self.assertIn("DROP_CUSTOM", instructions)
        self.assertIn("GRP_CUSTOM", instructions)
        self.assertNotIn(DEFAULT_DROP_CRITERIA, instructions)
        self.assertNotIn(DEFAULT_GROUP_DESCRIPTION, instructions)

        # Jev Choice instructions: only {group} injected; criteria texts live
        # exclusively in the criteria object (no duplicate tokens)
        choice_inst = arb._load_choice_instructions()
        self.assertIn("GRP_CUSTOM", choice_inst)
        self.assertNotIn("DROP_CUSTOM", choice_inst)
        self.assertNotIn("IMM {bot}|{role}", choice_inst)
        self.assertNotIn(DEFAULT_DROP_CRITERIA, choice_inst)
        self.assertNotIn(DEFAULT_GROUP_DESCRIPTION, choice_inst)

    def test_jev_criteria_falls_back_to_defaults(self):
        from groupconnect.routing.router import (
            AutonomousArbiter, DEFAULT_IMMEDIATE_CRITERIA, DEFAULT_DROP_CRITERIA,
        )

        # Config with no custom rules -> built-in defaults kick in
        arb = AutonomousArbiter(self.cfg)
        criteria, _, _ = arb._jev_criteria()
        self.assertEqual(criteria["drop"], DEFAULT_DROP_CRITERIA)
        self.assertEqual(criteria["immediate"], DEFAULT_IMMEDIATE_CRITERIA)

    def test_jev_assignment_templates(self):
        from groupconnect.routing.router import AutonomousArbiter

        # Fallback to default
        arb = AutonomousArbiter(self.cfg)
        pt = arb._jev_assignment_templates()
        self.assertIn("primary_bot", pt)
        self.assertIn("Home automation", pt["primary_bot"])

        # Custom from inline zero_at.rules (new 'assignment' slot)
        cfg = AutonomousConfig({
            "roles": {"bot_a": "RoleA", "bot_b": "RoleB"},
            "rules": {"assignment": "NEEDS {bot} as {role}"},
        })
        arb2 = AutonomousArbiter(cfg)
        pt2 = arb2._jev_assignment_templates()
        self.assertEqual(pt2["bot_a"], "NEEDS bot_a as RoleA")
        self.assertEqual(pt2["bot_b"], "NEEDS bot_b as RoleB")

    def test_jev_classify_choice_and_noul_multi_bot(self):
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
                        "choice": "immediate",
                        "confidence": 0.95,
                    },
                    "assignment_bot_a": {
                        "type": "noul",
                        "noul": 0.88,
                    },
                    "assignment_bot_b": {
                        "type": "noul",
                        "noul": 0.85,
                    },
                    "assignment_bot_c": {
                        "type": "noul",
                        "noul": 0.12,
                    },
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Bot A and Bot B look at this", "Alice", "")
                    # Choice=immediate, Noul A=0.88>=0.40, Noul B=0.85>=0.40, C=0.12<0.40
                    self.assertEqual(res["target_bot"], "bot_a")
                    self.assertEqual(set(res["target_bots"]), {"bot_a", "bot_b"})
                    self.assertEqual(res["urgency"], "immediate")

            asyncio.run(run())

    def test_jev_classify_noul_rescues_choice_drop(self):
        """When Choice drops but Noul detects a bot's domain, rescue with wait_silence."""
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
                        "choice": "drop",
                        "confidence": 0.9,
                    },
                    "assignment_bot_a": {"type": "noul", "noul": 0.10},
                    "assignment_bot_b": {"type": "noul", "noul": 0.99},
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Spouse talk", "Alice", "")
                    # Noul rescues: bot_b 0.99 >= 0.60 (strict threshold when Choice=drop)
                    self.assertEqual(res["target_bot"], "bot_b")
                    self.assertEqual(res["target_bots"], ["bot_b"])
                    # Rescue uses wait_silence (4s grace), NOT immediate
                    self.assertEqual(res["urgency"], "wait_silence")

            asyncio.run(run())

    def test_jev_classify_drop_when_choice_and_noul_both_fail(self):
        """True fail-closed: Choice drops AND Noul finds nothing -> drop."""
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
                        "choice": "drop",
                        "confidence": 0.9,
                    },
                    "assignment_bot_a": {"type": "noul", "noul": 0.2},
                    "assignment_bot_b": {"type": "noul", "noul": 0.3},
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Nice weather today", "Alice", "")
                    self.assertEqual(res["target_bot"], "none")
                    self.assertEqual(res["target_bots"], [])
                    self.assertEqual(res["urgency"], "drop")
                    self.assertEqual(res["confidence"], 0.0)

            asyncio.run(run())

    def test_jev_classify_choice_wait_yields_wait_silence(self):
        """Choice 'wait' produces urgency 'wait_silence' with candidate bots."""
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
                    "routing": {"type": "choice", "choice": "wait", "confidence": 0.88},
                    "assignment_bot_a": {"type": "noul", "noul": 0.75},
                    "assignment_bot_b": {"type": "noul", "noul": 0.10},
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Any book recommendations?", "Alice", "")
                    self.assertEqual(res["target_bot"], "bot_a")
                    self.assertEqual(res["target_bots"], ["bot_a"])
                    self.assertEqual(res["urgency"], "wait_silence")
                    self.assertEqual(res["confidence"], 0.75)

            asyncio.run(run())

    def test_jev_classify_candidate_sorting_preserves_score_order(self):
        """target_bots must be ordered by Noul score descending, not config dict order."""
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        # bot_a defined before bot_b in roles
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
                    "routing": {"type": "choice", "choice": "immediate", "confidence": 0.90},
                    "assignment_bot_a": {"type": "noul", "noul": 0.70},
                    "assignment_bot_b": {"type": "noul", "noul": 0.95},
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Both check this", "Alice", "")
                    # bot_b has higher score (0.95 > 0.70), must be first
                    self.assertEqual(res["target_bot"], "bot_b")
                    self.assertEqual(res["target_bots"], ["bot_b", "bot_a"])
                    self.assertEqual(res["urgency"], "immediate")
                    self.assertEqual(res["confidence"], 0.95)

            asyncio.run(run())

    def test_jev_classify_malformed_json_fails_closed_drop(self):
        """Malformed answers structure safely fails closed to drop."""
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA"},
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
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            arb = AutonomousArbiter(cfg)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = ValueError("Invalid JSON")

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Hello", "Alice", "")
                    self.assertEqual(res["target_bot"], "none")
                    self.assertEqual(res["target_bots"], [])
                    self.assertEqual(res["urgency"], "drop")

            asyncio.run(run())

    def test_jev_classify_choice_immediate_noul_fails_all_fallback_dispatch(self):
        """Choice says immediate (human urgency) but no bot matches Noul ->
        fallback dispatch to the highest-scoring bot with wait_silence grace.
        (Behavior change vs. pre-fallback: was a silent drop.)"""
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
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "groupconnect.yaml")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            arb = AutonomousArbiter(cfg)

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            # Choice is high immediate (0.95), but both bots fail relaxed threshold (0.40)
            mock_resp.json.return_value = {
                "answers": {
                    "routing": {"type": "choice", "choice": "immediate", "confidence": 0.95},
                    "assignment_bot_a": {"type": "noul", "noul": 0.15},
                    "assignment_bot_b": {"type": "noul", "noul": 0.22},
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Hurry up, the taxi is waiting downstairs!", "Alice", "")
                    # Fallback: highest scorer bot_b (0.22) takes it with wait_silence
                    self.assertEqual(res["target_bot"], "bot_b")
                    self.assertEqual(res["target_bots"], ["bot_b"])
                    self.assertEqual(res["urgency"], "wait_silence")
                    self.assertAlmostEqual(res["confidence"], 0.22)

            asyncio.run(run())

    def test_jev_classify_explicit_null_answers_drop(self):
        """Answers containing explicit null for keys are handled gracefully."""
        import asyncio
        from unittest.mock import patch, MagicMock
        import tempfile, json
        from groupconnect.routing.router import AutonomousArbiter

        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA"},
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
                    "routing": None,
                    "assignment_bot_a": None,
                }
            }

            async def run():
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res = await arb.classify("Hello", "Alice", "")
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
                    sent_prompt = mock_post.call_args[1]["json"]["messages"][0]["content"]
                    self.assertIn("MULTI-BOT ASSIGNMENT & DISPATCH", sent_prompt)
                    self.assertNotIn("YOUR SCOPE — You judge ONLY the response TIMING", sent_prompt)

            asyncio.run(run())

    def test_jev_prefix_collision_prevention(self):
        """Bots sharing name prefix (e.g. 'bot' and 'bot_helper') must not bleed probabilities.
        With orthogonal Choice (3-option, no bot identity), prefix collision is moot
        for Choice. Noul handles per-bot assignment independently."""
        from unittest.mock import MagicMock, patch
        from groupconnect.routing.router import AutonomousArbiter

        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {
                "bot": "General Bot",
                "bot_helper": "Specialist Helper",
            },
            "classifier": {
                "engine": "jev",
                "confidence_threshold": 0.8,
                "providers": {
                    "typesafe": {
                        "api_key": "dummy_key",
                        "engine": "jev"
                    }
                }
            }
        })
        arb = AutonomousArbiter(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "answers": {
                "routing": {
                    "choice": "immediate",
                    "confidence": 0.85,
                },
                "assignment_bot": {"type": "noul", "noul": 0.10},
                "assignment_bot_helper": {"type": "noul", "noul": 0.90},
            }
        }

        async def run():
            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                res = await arb.classify("Ask helper for assistance", "Alice", "")
                # Choice=immediate, threshold=0.80*2/3=0.53
                # bot_helper Noul=0.90 >= 0.53, bot Noul=0.10 < 0.53
                self.assertEqual(res["target_bot"], "bot_helper")
                self.assertEqual(res["urgency"], "immediate")
                self.assertAlmostEqual(res["confidence"], 0.9)

        asyncio.run(run())

    def test_fallback_dispatch_when_choice_responds_but_nobody_claims(self):
        """Choice says respond but no bot passes the relaxed Noul threshold ->
        fallback dispatch to the highest-scoring bot with wait_silence grace.
        Roles stay naturally scoped; the mechanism closes the coverage."""
        import asyncio
        from unittest.mock import patch, MagicMock
        from groupconnect.routing.router import AutonomousArbiter

        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {"bot_a": "Domain A", "bot_b": "Domain B"},
            "classifier": {
                "engine": "jev",
                "confidence_threshold": 0.8,
                "providers": {"typesafe": {"api_key": "dummy_key", "engine": "jev"}},
            }
        })
        arb = AutonomousArbiter(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "answers": {
                "routing": {"choice": "immediate", "confidence": 0.85},
                "assignment_bot_a": {"noul": 0.31},
                "assignment_bot_b": {"noul": 0.05},
            }
        }

        async def run():
            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                res = await arb.classify("聊聊架构", "Alice", "")
                # relaxed threshold = 0.8 * 2/3 ≈ 0.53; nobody claims
                # fallback: highest scorer bot_a (0.31) with wait_silence grace
                self.assertEqual(res["target_bot"], "bot_a")
                self.assertEqual(res["target_bots"], ["bot_a"])
                self.assertEqual(res["urgency"], "wait_silence")
                self.assertAlmostEqual(res["confidence"], 0.31)

        asyncio.run(run())

    def test_fallback_picks_highest_scorer_not_config_order(self):
        """Fallback dispatch must pick the highest-scoring bot by score order,
        not the first bot in the roles dict."""
        import asyncio
        from unittest.mock import patch, MagicMock
        from groupconnect.routing.router import AutonomousArbiter

        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {"bot_a": "Domain A", "bot_b": "Domain B"},
            "classifier": {
                "engine": "jev",
                "confidence_threshold": 0.8,
                "providers": {"typesafe": {"api_key": "dummy_key", "engine": "jev"}},
            }
        })
        arb = AutonomousArbiter(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "answers": {
                "routing": {"choice": "wait", "confidence": 0.7},
                "assignment_bot_a": {"noul": 0.05},
                "assignment_bot_b": {"noul": 0.20},
            }
        }

        async def run():
            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                res = await arb.classify("随便聊聊", "Alice", "")
                self.assertEqual(res["target_bot"], "bot_b")
                self.assertEqual(res["urgency"], "wait_silence")
                self.assertAlmostEqual(res["confidence"], 0.2)

        asyncio.run(run())

    def test_choice_drop_with_no_claim_stays_silent_no_fallback(self):
        """Couple-chat firewall: Choice says drop AND nobody claims -> true
        silence. Fallback must NEVER fire when Choice says drop."""
        import asyncio
        from unittest.mock import patch, MagicMock
        from groupconnect.routing.router import AutonomousArbiter

        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {"bot_a": "Domain A", "bot_b": "Domain B"},
            "classifier": {
                "engine": "jev",
                "confidence_threshold": 0.8,
                "providers": {"typesafe": {"api_key": "dummy_key", "engine": "jev"}},
            }
        })
        arb = AutonomousArbiter(cfg)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "answers": {
                "routing": {"choice": "drop", "confidence": 0.9},
                "assignment_bot_a": {"noul": 0.50},
                "assignment_bot_b": {"noul": 0.10},
            }
        }

        async def run():
            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                res = await arb.classify("晚上咱吃啥", "Alice", "")
                # strict threshold 0.8 -> nobody claims; Choice drop -> silence
                self.assertEqual(res["target_bot"], "none")
                self.assertEqual(res["target_bots"], [])
                self.assertEqual(res["urgency"], "drop")

        asyncio.run(run())


class TestUncertainDropInterpolation(unittest.TestCase):
    """An uncertain drop (low Choice confidence) must not strand a strong
    Noul claim: the Noul bar interpolates from strict toward relaxed as the
    drop's own certainty falls. A fully confident drop keeps the chitchat
    firewall at the strict bar. Live case (2026-09-25 21:28): third-person
    correction + rhetorical health question -> drop conf=0.28, top Noul 0.53,
    stranded between the strict bar and the fallback-dispatch path."""

    def _arb(self):
        from groupconnect.routing.router import AutonomousArbiter
        cfg = AutonomousConfig({
            "enabled": True,
            "roles": {"bot_a": "Domain A", "bot_b": "Domain B"},
            "classifier": {
                "engine": "jev",
                "confidence_threshold": 0.6,
                "providers": {"typesafe": {"api_key": "dummy_key", "engine": "jev"}},
            }
        })
        return AutonomousArbiter(cfg)

    def _run(self, arb, choice_conf, noul_a, noul_b, with_conf=True):
        import asyncio
        from unittest.mock import patch, MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        routing_ans = {"choice": "drop"}
        if with_conf:
            routing_ans["confidence"] = choice_conf
        mock_resp.json.return_value = {"answers": {
            "routing": routing_ans,
            "assignment_bot_a": {"noul": noul_a},
            "assignment_bot_b": {"noul": noul_b},
        }}

        async def go():
            with patch("httpx.AsyncClient.post", return_value=mock_resp):
                return await arb.classify("msg", "Alice", "")
        return asyncio.run(go())

    def test_uncertain_drop_moderate_claim_rescues(self):
        # Live case: conf=0.30 -> bar = 0.40 + 0.20*0.30 = 0.46; claim 0.53 clears
        res = self._run(self._arb(), 0.30, 0.20, 0.53)
        self.assertEqual(res["target_bot"], "bot_b")
        self.assertEqual(res["target_bots"], ["bot_b"])
        self.assertEqual(res["urgency"], "wait_silence")  # 4s grace, not immediate

    def test_certain_drop_moderate_claim_stays_silent(self):
        # Same claim strength, confident drop: bar = 0.40 + 0.20*0.95 = 0.59
        res = self._run(self._arb(), 0.95, 0.10, 0.55)
        self.assertEqual(res["target_bot"], "none")
        self.assertEqual(res["urgency"], "drop")

    def test_full_confidence_drop_keeps_strict_bar(self):
        # conf=1.0 -> bar == strict (0.60): pre-existing firewall unchanged
        res = self._run(self._arb(), 1.0, 0.10, 0.59)
        self.assertEqual(res["urgency"], "drop")
        res = self._run(self._arb(), 1.0, 0.10, 0.61)
        self.assertEqual(res["urgency"], "wait_silence")  # existing rescue path

    def test_out_of_range_confidence_is_clamped(self):
        # conf=1.5 must clamp to 1.0 -> strict bar, no accidental loosening
        res = self._run(self._arb(), 1.5, 0.10, 0.59)
        self.assertEqual(res["urgency"], "drop")

    def test_missing_confidence_uses_relaxed_floor(self):
        # No confidence field: maximum uncertainty -> relaxed bar (0.40)
        res = self._run(self._arb(), 0.0, 0.10, 0.45, with_conf=False)
        self.assertEqual(res["target_bot"], "bot_b")
        self.assertEqual(res["urgency"], "wait_silence")


class TestInflightTaskMarker(unittest.IsolatedAsyncioTestCase):
    """Immediate dispatches must surface an in-flight marker in the routing
    context until the bot's reply lands — otherwise same-sender follow-ups
    ('再加上两个鸡蛋') read like human small talk and get dropped."""

    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        self.SimpleNamespace = SimpleNamespace
        self.cfg = AutonomousConfig({
            "enabled": True,
            "arbiter_bot": "primary_bot",
            "ipc_dir": "/tmp/test_ipc",
            "aliases": {"primary_bot": ["assistant"]},
            "classifier": {
                "confidence_threshold": 0.8,
                "providers": {"typesafe": {"engine": "jev", "api_key": "dummy"}},
            },
            "roles": {"primary_bot": "Home automation and data lookup."},
            "allowed_chat_ids": [-1001234567890],
        })
        self.ctrl = AutonomousController(
            bot_username="primary_bot",
            cfg=self.cfg,
            relay=MagicMock(),
            dispatch=lambda d: None,
            context_summary_fn=lambda c, m, w: "",
        )

    def _msg(self, text, msg_id=200, sender="Alice"):
        return self.SimpleNamespace(
            chat_id=-1001234567890, chat_type="group", msg_id=msg_id,
            sender_name=sender, from_user={"is_bot": False}, text=text,
            is_bot_relay=False, attachments=None,
        )

    async def test_immediate_dispatch_records_inflight_marker(self):
        # Alias bypass -> immediate decision, zero classifier calls
        await self.ctrl.evaluate_and_publish(self._msg("assistant 帮我算一下热量"))
        marker = self.ctrl.inflight_marker(-1001234567890, [])
        self.assertIn("@primary_bot", marker)
        self.assertIn("Alice", marker)
        self.assertIn("not been posted yet", marker)

    async def test_drop_and_wait_do_not_record_inflight(self):
        from unittest.mock import AsyncMock, patch
        # Noise text -> L0 drop, early return before any recording
        await self.ctrl.evaluate_and_publish(self._msg("好的"))
        self.assertEqual(self.ctrl._inflight, {})
        # Classifier wait_silence decision -> not recorded
        with patch.object(self.ctrl.arbiter, "classify", AsyncMock(return_value={
            "target_bot": "primary_bot", "target_bots": ["primary_bot"],
            "urgency": "wait_silence", "confidence": 0.7, "source": "classifier",
        })):
            await self.ctrl.evaluate_and_publish(self._msg("帮我看看周末天气"))
        self.assertEqual(self.ctrl._inflight, {})

    async def test_bot_reply_lands_clears_marker(self):
        await self.ctrl.evaluate_and_publish(self._msg("assistant 查天气", msg_id=100))
        self.assertTrue(self.ctrl.inflight_marker(-1001234567890, []))
        # A bot message after the dispatched msg_id -> task answered
        buffer = [{"is_bot": True, "msg_id": 101, "sender": "Bot", "text": "done"}]
        self.assertEqual(self.ctrl.inflight_marker(-1001234567890, buffer), "")
        # Cleared permanently (record popped)
        self.assertEqual(self.ctrl.inflight_marker(-1001234567890, []), "")

    async def test_inflight_marker_expires_after_ttl(self):
        import time as _time
        await self.ctrl.evaluate_and_publish(self._msg("assistant 查天气", msg_id=100))
        self.ctrl._inflight[-1001234567890]["ts"] = _time.time() - 601
        self.assertEqual(self.ctrl.inflight_marker(-1001234567890, []), "")
        self.assertNotIn(-1001234567890, self.ctrl._inflight)

    async def test_engine_context_appends_marker(self):
        import tempfile
        import time as _time
        from groupconnect.core.config import GatewayConfig
        from groupconnect.core.context import ContextManager
        from groupconnect.engine import GroupConnectEngine

        engine = GroupConnectEngine(GatewayConfig({
            "platform": "telegram", "bot_token": "mock_token",
            "bot_username": "guaguahome_bot", "bot_name": "guaguahome",
            "allow_open_access": True,
        }))
        with tempfile.TemporaryDirectory() as tmp:
            engine.context_mgr = ContextManager(chat_logs_dir=tmp)
            engine.context_mgr.record_message(-1001234567890, "Alice", "帮我算一下热量", msg_id=200)
            engine.autonomous = self.ctrl
            self.ctrl._inflight[-1001234567890] = {
                "sender": "Alice", "msg_id": 200, "bot": "primary_bot", "ts": _time.time(),
            }
            ctx = engine._build_routing_context(-1001234567890, 0, 5)
            lines = ctx.split("\n")
            self.assertEqual(len(lines), 2)
            self.assertIn("[Alice]: 帮我算一下热量", lines[0])
            self.assertIn("@primary_bot", lines[1])
            self.assertIn("not been posted yet", lines[1])

    async def test_engine_context_flattens_and_widens_bot_lines(self):
        """Bot replies with newlines must render as ONE context line, and bot
        content must survive far past 120 chars (questions/advice in long
        replies are the anchors follow-up detection needs). Human entries
        keep the 120-char form."""
        import tempfile
        from groupconnect.core.config import GatewayConfig
        from groupconnect.core.context import ContextManager
        from groupconnect.engine import GroupConnectEngine

        engine = GroupConnectEngine(GatewayConfig({
            "platform": "telegram", "bot_token": "mock_token",
            "bot_username": "guaguahome_bot", "bot_name": "guaguahome",
            "allow_open_access": True,
        }))
        long_reply = (
            "开头寒暄。\n\n" + "分析段落，油泼面重油封胃。" * 100 + "\n\n末尾建议：严禁夜宵，多喝温水。"
        )
        self.assertGreater(len(long_reply), 1300)  # deep past the old 120-char cliff
        self.assertLess(len(long_reply), 2000)     # ...but inside the new cap
        with tempfile.TemporaryDirectory() as tmp:
            engine.context_mgr = ContextManager(chat_logs_dir=tmp)
            engine.context_mgr.record_message(
                -1001234567890, "Alice", "我不是有结石的征兆吗", msg_id=200)
            engine.context_mgr.record_message(
                -1001234567890, "Assistant Bot", long_reply, msg_id=201, is_bot_reply=True)
            ctx = engine._build_routing_context(-1001234567890, 0, 5)
            lines = ctx.split("\n")
            # Flattened: exactly one line per entry (no multi-line spill)
            self.assertEqual(len(lines), 2)
            self.assertIn("[Alice]: 我不是有结石的征兆吗", lines[0])
            bot_line = lines[1]
            self.assertTrue(bot_line.startswith("[Bot Assistant Bot]:"))
            # Content deep inside a long bot reply is visible to the classifier
            self.assertIn("末尾建议", bot_line)
            # Bot entries cap at 2000 chars (plus prefix), not 120
            self.assertLessEqual(len(bot_line), len("[Bot Assistant Bot]: ") + 2000)
            self.assertGreater(len(bot_line), len("[Bot Assistant Bot]: ") + 120)


if __name__ == "__main__":
    unittest.main()


