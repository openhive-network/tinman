import base64
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

try:
    from tinman import server
except ModuleNotFoundError:
    server = None


@unittest.skipIf(server is None, "server extras are not installed")
class ServerTest(unittest.TestCase):
    def test_route_requires_authentication_and_csrf_before_broadcast(self):
        with tempfile.TemporaryDirectory() as temporary:
            config_path = Path(temporary) / "server.json"
            config_path.write_text(json.dumps({
                "shared_secret": "key-seed",
                "account_creator": "initminer",
                "server_auth": {"username": "user", "password": "password"},
                "session_secret": "session-secret",
                "transaction_target": {"node": "https://hive.example"},
            }))
            hived = mock.Mock()
            hived.database_api.get_dynamic_global_properties.return_value = {
                "head_block_number": 1,
                "head_block_id": "00000001" + ("00" * 16),
                "time": "2026-09-01T00:00:00",
            }
            signer = mock.Mock()
            signer.sign_transaction.return_value = {
                "result": {"sig": "signature"}
            }
            generated_key = json.dumps([{
                "public_key": "TST-public", "private_key": "private",
            }]).encode("utf-8")
            apps = []

            def capture_app(app, **kwargs):
                apps.append(app)

            with mock.patch.object(
                    server.subprocess, "check_output", return_value=generated_key
            ), mock.patch.object(server, "HiveRemoteBackend") as backend, mock.patch.object(
                    server, "HiveInterface", return_value=hived
            ), mock.patch.object(
                    server.submit, "TransactionSigner", return_value=signer
            ) as signer_class, mock.patch.object(
                    server.submit, "broadcast_transaction"
            ) as broadcast, mock.patch.object(server.Flask, "run", new=capture_app):
                server.main([
                    "server", "--conffile", str(config_path),
                    "--chain-id", "selected-chain", "--read-retries", "4",
                ])
                signer_class.assert_called_once_with(
                    sign_transaction_exe="sign_transaction",
                    chain_id="selected-chain",
                )
                self.assertEqual(len(backend.call_args_list), 2)
                self.assertEqual(
                    backend.call_args_list[0].kwargs["max_retries"], 4
                )
                self.assertEqual(
                    backend.call_args_list[1].kwargs["max_retries"], 0
                )
                client = apps[0].test_client()
                credentials = base64.b64encode(b"user:password").decode("ascii")
                headers = {"Authorization": "Basic " + credentials}

                self.assertEqual(client.get("/account_create").status_code, 401)
                self.assertEqual(
                    client.post("/account_create", headers=headers).status_code, 400
                )
                self.assertEqual(
                    client.get("/account_create", headers=headers).status_code, 200
                )
                with client.session_transaction() as flask_session:
                    csrf_token = flask_session["csrf_token"]
                self.assertEqual(client.post(
                    "/account_create", headers=headers,
                    data={"csrf_token": csrf_token},
                ).status_code, 200)
                broadcast.assert_not_called()

                self.assertEqual(client.post(
                    "/account_create", headers=headers,
                    data={
                        "csrf_token": csrf_token,
                        "new_account_name": "alice",
                    },
                ).status_code, 200)
                broadcast.assert_called_once()

    def test_server_requires_independent_security_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "server_auth"):
            server.require_server_security({})
        self.assertEqual(
            server.require_server_security({
                "server_auth": {"username": "user", "password": "password"},
                "session_secret": "session-secret",
            }),
            ("user", "password", "session-secret"),
        )

    def test_basic_authentication(self):
        auth = types.SimpleNamespace(username="user", password="password")
        self.assertTrue(server.authorized(auth, "user", "password"))
        self.assertFalse(server.authorized(auth, "user", "wrong"))
        self.assertFalse(server.authorized(None, "user", "password"))

        unicode_auth = types.SimpleNamespace(username="usér", password="päss")
        self.assertTrue(server.authorized(unicode_auth, "usér", "päss"))

    def test_signer_error_stops_before_broadcast(self):
        with self.assertRaisesRegex(RuntimeError, "signer failed"):
            server.signature_from_result({"error": "failure"})
        self.assertEqual(
            server.signature_from_result({"result": {"sig": "signature"}}),
            "signature",
        )

    def test_hive_error_message_handles_unexpected_shapes(self):
        self.assertEqual(
            server.hive_error_message(RuntimeError({"error": "odd"})), "odd"
        )
        self.assertEqual(
            server.hive_error_message(RuntimeError("plain")), "plain"
        )


if __name__ == "__main__":
    unittest.main()
