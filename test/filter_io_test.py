import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tinman import amountsub, keysub, prefixsub, sample


class FilterIoTest(unittest.TestCase):
    def test_streaming_filters_reject_identical_input_and_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            actions = Path(temporary) / "actions.jsonl"
            original = '["submit_transaction",{"tx":{"operations":[]}}]\n'
            actions.write_text(original)
            commands = (
                (amountsub.main, ["amountsub", "-i", str(actions), "-o", str(actions), "-r", "0.5"]),
                (keysub.main, ["keysub", "-i", str(actions), "-o", str(actions)]),
                (prefixsub.main, ["prefixsub", "-i", str(actions), "-o", str(actions)]),
            )
            for command, argv in commands:
                with self.subTest(command=argv[0]):
                    with self.assertRaisesRegex(RuntimeError, "must be different"):
                        command(argv)
                    self.assertEqual(actions.read_text(), original)

    def test_sample_default_stdout_is_json(self):
        fixture = Path(__file__).with_name("test-snapshot.json")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            sample.main(["sample", "--infile", str(fixture), "--outfile", "-"])

        result = json.loads(stdout.getvalue())
        self.assertEqual(len(result["accounts"]), 21)
        self.assertIn("Captured:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
