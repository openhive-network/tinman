import importlib.util
from pathlib import Path
import unittest

from simple_hive_client.client import HiveInterface, HiveRemoteBackend
from rpc_contract_test import RecordingHiveNode


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hive_compatibility.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location("hive_compatibility", SCRIPT_PATH)
hive_compatibility = importlib.util.module_from_spec(SCRIPT_SPEC)
SCRIPT_SPEC.loader.exec_module(hive_compatibility)


class HiveCompatibilityTest(unittest.TestCase):
    def test_read_only_probe_captures_chain_profile(self):
        node = RecordingHiveNode()
        hive = HiveInterface(HiveRemoteBackend(
            nodes=["https://hive.example"],
            urlopen=node,
            appbase=True,
            max_retries=0,
        ))

        profile = hive_compatibility.read_only_probe(hive)

        self.assertEqual(profile["chain_id"], "test-chain-id")
        self.assertEqual(profile["active_hardfork"], "1.28.0")
        self.assertTrue(profile["is_testnet"])
        self.assertEqual(profile["address_prefix"], "TST")
        self.assertEqual(profile["max_authority_membership"], 40)
        self.assertEqual(profile["block_interval"], 3)
        self.assertEqual(profile["account_creation_fee"]["amount"], "30")

    def test_fastgen_profiles_again_after_pristine_chain_first_block(self):
        node = RecordingHiveNode()
        hive = HiveInterface(HiveRemoteBackend(
            nodes=["https://hive.example"],
            urlopen=node,
            appbase=True,
            max_retries=0,
        ))

        profile, generated = hive_compatibility.fastgen_chain_profile(
            hive, {
                "head_block_number": 0,
                "head_block_time": "2016-01-01T00:00:00",
                "block_interval": 3,
            }
        )

        self.assertTrue(generated)
        self.assertEqual(profile["account_creation_fee"]["amount"], "30")
        methods = [request[2]["method"] for request in node.requests]
        self.assertEqual(methods[0], "debug_node_api.debug_generate_blocks")
        self.assertGreater(node.requests[0][2]["params"]["miss_blocks"], 0)


if __name__ == "__main__":
    unittest.main()
