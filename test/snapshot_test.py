import unittest
from unittest import mock

from tinman import snapshot
from simple_hive_client.client import HiveRPCException

class SnapshotTest(unittest.TestCase):
    def test_list_all_accounts(self):
        hived = mock.Mock()
        hived.database_api.list_accounts.side_effect = [
            {"accounts": [{"name": "alice"}, {"name": "bob"}]},
            {"accounts": [{"name": "bob"}, {"name": "carol"}]},
            {"accounts": [{"name": "carol"}]},
        ]

        accounts = list(snapshot.list_all_accounts(hived))

        self.assertEqual([account["name"] for account in accounts], [
            "alice", "bob", "carol",
        ])

    def test_list_all_accounts_retries_each_page_independently(self):
        hived = mock.Mock()
        pages = [
            {"accounts": [{"name": "account-{:03d}".format(index)}]}
            for index in range(35)
        ]
        transient = HiveRPCException({
            "error": {"message": "Internal Error"}
        })
        hived.database_api.list_accounts.side_effect = (
            pages + [transient, {"accounts": [{"name": "account-034"}]}]
        )

        with mock.patch.object(snapshot.util.time, "sleep"):
            accounts = list(snapshot.list_all_accounts(hived))

        self.assertEqual(len(accounts), 35)
