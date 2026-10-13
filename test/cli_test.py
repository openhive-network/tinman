import subprocess
import shutil
import sys
import unittest


class CliTest(unittest.TestCase):
    def test_installed_console_script_help(self):
        executable = shutil.which("tinman")
        if executable is None:
            self.skipTest("console script is only available in an installed environment")
        result = subprocess.run(
            [executable, "--help"], check=False, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Available commands:", result.stdout)

    def test_core_command_help(self):
        commands = (
            "snapshot",
            "txgen",
            "gatling",
            "keysub",
            "sample",
            "submit",
            "warden",
            "amountsub",
            "durables",
            "prefixsub",
        )

        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, "-m", "tinman", command, "--help"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage:", result.stdout)
