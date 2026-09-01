import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tinman import submit


class SubmitTest(unittest.TestCase):
    def run_main(self, lines, signer_result=None, transactions_per_block=1):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        input_path = Path(temporary.name) / "input.actions"
        fail_path = Path(temporary.name) / "fail.actions"
        input_path.write_text("\n".join(lines) + "\n")
        hived = mock.Mock()
        hived.database_api.get_dynamic_global_properties.return_value = {
            "head_block_number": 1,
            "head_block_id": "00000001" + ("00" * 16),
            "time": "2026-09-01T00:00:00",
        }
        signer = mock.Mock()
        signer.sign_transaction.return_value = signer_result or {
            "result": {"sig": "signature"}
        }
        with mock.patch.object(submit, "HiveRemoteBackend"), mock.patch.object(
                submit, "HiveInterface", return_value=hived), mock.patch.object(
                submit, "TransactionSigner", return_value=signer), mock.patch.object(
                submit, "generate_blocks") as generate_blocks, mock.patch.object(
                submit, "broadcast_transaction") as broadcast:
            submit.main([
                "submit", "--input-file", str(input_path),
                "--fail-file", str(fail_path),
                "--transactions-per-block", str(transactions_per_block),
            ])
        return fail_path.read_text(), generate_blocks, broadcast

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

    def test_malformed_record_is_written_and_stream_continues(self):
        failures, generate_blocks, _ = self.run_main([
            "not-json",
            json.dumps(["wait_blocks", {"count": 1}]),
        ])
        self.assertIn("not-json", failures)
        generate_blocks.assert_called_once()

    def test_wait_after_transaction_boundary_does_not_add_extra_block(self):
        metadata = ["metadata", {
            "txgen:semver": "0.2", "txgen:transactions_per_block": 1,
        }]
        transaction = ["submit_transaction", {"tx": {
            "operations": [], "wif_sigs": ["private"],
        }}]
        wait = ["wait_blocks", {"count": 1}]
        _, generate_blocks, broadcast = self.run_main([
            json.dumps(metadata), json.dumps(transaction), json.dumps(wait),
        ])
        self.assertEqual(generate_blocks.call_count, 2)
        broadcast.assert_called_once()

    def test_signer_failure_prevents_broadcast(self):
        transaction = ["submit_transaction", {"tx": {
            "operations": [], "wif_sigs": ["private"],
        }}]
        failures, _, broadcast = self.run_main(
            [json.dumps(transaction)], signer_result={"error": "failure"}
        )
        self.assertIn("could not sign transaction", failures)
        broadcast.assert_not_called()
