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


# Fake worker that sleeps long enough for the test to /stop it mid-run.
_SLEEP_WORKER = """#!/bin/sh
sleep 30
"""

# Records invocation count so we can assert the revival fallback never ran.
_COUNTING_WORKER = """#!/bin/sh
echo "$GC_TURN" >> "%s"
sleep 30
"""


class TestTeleAgentStopNoRevival(unittest.TestCase):
    """Regression: /stop SIGKILL on a resumed-session worker used to be
    mistaken by execute_turn's crash-revival fallback for a crashed session,
    which respawned a fresh worker — the bot kept running after /stop."""

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
            output_grace_secs=1,
            abort_server_sessions=False  # tests must never touch the real daemon
        )

    def test_stop_killed_worker_is_not_revived(self):
        calls = []
        calls_file = tempfile.mktemp(suffix=".calls")
        self.addCleanup(lambda: os.path.exists(calls_file) and os.remove(calls_file))
        worker = self._make_worker(_COUNTING_WORKER % calls_file)

        adapter = self._make_adapter(worker)

        async def scenario():
            task = asyncio.ensure_future(
                adapter.execute_turn("工作", conversation_id="ses_abc", chat_id=7)
            )
            # Wait until the worker registers itself with the adapter
            for _ in range(100):
                if 7 in adapter.workers:
                    break
                await asyncio.sleep(0.05)
            adapter.terminate(7)  # /stop lands mid-run
            text, cid = await asyncio.wait_for(task, timeout=10)
            return text, cid

        text, cid = asyncio.run(scenario())
        # Turn must end silently (no reply, no "Exit code -9" error message)
        self.assertIsNone(text)
        self.assertEqual(cid, "ses_abc")
        # Exactly ONE worker invocation: the crash-revival fallback must not run
        with open(calls_file) as f:
            invocation_count = sum(1 for _ in f)
        self.assertEqual(invocation_count, 1)
        # Flag consumed, so a later turn for the same chat is unaffected
        self.assertEqual(adapter._termination_requested, set())

    def test_stop_with_no_live_worker_poisons_nothing(self):
        adapter = self._make_adapter(self._make_worker(_CLEAN_WORKER))
        adapter.terminate(7)  # no worker registered: must be a no-op
        self.assertEqual(adapter._termination_requested, set())
        # The very next turn must still run normally
        text, cid = asyncio.run(adapter.execute_turn("ping", chat_id=7))
        self.assertEqual(text, "任务完成：假想答卷")
        self.assertEqual(cid, "ses_test123")


class TestTeleAgentStopAbortsServer(unittest.TestCase):
    """Regression: /stop used to only SIGKILL the thin tele-worker client.
    The TeleAgent daemon kept running the session's LLM loop server-side —
    burning tokens, finishing the task, even messaging the user out-of-band
    long after "Task execution was stopped." was sent. terminate() must now
    also abort the daemon sessions tagged for that chat; abort (not delete)
    keeps the session and its history for seamless resumption."""

    _LISTING = (
        "Total sessions: 5\n"
        "  [ses_live_7a] GC-7-1697000001 (2026-10-12 19:00:01)\n"
        "  [ses_old_7b] GC-7-1696000001 (2026-10-11 19:00:01)\n"
        "  [ses_other_8] GC-8-1697000001 (2026-10-12 19:00:01)\n"
        "  [ses_neg_grp] GC--1004324820543-1697000001 (2026-10-12 19:00:01)\n"
        "  [ses_user_mk] TeleWorker - 10-12 19:08:41 (2026-10-12 19:08:41)\n"
    )

    def _make_worker(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.addCleanup(os.remove, path)
        return path

    def _make_adapter(self, worker: str, **kwargs) -> TeleAgentAdapter:
        return TeleAgentAdapter(
            teleworker_bin=worker,
            workspace_dir=".",
            timeout_secs=30,
            output_grace_secs=1,
            **kwargs
        )

    class _FakeSubprocessRun:
        """Records calls; answers -l with a fake listing and accepts aborts."""

        def __init__(self, listing: str):
            self.calls = []
            self.listing = listing

        def __call__(self, args, **kwargs):
            self.calls.append(list(args))
            if "-l" in args:
                return type("R", (), {"returncode": 0, "stdout": self.listing.encode(), "stderr": b""})()
            if "--abort-session" in args:
                return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
            raise AssertionError(f"unexpected subprocess call: {args}")

        def aborted(self):
            return [c[c.index("--abort-session") + 1] for c in self.calls if "--abort-session" in c]

    def test_stop_aborts_tagged_daemon_sessions(self):
        from unittest.mock import patch

        worker = self._make_worker(_SLEEP_WORKER)
        adapter = self._make_adapter(worker)
        fake = self._FakeSubprocessRun(self._LISTING)

        async def scenario():
            with patch("groupconnect.adapters.teleagent.subprocess.run", fake):
                task = asyncio.ensure_future(
                    adapter.execute_turn("工作", conversation_id="ses_abc", chat_id=7)
                )
                for _ in range(100):
                    if 7 in adapter.workers:
                        break
                    await asyncio.sleep(0.05)
                adapter.terminate(7)  # /stop lands mid-run
                text, cid = await asyncio.wait_for(task, timeout=10)
                # Background executor abort must complete before the loop closes
                for _ in range(200):
                    if fake.aborted():
                        break
                    await asyncio.sleep(0.05)
                return text, cid

        text, cid = asyncio.run(scenario())
        self.assertIsNone(text)
        self.assertEqual(cid, "ses_abc")
        # Exactly this chat's tagged sessions are aborted; other chats', group
        # chats' and user-created sessions are untouched.
        self.assertEqual(sorted(fake.aborted()), ["ses_live_7a", "ses_old_7b"])
        self.assertTrue(any("-l" in c for c in fake.calls))

    def test_no_op_stop_still_aborts_orphan_sessions(self):
        from unittest.mock import patch

        adapter = self._make_adapter(self._make_worker(_CLEAN_WORKER))
        fake = self._FakeSubprocessRun(self._LISTING)

        async def scenario():
            with patch("groupconnect.adapters.teleagent.subprocess.run", fake):
                adapter.terminate(7)  # no live worker: kill is a no-op...
                for _ in range(200):
                    if fake.aborted():
                        break
                    await asyncio.sleep(0.05)

        asyncio.run(scenario())
        # ...but leaked daemon sessions from earlier turns are still aborted
        self.assertEqual(sorted(fake.aborted()), ["ses_live_7a", "ses_old_7b"])
        self.assertEqual(adapter._termination_requested, set())

    def test_abort_disabled_never_touches_daemon(self):
        from unittest.mock import patch

        adapter = self._make_adapter(
            self._make_worker(_SLEEP_WORKER), abort_server_sessions=False
        )
        fake = self._FakeSubprocessRun(self._LISTING)

        async def scenario():
            with patch("groupconnect.adapters.teleagent.subprocess.run", fake):
                task = asyncio.ensure_future(
                    adapter.execute_turn("工作", conversation_id="ses_abc", chat_id=7)
                )
                for _ in range(100):
                    if 7 in adapter.workers:
                        break
                    await asyncio.sleep(0.05)
                adapter.terminate(7)
                await asyncio.wait_for(task, timeout=10)
                await asyncio.sleep(0.3)

        asyncio.run(scenario())
        self.assertEqual(fake.calls, [])  # daemon never contacted

    def test_execute_turn_titles_session_with_chat_marker(self):
        argv_file = tempfile.mktemp(suffix=".argv")
        self.addCleanup(lambda: os.path.exists(argv_file) and os.remove(argv_file))
        worker = self._make_worker(
            "#!/bin/sh\nprintf '%s\\n' \"$@\" > \"" + argv_file + "\"\n"
            "printf '%s' '{\"session_id\":\"ses_t1\",\"text\":\"ok\"}'\n"
        )
        adapter = self._make_adapter(worker)

        asyncio.run(adapter.execute_turn("ping", chat_id=7))
        with open(argv_file) as f:
            argv = f.read().splitlines()
        self.assertIn("--title", argv)
        title = argv[argv.index("--title") + 1]
        self.assertRegex(title, r"^GC-7-\d+$")

        # Without a chat_id (bare CLI usage), no marker title is injected
        with open(argv_file, "w") as f:
            f.write("")
        asyncio.run(adapter.execute_turn("ping"))
        with open(argv_file) as f:
            argv = f.read().splitlines()
        self.assertNotIn("--title", argv)


class TestCliStopSilence(unittest.TestCase):
    """Regression: /stop SIGKILL on CLI-harness workers (antigravity/claude/
    codex/opencode) used to surface an "Exit code -9" error message in chat.
    terminate() now flags the kill so execute_turn ends the turn silently."""

    def _make_worker(self, body: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".sh")
        with os.fdopen(fd, "w") as f:
            f.write(body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        self.addCleanup(os.remove, path)
        return path

    def _stop_scenario(self, make_adapter):
        worker = self._make_worker(_SLEEP_WORKER)
        adapter = make_adapter(worker)

        async def scenario():
            task = asyncio.ensure_future(
                adapter.execute_turn("工作", conversation_id="ses_abc", chat_id=7)
            )
            # Wait until the worker registers itself with the adapter
            for _ in range(100):
                procs = getattr(adapter, "workers", None) or getattr(adapter, "active_processes", None) or {}
                if 7 in procs:
                    break
                await asyncio.sleep(0.05)
            adapter.terminate(7)  # /stop lands mid-run
            return await asyncio.wait_for(task, timeout=10)

        text, cid = asyncio.run(scenario())
        # Turn must end silently (no reply, no "Exit code -9" error message)
        self.assertIsNone(text)
        self.assertEqual(cid, "ses_abc")
        # Flag consumed, so a later turn for the same chat is unaffected
        self.assertEqual(adapter._termination_requested, set())

    def _no_poison_scenario(self, make_adapter):
        worker = self._make_worker("#!/bin/sh\necho ok\n")
        adapter = make_adapter(worker)
        adapter.terminate(7)  # no worker registered: must be a no-op
        self.assertEqual(adapter._termination_requested, set())
        # The very next turn must still run normally
        text, _ = asyncio.run(adapter.execute_turn("ping", chat_id=7))
        self.assertEqual(text, "ok")

    def test_antigravity_stop_is_silent(self):
        self._stop_scenario(lambda w: AntigravityAdapter(agy_bin=w, workspace_dir=".", timeout_secs=30))

    def test_antigravity_stop_with_no_live_worker_poisons_nothing(self):
        self._no_poison_scenario(lambda w: AntigravityAdapter(agy_bin=w, workspace_dir=".", timeout_secs=30))

    def test_claude_stop_is_silent(self):
        self._stop_scenario(lambda w: ClaudeCodeAdapter(claude_bin=w, workspace_dir=".", timeout_secs=30))

    def test_claude_stop_with_no_live_worker_poisons_nothing(self):
        self._no_poison_scenario(lambda w: ClaudeCodeAdapter(claude_bin=w, workspace_dir=".", timeout_secs=30))

    def test_codex_stop_is_silent(self):
        self._stop_scenario(lambda w: CodexAdapter(codex_bin=w, workspace_dir=".", timeout_secs=30))

    def test_codex_stop_with_no_live_worker_poisons_nothing(self):
        self._no_poison_scenario(lambda w: CodexAdapter(codex_bin=w, workspace_dir=".", timeout_secs=30))

    def test_opencode_stop_is_silent(self):
        self._stop_scenario(lambda w: OpenCodeAdapter(opencode_bin=w, workspace_dir=".", timeout_secs=30))

    def test_opencode_stop_with_no_live_worker_poisons_nothing(self):
        self._no_poison_scenario(lambda w: OpenCodeAdapter(opencode_bin=w, workspace_dir=".", timeout_secs=30))


if __name__ == "__main__":
    unittest.main()
