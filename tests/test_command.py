import unittest
from groupconnect.core.parser import parse_bot_command


class TestCommandParser(unittest.TestCase):
    def test_basic_commands(self):
        cmd, target, args = parse_bot_command("/stop", "my_bot")
        self.assertEqual(cmd, "stop")
        self.assertIsNone(target)
        self.assertEqual(args, "")

        cmd, target, args = parse_bot_command("/status", "my_bot")
        self.assertEqual(cmd, "status")

        cmd, target, args = parse_bot_command("/new", "my_bot")
        self.assertEqual(cmd, "new")

    def test_bot_target_mention(self):
        cmd, target, args = parse_bot_command("/stop@my_bot", "my_bot")
        self.assertEqual(cmd, "stop")
        self.assertEqual(target, "my_bot")

        # Targeted at another bot -> ignored
        cmd, target, args = parse_bot_command("/stop@other_bot", "my_bot")
        self.assertIsNone(cmd)

    def test_args_parsing(self):
        cmd, target, args = parse_bot_command("/stop right now please", "my_bot")
        self.assertEqual(cmd, "stop")
        self.assertEqual(args, "right now please")

    def test_false_triggers_avoidance(self):
        # /stopwords is NOT /stop
        cmd, target, args = parse_bot_command("/stopwords in text", "my_bot")
        self.assertEqual(cmd, "stopwords")
        self.assertNotEqual(cmd, "stop")

        # /stopwatch is NOT /stop
        cmd, target, args = parse_bot_command("/stopwatch", "my_bot")
        self.assertEqual(cmd, "stopwatch")
        self.assertNotEqual(cmd, "stop")

        # Mid-sentence mention of /stop is NOT a command
        cmd, target, args = parse_bot_command("Hello, please do not /stop this", "my_bot")
        self.assertIsNone(cmd)

    def test_custom_command_locking_normalization(self):
        from groupconnect.core.commands import CustomCommandDispatcher
        dispatcher = CustomCommandDispatcher(
            commands=[{"command": "/backup", "script": "/bin/true"}],
            channel=None,
            context_mgr=None,
            bot_name="Bot",
            bot_username="my_bot"
        )
        # Lock with leading slash
        self.assertTrue(dispatcher.acquire_lock("/backup"))
        # Cannot acquire second time while locked
        self.assertFalse(dispatcher.acquire_lock("/backup"))
        self.assertFalse(dispatcher.acquire_lock("backup"))
        # Release with or without leading slash
        dispatcher.release_lock("/backup")
        # Can acquire again
        self.assertTrue(dispatcher.acquire_lock("backup"))
        dispatcher.release_lock("backup")

    def test_custom_command_preserve_duplicate_arguments(self):
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from groupconnect.core.commands import CustomCommandDispatcher

        dispatcher = CustomCommandDispatcher(
            commands=[{"command": "calc", "script": "/bin/echo", "pass_args": True}],
            channel=AsyncMock(),
            context_mgr=MagicMock(),
            bot_name="Bot",
            bot_username="my_bot"
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        executed_args = []
        async def mock_subprocess_exec(*cmd_args, **kwargs):
            executed_args.extend(cmd_args)
            proc = AsyncMock()
            proc.communicate = AsyncMock(return_value=(b"20\n", b""))
            proc.returncode = 0
            return proc

        cmd_cfg = dispatcher.get_command("calc")
        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec), \
             patch("os.path.isfile", return_value=True):
            loop.run_until_complete(
                dispatcher.execute_command(123, cmd_cfg, "10 + 10")
            )

        # Duplicate '10' arguments must be preserved
        self.assertEqual(executed_args, ["/bin/echo", "10", "+", "10"])
        loop.close()


if __name__ == "__main__":
    unittest.main()
