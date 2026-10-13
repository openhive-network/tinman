import contextlib
import io
import unittest
from unittest import mock

from tinman import main


class MainTest(unittest.TestCase):
    def test_help_does_not_import_command_modules(self):
        output = io.StringIO()
        with mock.patch.object(main, "import_module") as import_module:
            with contextlib.redirect_stdout(output):
                result = main.main(["tinman", "--help"])

        self.assertIsNone(result)
        import_module.assert_not_called()
        self.assertIn("snapshot", output.getvalue())
        self.assertIn("server", output.getvalue())

    def test_server_reports_missing_optional_dependencies(self):
        missing = ModuleNotFoundError("No module named 'flask'", name="flask")
        output = io.StringIO()
        with mock.patch.object(main, "import_module", side_effect=missing):
            with contextlib.redirect_stderr(output):
                result = main.main(["tinman", "server", "--help"])

        self.assertEqual(result, 2)
        self.assertIn("tinman[server]", output.getvalue())
