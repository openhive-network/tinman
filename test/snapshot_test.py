import unittest
import json
import shutil

from tinman import snapshot
from simple_hive_client.client import HiveRemoteBackend, HiveInterface, HiveRPCException

class SnapshotTest(unittest.TestCase):
    def test_list_all_accounts(self):
        backend = HiveRemoteBackend(nodes=["http://test.com"], appbase=True)
        hived = HiveInterface(backend)
        self.assertIsNotNone(snapshot.list_all_accounts(hived))
