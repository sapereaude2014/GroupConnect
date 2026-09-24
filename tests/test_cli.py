import os
import shutil
import tempfile
import unittest


class TestCliEnvDeduplication(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_env_deduplication_exact_key_matching(self):
        """Line-prefix key deduplication prevents substring collisions (e.g. ANOTHER_KEY vs KEY)."""
        env_file = os.path.join(self.tmpdir, ".env")
        # Pre-populate with a key that contains our new key as a substring
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("ANOTHER_API_KEY=pre_existing_value\n")

        with open(env_file, "r", encoding="utf-8") as f:
            existing_env = f.read()

        # The new key is 'API_KEY', which is a substring of 'ANOTHER_API_KEY'
        env_vars = {
            "API_KEY": "new_secret_val",
            "ANOTHER_API_KEY": "should_be_skipped"
        }

        existing_keys = {line.split("=", 1)[0].strip() for line in existing_env.splitlines() if "=" in line}
        new_lines = [f"{k}={v}" for k, v in env_vars.items() if k not in existing_keys]

        # API_KEY must NOT be skipped, while ANOTHER_API_KEY must be skipped
        self.assertIn("API_KEY=new_secret_val", new_lines)
        self.assertNotIn("ANOTHER_API_KEY=should_be_skipped", new_lines)

        # Append to file
        if new_lines:
            with open(env_file, "a", encoding="utf-8") as f:
                for line in new_lines:
                    f.write(f"{line}\n")

        with open(env_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("ANOTHER_API_KEY=pre_existing_value", content)
        self.assertIn("API_KEY=new_secret_val", content)

    def test_env_deduplication_export_prefix_and_comments(self):
        """Deduplication recognizes 'export KEY=val' and ignores commented '# KEY=val'."""
        env_content = (
            "# JEV_API_KEY=commented_out_key\n"
            "export EXISTING_TOKEN=tok123\n"
            "PLAIN_KEY=plain\n"
        )
        existing_keys = {
            line.strip().removeprefix("export ").split("=", 1)[0].strip()
            for line in env_content.splitlines()
            if "=" in line and not line.strip().startswith("#")
        }
        self.assertIn("EXISTING_TOKEN", existing_keys)
        self.assertIn("PLAIN_KEY", existing_keys)
        self.assertNotIn("JEV_API_KEY", existing_keys)  # Commented out, so new one can be added


if __name__ == "__main__":
    unittest.main()
