import unittest
from groupagent.core.command import parse_bot_command


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


if __name__ == "__main__":
    unittest.main()
