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

    def test_generate_blocks_uses_current_debug_node_contract(self):
        hived = mock.Mock()

        submit.generate_blocks(hived, {"count": 2, "miss_blocks": 3})

        hived.debug_node_api.debug_generate_blocks.assert_called_once_with(
            debug_key="5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n",
            count=2,
            skip=0,
            miss_blocks=3,
        )

    def test_broadcast_uses_unbounded_block_age(self):
        hived = mock.Mock()
        transaction = {"operations": [], "signatures": []}

        submit.broadcast_transaction(hived, transaction)

        hived.network_broadcast_api.broadcast_transaction.assert_called_once_with(
            trx=transaction,
            max_block_age=-1,
        )
