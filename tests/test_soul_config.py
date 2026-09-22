import os
import tempfile
import unittest
from groupconnect.core.config import GatewayConfig
from groupconnect.engine import _load_soul


class TestSoulAndConfig(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.workspace = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_default_soul_path(self):
        # Default: {workspace}/.agents/souls/{bot_username}.md
        souls_dir = os.path.join(self.workspace, ".agents", "souls")
        os.makedirs(souls_dir, exist_ok=True)
        soul_file = os.path.join(souls_dir, "test_bot.md")
        with open(soul_file, "w", encoding="utf-8") as f:
            f.write("I am the default soul")

        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock",
            "bot_username": "test_bot",
            "workspace_dir": self.workspace
        })
        soul = _load_soul(cfg)
        self.assertIn("I am the default soul", soul)

    def test_explicit_souls_dir(self):
        # Custom souls_dir
        custom_dir = os.path.join(self.workspace, "custom_souls")
        os.makedirs(custom_dir, exist_ok=True)
        soul_file = os.path.join(custom_dir, "custom_bot.md")
        with open(soul_file, "w", encoding="utf-8") as f:
            f.write("I am from custom_souls directory")

        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock",
            "bot_username": "custom_bot",
            "workspace_dir": self.workspace,
            "souls_dir": custom_dir
        })
        soul = _load_soul(cfg)
        self.assertIn("I am from custom_souls directory", soul)

    def test_explicit_soul_path(self):
        # Custom soul_path takes highest priority
        direct_file = os.path.join(self.workspace, "my_custom_persona.md")
        with open(direct_file, "w", encoding="utf-8") as f:
            f.write("I am explicit soul_path")

        cfg = GatewayConfig({
            "platform": "telegram",
            "bot_token": "mock",
            "bot_username": "any_bot",
            "workspace_dir": self.workspace,
            "soul_path": direct_file
        })
        soul = _load_soul(cfg)
        self.assertIn("I am explicit soul_path", soul)


if __name__ == "__main__":
    unittest.main()
