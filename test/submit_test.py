import io
import json
import unittest
from unittest import mock

from tinman import submit


class SubmitTest(unittest.TestCase):
    def test_transaction_signer_uses_binary_process_streams(self):
        process = mock.Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b'{"result":{"sig":"signature"}}\n')

        with mock.patch.object(
            submit.subprocess, "Popen", return_value=process
        ) as popen:
            signer = submit.TransactionSigner("sign_transaction", "chain-id")
            result = signer.sign_transaction({"operations": []}, "private-key")

        command = popen.call_args.args[0]
        self.assertEqual(command, ["sign_transaction", "--chain-id=chain-id"])
        request = json.loads(process.stdin.getvalue().decode("ascii"))
        self.assertEqual(request["tx"], {"operations": []})
        self.assertEqual(request["wif"], "private-key")
        self.assertEqual(result, {"result": {"sig": "signature"}})
