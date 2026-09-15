import asyncio
import os
import stat
import tempfile
import time
import unittest
from groupconnect.adapters.antigravity import AntigravityAdapter
from groupconnect.adapters.claude_code import ClaudeCodeAdapter
from groupconnect.adapters.codex import CodexAdapter
from groupconnect.adapters.opencode import OpenCodeAdapter
from groupconnect.adapters.teleagent import TeleAgentAdapter
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


# Fake tele-worker scripts. The "hang" variant writes the complete final JSON
# answer but never exits, reproducing the real-world bug where a leaked child
# process kept the output pipes open and the engine blocked on communicate().
_HANG_WORKER = """#!/bin/sh
printf '%s' '{"session_id":"ses_test123","text":"任务完成：假想答卷"}'
sleep 60
"""

_CLEAN_WORKER = """#!/bin/sh
printf '%s' '{"session_id":"ses_test123","text":"任务完成：假想答卷"}'
"""


class TestTeleAgentOutputGuard(unittest.TestCase):
    """Regression: worker delivers the final JSON but never exits."""

    def _make_worker(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.addCleanup(os.remove, path)
        return path

    def _make_adapter(self, worker: str) -> TeleAgentAdapter:
        return TeleAgentAdapter(
            teleworker_bin=worker,
            workspace_dir=".",
            timeout_secs=30,
            output_grace_secs=1
        )

    def test_hanging_worker_is_killed_and_answer_used(self):
        adapter = self._make_adapter(self._make_worker(_HANG_WORKER))
        started = time.monotonic()
        text, cid = asyncio.run(
            adapter.execute_turn("ping", conversation_id="ses_test123", chat_id=1)
        )
        elapsed = time.monotonic() - started
        self.assertEqual(text, "任务完成：假想答卷")
        self.assertEqual(cid, "ses_test123")
        # Must return shortly after the grace window, not after the 30s hard
        # timeout (nor the worker's own 60s sleep).
        self.assertLess(elapsed, 15)

    def test_clean_worker_exits_normally(self):
        adapter = self._make_adapter(self._make_worker(_CLEAN_WORKER))
        text, cid = asyncio.run(adapter.execute_turn("ping", chat_id=1))
        self.assertEqual(text, "任务完成：假想答卷")
        self.assertEqual(cid, "ses_test123")


if __name__ == "__main__":
    unittest.main()
