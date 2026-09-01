import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from simple_hive_client.client import HiveNetworkError
from tinman import submit


class SubmitTest(unittest.TestCase):
    def run_main(
            self, lines, signer_result=None, transactions_per_block=1,
            extra_args=None):
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
        with mock.patch.object(submit, "HiveRemoteBackend") as backend, mock.patch.object(
                submit, "HiveInterface", return_value=hived), mock.patch.object(
                submit, "TransactionSigner", return_value=signer) as signer_class, mock.patch.object(
                submit, "generate_blocks") as generate_blocks, mock.patch.object(
                submit, "broadcast_transaction") as broadcast:
            argv = [
                "submit", "--input-file", str(input_path),
                "--fail-file", str(fail_path),
                "--transactions-per-block", str(transactions_per_block),
            ]
            argv.extend(extra_args or [])
            submit.main(argv)
        self.last_backend = backend
        self.last_signer_class = signer_class
        return fail_path.read_text(), generate_blocks, broadcast

    def test_transaction_signer_uses_binary_process_streams(self):
        process = mock.Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO(b'{"result":{"sig":"signature"}}\n')
        process.stderr = io.BytesIO()

        with mock.patch.object(
            submit.subprocess, "Popen", return_value=process
        ) as popen:
            signer = submit.TransactionSigner("sign_transaction", "chain-id")
            result = signer.sign_transaction({"operations": []}, "private-key")

        command = popen.call_args.args[0]
        self.assertEqual(command, ["sign_transaction", "--chain-id=chain-id"])
        self.assertEqual(popen.call_args.kwargs["stderr"], submit.subprocess.PIPE)
        request = json.loads(process.stdin.getvalue().decode("ascii"))
        self.assertEqual(request["tx"], {"operations": []})
        self.assertEqual(request["wif"], "private-key")
        self.assertEqual(result, {"result": {"sig": "signature"}})

    def test_transaction_signer_reports_stderr_on_empty_response(self):
        process = mock.Mock()
        process.stdin = io.BytesIO()
        process.stdout = io.BytesIO()
        process.stderr = io.BytesIO(b"bad chain id\n")
        with mock.patch.object(submit.subprocess, "Popen", return_value=process):
            signer = submit.TransactionSigner("sign_transaction")
            with self.assertRaisesRegex(RuntimeError, "bad chain id"):
                signer.sign_transaction({"operations": []}, "private-key")

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

    def test_broadcast_network_failure_is_not_retried(self):
        hived = mock.Mock()
        hived.network_broadcast_api.broadcast_transaction.side_effect = (
            HiveNetworkError("connection lost")
        )

        with self.assertRaisesRegex(
                submit.BroadcastOutcomeUnknown, "outcome is unknown"):
            submit.broadcast_transaction(hived, {"operations": []})

        hived.network_broadcast_api.broadcast_transaction.assert_called_once()

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

    def test_transaction_batch_generates_only_at_boundary(self):
        metadata = ["metadata", {
            "txgen:semver": "0.2", "txgen:transactions_per_block": 2,
        }]
        transaction = ["submit_transaction", {"tx": {
            "operations": [], "wif_sigs": ["private"],
        }}]
        _, generate_blocks, broadcast = self.run_main([
            json.dumps(metadata), json.dumps(transaction),
            json.dumps(transaction),
        ], transactions_per_block=2)
        self.assertEqual(generate_blocks.call_count, 1)
        self.assertEqual(broadcast.call_count, 2)

    def test_signer_failure_prevents_broadcast(self):
        transaction = ["submit_transaction", {"tx": {
            "operations": [], "wif_sigs": ["private"],
        }}]
        failures, _, broadcast = self.run_main(
            [json.dumps(transaction)], signer_result={"error": "failure"}
        )
        self.assertIn("could not sign transaction", failures)
        broadcast.assert_not_called()

    def test_main_returns_failure_when_a_record_fails(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        input_path = Path(temporary.name) / "input.actions"
        input_path.write_text("not-json\n")
        with mock.patch.object(submit, "HiveRemoteBackend"), mock.patch.object(
                submit, "HiveInterface"), mock.patch.object(
                submit, "TransactionSigner"):
            result = submit.main([
                "submit", "--input-file", str(input_path), "--fail-file", "-",
            ])
        self.assertEqual(result, 1)

    def test_main_plumbs_chain_id_and_rpc_policies(self):
        self.run_main([], extra_args=[
            "--chain-id", "selected-chain",
            "--timeout", "7",
            "--block-timeout", "601",
            "--read-retries", "4",
        ])

        self.last_signer_class.assert_called_once_with(
            sign_transaction_exe="sign_transaction",
            chain_id="selected-chain",
        )
        calls = self.last_backend.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0].kwargs["max_retries"], 4)
        self.assertEqual(calls[0].kwargs["min_timeout"], 7)
        self.assertEqual(calls[1].kwargs["max_retries"], 0)
        self.assertEqual(calls[1].kwargs["min_timeout"], 601)
        self.assertEqual(calls[2].kwargs["max_retries"], 0)
        self.assertEqual(calls[2].kwargs["min_timeout"], 7)
