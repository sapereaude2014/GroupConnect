import os
import unittest

from groupconnect.core.relay import CrossBotRelay
from groupconnect.routing import AutonomousConfig, AutonomousController


class TestAutonomousRouting(unittest.TestCase):
    def setUp(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.example_cfg_path = os.path.join(repo_root, "autonomous_config.example.json")
        self.cfg = AutonomousConfig(self.example_cfg_path)
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

    def test_multiple_aliases_first_mentioned_wins(self):
        self.cfg.aliases = {
            "bot_a": ["alpha", "小迷妹"],
            "bot_b": ["beta", "管家"]
        }

        # Single bot hit
        target1 = self.cfg.alias_hit("alpha please check this")
        self.assertEqual(target1, "bot_a")

        target2 = self.cfg.alias_hit("beta please check this")
        self.assertEqual(target2, "bot_b")

        # Multiple bots hit -> first-mentioned wins (NOT 'all')
        target_first = self.cfg.alias_hit("alpha please ask beta to check this")
        self.assertEqual(target_first, "bot_a")

        target_second = self.cfg.alias_hit("beta please ask alpha to check this")
        self.assertEqual(target_second, "bot_b")

        decision = self.ctrl.arbiter.evaluate_sync("小迷妹给蓉汇报，最大的问题是管家", "Alice")
        self.assertIsNotNone(decision)
        self.assertEqual(decision["target_bot"], "bot_a")
        self.assertEqual(decision["urgency"], "immediate")

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

    def test_observer_accepts_target_all(self):
        import asyncio
        from groupconnect.routing.router import AutonomousObserver

        async def run():
            obs = AutonomousObserver("primary_bot", self.cfg, lambda d: None)
            obs.on_decision({"target_bot": "all", "urgency": "immediate", "chat_id": 123})
            self.assertIn(123, obs.pending)
            obs._cancel(123)

        asyncio.run(run())

    def test_parse_rule_templates(self):
        from groupconnect.routing.router import parse_rule_templates

        content = (
            "# Routing Rules\n\n"
            "Decision Rules prose that must NOT become a template.\n\n"
            "# Classifier Templates\n\n"
            "## immediate\nReply {bot} {role}\n\n"
            "## wait\nAsk {role}\n\n"
            "## drop\nSpouse talk only\n\n"
            "## group\nFamily chat\n"
        )
        t = parse_rule_templates(content)
        self.assertEqual(t["immediate"], "Reply {bot} {role}")
        self.assertEqual(t["wait"], "Ask {role}")
        self.assertEqual(t["drop"], "Spouse talk only")
        self.assertEqual(t["group"], "Family chat")
        # Multi-word headings never parse as template keys
        self.assertEqual(len(t), 4)

    def test_classifier_registry(self):
        # New self-describing registry: active switch + per-provider params.
        self.assertEqual(self.cfg.active_provider, "typesafe")
        self.assertIn("typesafe", self.cfg.providers)
        self.assertIn("google_ai_studio", self.cfg.providers)
        self.assertEqual(self.cfg.engine, "jev")
        self.assertEqual(self.cfg.model, "jev-latest")
        self.assertEqual(self.cfg.api_key, os.environ.get("JEV_API_KEY", ""))
        # jev engine carries no prompt skeleton; gemini's stays declared but inert
        self.assertEqual(self.cfg.prompt_file, "")
        self.assertEqual(
            self.cfg.providers["google_ai_studio"]["prompt_template"], "router_prompt.txt"
        )

    def test_classifier_legacy_flat_config(self):
        import json
        import tempfile

        # Legacy flat layout must keep working (auto-synthesized registry).
        cfg_json = {"autonomous": {
            "classifier": {
                "provider": "typesafe",
                "model": "jev-legacy",
                "api_key_env": "JEV_API_KEY",
                "timeout_ms": 5000
            },
            "prompt_file": "router_prompt.txt",
            "rules_file": "routing_rules.md"
        }}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "autonomous_config.json")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            self.assertEqual(cfg.active_provider, "typesafe")
            self.assertEqual(cfg.engine, "jev")
            self.assertEqual(cfg.model, "jev-legacy")
            self.assertEqual(cfg.rules_file, "routing_rules.md")
            self.assertEqual(cfg.prompt_file, "router_prompt.txt")

    def test_classifier_active_missing_fails_closed(self):
        import json
        import tempfile

        # active points at an unregistered provider -> empty params, no key
        cfg_json = {"autonomous": {"classifier": {
            "active": "nonexistent",
            "providers": {"typesafe": {"engine": "jev", "model": "m"}}
        }}}
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "autonomous_config.json")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            self.assertEqual(cfg.active_provider, "nonexistent")
            self.assertEqual(cfg.model, "")
            self.assertEqual(cfg.api_key, "")

    def test_jev_criteria_uses_rules_file_templates(self):
        import json
        import tempfile
        from groupconnect.routing.router import AutonomousArbiter

        rules_md = (
            "# Rules\n\nDecision Rules prose.\n\n# Classifier Templates\n\n"
            "## immediate\nIMM {bot}|{role}\n\n## wait\nWAIT {bot}\n\n"
            "## drop\nDROP\n\n## group\nGRP\n"
        )
        cfg_json = {"autonomous": {
            "roles": {"bot_a": "RoleA"},
            "classifier": {"rules_file": "routing_rules.md"},
        }}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "routing_rules.md"), "w") as f:
                f.write(rules_md)
            cfg_path = os.path.join(d, "autonomous_config.json")
            with open(cfg_path, "w") as f:
                f.write(json.dumps(cfg_json))
            cfg = AutonomousConfig(cfg_path)
            arb = AutonomousArbiter(cfg)
            criteria, jev_map, group = arb._jev_criteria()
            self.assertEqual(criteria["bot_a_immediate"], "IMM bot_a|RoleA")
            self.assertEqual(criteria["bot_a_wait"], "WAIT bot_a")
            self.assertEqual(criteria["none_drop"], "DROP")
            self.assertEqual(group, "GRP")
            self.assertEqual(jev_map["none_drop"], ("none", "drop"))
            # Instructions must carry the rules prose but never the templates
            instructions = arb._load_rules_instructions()
            self.assertIn("Decision Rules prose.", instructions)
            self.assertNotIn("Classifier Templates", instructions)
            self.assertNotIn("IMM", instructions)

    def test_jev_criteria_falls_back_to_defaults(self):
        from groupconnect.routing.router import (
            AutonomousArbiter, DEFAULT_IMMEDIATE_CRITERIA, DEFAULT_DROP_CRITERIA,
        )

        # Example config has no rules_file -> templates empty -> defaults kick in
        arb = AutonomousArbiter(self.cfg)
        criteria, _, _ = arb._jev_criteria()
        self.assertEqual(criteria["none_drop"], DEFAULT_DROP_CRITERIA)
        bot = next(iter(self.cfg.roles))
        self.assertEqual(
            criteria[f"{bot}_immediate"],
            DEFAULT_IMMEDIATE_CRITERIA.replace("{bot}", bot).replace("{role}", self.cfg.roles[bot]),
        )


if __name__ == "__main__":
    unittest.main()
