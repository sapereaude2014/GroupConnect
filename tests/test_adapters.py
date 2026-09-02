import unittest
from groupconnect.adapters.antigravity import AntigravityAdapter
from groupconnect.adapters.claude_code import ClaudeCodeAdapter
from groupconnect.adapters.codex import CodexAdapter
from groupconnect.adapters.opencode import OpenCodeAdapter
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import GroupConnectEngine


class TestAdapters(unittest.TestCase):
    def test_adapter_instantiations(self):
        agy = AntigravityAdapter(agy_bin="agy", workspace_dir=".", model="gemini-3.7-flash-high")
        self.assertEqual(agy.model, "gemini-3.7-flash-high")

        claude = ClaudeCodeAdapter(claude_bin="claude", workspace_dir=".")
        self.assertEqual(claude.claude_bin, "claude")

        codex = CodexAdapter(codex_bin="codex", workspace_dir=".", model="o3")
        self.assertEqual(codex.model, "o3")

        opencode = OpenCodeAdapter(opencode_bin="opencode", workspace_dir=".", model="deepseek-coder")
        self.assertEqual(opencode.model, "deepseek-coder")

    def test_engine_factory(self):
        # 1. Antigravity
        cfg_agy = GatewayConfig({"platform": "telegram", "engine_type": "antigravity"})
        engine_agy = GroupConnectEngine(cfg_agy)
        self.assertIsInstance(engine_agy.adapter, AntigravityAdapter)

        # 2. Claude
        cfg_claude = GatewayConfig({"platform": "telegram", "engine_type": "claude"})
        engine_claude = GroupConnectEngine(cfg_claude)
        self.assertIsInstance(engine_claude.adapter, ClaudeCodeAdapter)

        # 3. Codex
        cfg_codex = GatewayConfig({"platform": "telegram", "engine_type": "codex"})
        engine_codex = GroupConnectEngine(cfg_codex)
        self.assertIsInstance(engine_codex.adapter, CodexAdapter)

        # 4. OpenCode
        cfg_opencode = GatewayConfig({"platform": "telegram", "engine_type": "opencode"})
        engine_opencode = GroupConnectEngine(cfg_opencode)
        self.assertIsInstance(engine_opencode.adapter, OpenCodeAdapter)


if __name__ == "__main__":
    unittest.main()
