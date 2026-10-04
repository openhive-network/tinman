import json
import socket
import unittest
import urllib.error

from simple_hive_client.client import (
    HiveHTTPError,
    HiveIllegalArgument,
    HiveInterface,
    HiveNetworkError,
    HiveRemoteBackend,
    HiveResponseError,
)


class FakeResponse:
    def __init__(self, payload, raw=False):
        self.payload = payload
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        if self.raw:
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


class RecordingHiveNode:
    def __init__(self):
        self.requests = []

    def __call__(self, url, data, timeout):
        request = json.loads(data.decode("ascii"))
        self.requests.append((url, timeout, request))
        result_by_method = {
            "database_api.get_version": {
                "blockchain_version": "1.29.0",
                "chain_id": "test-chain-id",
            },
            "database_api.get_config": {
                "IS_TEST_NET": True,
                "HIVE_ADDRESS_PREFIX": "TST",
                "HIVE_MAX_AUTHORITY_MEMBERSHIP": 40,
                "HIVE_BLOCK_INTERVAL": 3,
            },
            "database_api.get_hardfork_properties": {
                "current_hardfork_version": "1.28.0",
            },
            "database_api.get_witness_schedule": {
                "median_props": {
                    "account_creation_fee": {
                        "amount": "30",
                        "precision": 3,
                        "nai": "@@000000021",
                    }
                }
            },
            "database_api.list_accounts": {
                "accounts": [{
                    "name": "alice",
                    "balance": {
                        "amount": "1000",
                        "precision": 3,
                        "nai": "@@000000021",
                    },
                }],
            },
            "database_api.list_witnesses": {
                "witnesses": [{"owner": "alice"}],
            },
            "database_api.get_dynamic_global_properties": {
                "head_block_number": 123,
                "head_block_id": "0000007b" + ("00" * 16),
                "time": "2026-08-31T12:00:00",
            },
            "debug_node_api.debug_generate_blocks": {"blocks": 1},
            "network_broadcast_api.broadcast_transaction": {},
        }
        return FakeResponse({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": result_by_method[request["method"]],
        })


class RpcContractTest(unittest.TestCase):
    def setUp(self):
        self.node = RecordingHiveNode()
        backend = HiveRemoteBackend(
            nodes=["https://hive.example"],
            urlopen=self.node,
            appbase=True,
            max_retries=0,
        )
        self.hive = HiveInterface(backend)

    def assert_last_request(self, method, params):
        url, timeout, request = self.node.requests[-1]
        self.assertEqual(url, "https://hive.example")
        self.assertEqual(timeout, 2.0)
        self.assertEqual(request["jsonrpc"], "2.0")
        self.assertEqual(request["method"], method)
        self.assertEqual(request["params"], params)

    def test_database_api_contracts(self):
        version = self.hive.database_api.get_version()
        self.assertEqual(version["chain_id"], "test-chain-id")
        self.assert_last_request("database_api.get_version", {})

        config = self.hive.database_api.get_config()
        self.assertEqual(config["HIVE_MAX_AUTHORITY_MEMBERSHIP"], 40)
        self.assert_last_request("database_api.get_config", {})

        hardfork = self.hive.database_api.get_hardfork_properties()
        self.assertEqual(hardfork["current_hardfork_version"], "1.28.0")
        self.assert_last_request("database_api.get_hardfork_properties", {})

        schedule = self.hive.database_api.get_witness_schedule()
        self.assertEqual(
            schedule["median_props"]["account_creation_fee"]["amount"], "30"
        )
        self.assert_last_request("database_api.get_witness_schedule", {})

        accounts = self.hive.database_api.list_accounts(
            start="", limit=1, order="by_name"
        )
        self.assertEqual(accounts["accounts"][0]["name"], "alice")
        self.assertEqual(
            accounts["accounts"][0]["balance"]["nai"], "@@000000021"
        )
        self.assert_last_request(
            "database_api.list_accounts",
            {"start": "", "limit": 1, "order": "by_name"},
        )

        witnesses = self.hive.database_api.list_witnesses(
            start="", limit=1, order="by_name"
        )
        self.assertEqual(witnesses, {"witnesses": [{"owner": "alice"}]})
        self.assert_last_request(
            "database_api.list_witnesses",
            {"start": "", "limit": 1, "order": "by_name"},
        )

        dgpo = self.hive.database_api.get_dynamic_global_properties()
        self.assertEqual(dgpo["head_block_number"], 123)
        self.assert_last_request(
            "database_api.get_dynamic_global_properties", {}
        )

    def test_debug_node_api_contract(self):
        result = self.hive.debug_node_api.debug_generate_blocks(
            debug_key="private-test-key",
            count=1,
            skip=0,
            miss_blocks=0,
        )
        self.assertEqual(result, {"blocks": 1})
        self.assert_last_request(
            "debug_node_api.debug_generate_blocks",
            {
                "debug_key": "private-test-key",
                "count": 1,
                "skip": 0,
                "miss_blocks": 0,
            },
        )

    def test_network_broadcast_api_contract(self):
        transaction = {
            "ref_block_num": 1,
            "ref_block_prefix": 2,
            "expiration": "2026-08-31T12:01:00",
            "operations": [],
            "extensions": [],
            "signatures": [],
        }
        result = self.hive.network_broadcast_api.broadcast_transaction(
            trx=transaction,
            max_block_age=-1,
        )
        self.assertEqual(result, {})
        self.assert_last_request(
            "network_broadcast_api.broadcast_transaction",
            {"trx": transaction, "max_block_age": -1},
        )

    def test_legacy_call_envelope_remains_available(self):
        requests = []

        def legacy_node(url, data, timeout):
            request = json.loads(data.decode("ascii"))
            requests.append(request)
            return FakeResponse({
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"head_block_number": 123},
            })

        backend = HiveRemoteBackend(
            nodes=["https://legacy.example"],
            urlopen=legacy_node,
            appbase=True,
            rpc_style="legacy_call",
            max_retries=0,
        )
        hive = HiveInterface(backend)
        hive.database_api.get_dynamic_global_properties()

        self.assertEqual(requests[0]["method"], "call")
        self.assertEqual(
            requests[0]["params"],
            ["database_api", "get_dynamic_global_properties", {}],
        )

    def test_network_failure_exhausts_retry_budget(self):
        calls = []
        sleeps = []

        def unavailable(url, data, timeout):
            calls.append(timeout)
            raise urllib.error.URLError("offline")

        backend = HiveRemoteBackend(
            nodes=["https://hive.example"], urlopen=unavailable,
            max_retries=2, min_timeout=1, timeout_backoff=1,
            sleep_function=sleeps.append,
        )
        with self.assertRaises(HiveNetworkError):
            HiveInterface(backend).database_api.get_config()
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(sleeps, [1, 2])

    def test_socket_timeout_exhausts_retry_budget(self):
        attempts = []

        def timeout(url, data, request_timeout):
            attempts.append(request_timeout)
            raise socket.timeout("slow")

        backend = HiveRemoteBackend(
            nodes=["https://hive.example"], urlopen=timeout,
            max_retries=1, sleep_function=lambda seconds: None,
        )
        with self.assertRaises(HiveNetworkError):
            HiveInterface(backend).database_api.get_config()
        self.assertEqual(len(attempts), 2)

    def test_non_retryable_http_error_is_not_retried(self):
        attempts = []

        def missing(url, data, timeout):
            attempts.append(timeout)
            raise urllib.error.HTTPError(url, 404, "missing", {}, None)

        backend = HiveRemoteBackend(
            nodes=["https://hive.example"], urlopen=missing,
            max_retries=3, sleep_function=lambda seconds: None,
        )
        with self.assertRaises(HiveHTTPError):
            HiveInterface(backend).database_api.get_config()
        self.assertEqual(len(attempts), 1)

    def test_retryable_http_error_is_bounded(self):
        attempts = []

        def unavailable(url, data, timeout):
            attempts.append(timeout)
            raise urllib.error.HTTPError(url, 503, "busy", {}, None)

        backend = HiveRemoteBackend(
            nodes=["https://hive.example"], urlopen=unavailable,
            max_retries=2, sleep_function=lambda seconds: None,
        )
        with self.assertRaises(HiveHTTPError):
            HiveInterface(backend).database_api.get_config()
        self.assertEqual(len(attempts), 3)

    def test_non_json_response_is_normalized(self):
        backend = HiveRemoteBackend(
            nodes=["https://hive.example"],
            urlopen=lambda url, data, timeout: FakeResponse(b"not json", raw=True),
            max_retries=0,
        )
        with self.assertRaisesRegex(HiveResponseError, "non-JSON"):
            HiveInterface(backend).database_api.get_config()

    def test_mismatched_response_id_is_rejected(self):
        backend = HiveRemoteBackend(
            nodes=["https://hive.example"],
            urlopen=lambda url, data, timeout: FakeResponse({
                "jsonrpc": "2.0", "id": 999, "result": {},
            }),
            max_retries=0,
        )
        with self.assertRaisesRegex(HiveResponseError, "ID did not match"):
            HiveInterface(backend).database_api.get_config()

    def test_negative_retry_budget_is_rejected(self):
        with self.assertRaisesRegex(HiveIllegalArgument, "non-negative"):
            HiveRemoteBackend(nodes=["https://hive.example"], max_retries=-1)
