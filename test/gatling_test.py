import unittest
from unittest import mock

from simple_hive_client.client import HiveInterface, HiveRPCException

from tinman import gatling


class GatlingTest(unittest.TestCase):
    def test_block_rpc_retry_does_not_duplicate_operations(self):
        hived = HiveInterface()
        hived.database_api = mock.Mock()
        hived.database_api.get_dynamic_global_properties.return_value = {
            "head_block_number": 2,
        }
        hived.block_api = mock.Mock()
        hived.block_api.get_block.side_effect = [
            HiveRPCException({"error": {"message": "Internal Error"}}),
            {"block": {"transactions": [{"operations": [{
                "type": "vote_operation", "value": {},
            }]}]}},
        ]
        conf = {
            "transaction_source": {"node": "unused", "appbase": "true"},
            "ported_operations": [{"type": "vote_operation", "roles": ["posting"]}],
            "transaction_signer": "alice",
            "transactions_per_block": 10,
        }

        with mock.patch.object(gatling, "HiveRemoteBackend"), mock.patch.object(
                gatling, "HiveInterface", return_value=hived), mock.patch.object(
                gatling.prockey, "ProceduralKeyDatabase") as key_database:
            key_database.return_value.get_privkey.return_value = "private"
            actions = list(gatling.build_actions(conf, 1, 2, -1, -1))

        self.assertEqual(len(actions), 1)
        self.assertEqual(
            actions[0][1]["tx"]["operations"][0]["type"], "vote_operation"
        )
        self.assertEqual(hived.block_api.get_block.call_count, 2)


if __name__ == "__main__":
    unittest.main()
