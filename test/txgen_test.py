import copy
from pathlib import Path
import unittest
import shutil
import tempfile
from unittest import mock

from tinman import prockey
from tinman import txgen

TEST_DIR = Path(__file__).resolve().parent

FULL_CONF = {
    "transactions_per_block" : 40,
    "hive_block_interval" : 3,
    "num_blocks_to_clear_witness_round" : 21,
    "transaction_witness_setup_pad" : 100,
    "hive_max_authority_membership" : 10,
    "hive_address_prefix" : "TST",
    "hive_init_miner_name" : 'initminer',
    "account_creation_fee" : {"amount" : "0", "precision" : 3, "nai" : "@@000000021"},
    "porter_vesting_per_snapshot_account" : {"amount" : "20000", "precision" : 3, "nai" : "@@000000021"},
    "snapshot_file" : None,
    "backfill_file" : None,
    "min_vesting_per_account" : {"amount" : "5000", "precision" : 3, "nai" : "@@000000021"},
    "total_port_balance" : {"amount" : "200000000000", "precision" : 3, "nai" : "@@000000021"},
    "accounts" : {
        "initminer" : {
            "name" : "initminer",
            "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"}
        }, "init" : {
            "name" : "init-{index}",
            "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"},
            "count" : 21,
            "creator" : "initminer"
        }, "elector" : {
            "name" : "elect-{index}",
            "vesting" : {"amount" : "1000000000", "precision" : 3, "nai" : "@@000000021"},
            "count" : 10,
            "round_robin_votes_per_elector" : 2,
            "random_votes_per_elector" : 3,
            "randseed" : 1234,
            "creator" : "initminer"
        }, "porter" : {
            "name" : "porter",
            "creator" : "initminer",
            "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"}
        }, "manager" : {
            "name" : "tnman",
            "creator" : "initminer",
            "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"}
        },
            "HIVE_MINER_ACCOUNT" : {"name" : "mners"},
            "HIVE_NULL_ACCOUNT" : {"name" : "null"},
            "HIVE_TEMP_ACCOUNT" : {"name" : "temp"}
        }
    }

class TxgenTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def copy_fixture(self, filename):
        destination = Path(self.temp_dir.name) / filename
        shutil.copyfile(TEST_DIR / filename, destination)
        return str(destination)

    def test_create_system_accounts_bad_args(self):
        self.assertRaises(TypeError, txgen.create_system_accounts)

    def test_create_system_accounts_uses_configured_fee(self):
        keydb = prockey.ProceduralKeyDatabase()
        conf = {
            "account_creation_fee": {
                "amount": "30", "precision": 3, "nai": "@@000000021"
            },
            "accounts": {
                "porter": {
                    "name": "porter", "creator": "initminer",
                    "vesting": txgen.amount(1000),
                }
            },
        }
        transaction = next(txgen.create_system_accounts(conf, keydb, "porter"))
        self.assertEqual(
            transaction["operations"][0]["value"]["fee"], txgen.amount(30)
        )

    def test_porter_vesting_scales_with_snapshot_size(self):
        conf = {
            "porter_vesting_per_snapshot_account": txgen.amount(20000),
            "accounts": {"porter": {"vesting": txgen.amount(1000000)}},
        }
        account_stats = {"account_names": set(range(2000))}
        self.assertEqual(
            txgen.porter_vesting(conf, account_stats), txgen.amount(40000000)
        )

    def test_porter_vesting_keeps_larger_configured_minimum(self):
        conf = {
            "porter_vesting_per_snapshot_account": txgen.amount(20000),
            "accounts": {"porter": {"vesting": txgen.amount(1000000)}},
        }
        account_stats = {"account_names": {"alice"}}
        self.assertEqual(
            txgen.porter_vesting(conf, account_stats), txgen.amount(1000000)
        )
    
    def test_create_witnesses(self):
        keydb = prockey.ProceduralKeyDatabase()
        conf = {"accounts": {
            "init": {
                "name" : "init-{index}",
                "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"},
                "count" : 21,
                "creator" : "initminer"
            }
        }}
        
        for witness in txgen.create_system_accounts(conf, keydb, "init"):
            self.assertEqual(len(witness["operations"]), 2)
            self.assertEqual(len(witness["wif_sigs"]), 1)
            account_create_operation, transfer_to_vesting_operation = witness["operations"]
            
            self.assertEqual(account_create_operation["type"], "account_create_operation")
            value = account_create_operation["value"]
            self.assertEqual(value["fee"], {"amount" : "0", "precision" : 3, "nai" : "@@000000021"})
            self.assertEqual(value["creator"], "initminer")
            
            self.assertEqual(transfer_to_vesting_operation["type"], "transfer_to_vesting_operation")
            value = transfer_to_vesting_operation["value"]
            self.assertEqual(value["from"], "initminer")
            self.assertEqual(value["amount"], {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"})

    def test_update_witnesses(self):
        keydb = prockey.ProceduralKeyDatabase()
        conf = {"accounts": {
            "init": {
                "name" : "init-{index}",
                "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"},
                "count" : 21,
                "creator" : "initminer"
            }
        }}
        
        for witness in txgen.update_witnesses(conf, keydb, "init"):
            self.assertEqual(len(witness["operations"]), 1)
            self.assertEqual(len(witness["wif_sigs"]), 1)
            
            for op in witness["operations"]:
                self.assertEqual(op["type"], "witness_update_operation")
                value = op["value"]
                self.assertEqual(value["url"], "https://hive.blog/")
                self.assertEqual(value["props"], {})
                self.assertEqual(value["fee"], {"amount" : "0", "precision" : 3, "nai" : "@@000000021"})

    def test_vote_witnesses(self):
        keydb = prockey.ProceduralKeyDatabase()
        conf = {"accounts": {
            "init": {
                "name" : "init-{index}",
                "vesting" : {"amount" : "1000000", "precision" : 3, "nai" : "@@000000021"},
                "count" : 21,
                "creator" : "initminer"
            }, "elector" : {
                "name" : "elect-{index}",
                "vesting" : {"amount" : "1000000000", "precision" : 3, "nai" : "@@000000021"},
                "count" : 10,
                "round_robin_votes_per_elector" : 2,
                "random_votes_per_elector" : 3,
                "randseed" : 1234,
                "creator" : "initminer"
            }
        }}
        
        for witness in txgen.vote_accounts(conf, keydb, "elector", "init"):
            self.assertGreater(len(witness["operations"]), 1)
            self.assertEqual(len(witness["wif_sigs"]), 1)
            
            for op in witness["operations"]:
                self.assertEqual(op["type"], "account_witness_vote_operation")
                value = op["value"]
                self.assertTrue(value["approve"])

    def test_get_account_stats(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "accounts": {}
        }
        
        account_stats = txgen.get_account_stats(conf)
        expected_account_names = {"steemit", "binance-hot", "alpha",
            "upbitsteemhot", "blocktrades", "steemit2", "ned", "holiday",
            "imadev", "muchfun", "poloniex", "gopax-deposit", "dan",
            "bithumb.sunshine", "ben", "dantheman", "openledger-dex", "bittrex",
            "huobi-withdrawal", "korbit3", "hellosteem"
        }
        
        self.assertEqual(account_stats["account_names"], expected_account_names)
        self.assertEqual(account_stats["total_vests"], 103927120221962824)
        self.assertEqual(account_stats["total_hive"], 60859732440)

    def test_get_account_stats_excludes_live_genesis_accounts(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "existing_account_names": ["steemit"],
          "accounts": {}
        }

        account_stats = txgen.get_account_stats(conf)

        self.assertNotIn("steemit", account_stats["account_names"])
        self.assertEqual(len(account_stats["account_names"]), 20)

    def test_get_proportions(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "min_vesting_per_account": {"amount" : "1", "precision" : 3, "nai" : "@@000000021"},
          "total_port_balance" : {"amount" : "200000000000", "precision" : 3, "nai" : "@@000000021"},
          "accounts": {}
        }
        account_stats = txgen.get_account_stats(conf)
        proportions = txgen.get_proportions(account_stats, conf)
        
        self.assertEqual(proportions["min_vesting_per_account"], 1)
        self.assertEqual(proportions["vest_conversion_factor"], 1469860)
        self.assertEqual(proportions["hive_conversion_factor"], 776237928593)

    def test_create_accounts(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "min_vesting_per_account": {"amount" : "1", "precision" : 3, "nai" : "@@000000021"},
          "total_port_balance" : {"amount" : "200000000000", "precision" : 3, "nai" : "@@000000021"},
          "accounts": {"porter": {"name": "porter"}
          }
        }
        keydb = prockey.ProceduralKeyDatabase()
        account_stats = txgen.get_account_stats(conf)
        
        for account in txgen.create_accounts(account_stats, conf, keydb):
            self.assertEqual(len(account["operations"]), 3)
            self.assertEqual(len(account["wif_sigs"]), 1)
            
            for op in account["operations"]:
                value = op["value"]
                if op["type"] == "account_create_operation":
                    self.assertEqual(value["fee"], {"amount" : "0", "precision" : 3, "nai" : "@@000000021"})
                elif op["type"] == "transfer_to_vesting_operation":
                    self.assertEqual(value["from"], "porter")
                    self.assertGreater(int(value["amount"]["amount"]), 0)
                elif op["type"] == "transfer_operation":
                    self.assertEqual(value["from"], "porter")
                    self.assertGreater(int(value["amount"]["amount"]), 0)
                    self.assertEqual(value["memo"], "Ported balance")

    def test_custom_porter_name_controls_authority_and_signatures(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "min_vesting_per_account": txgen.amount(1),
          "total_port_balance" : txgen.amount(200000000000),
          "accounts": {
              "porter": {"name": "snapshot-porter"},
              "manager": {"name": "tnman"},
          },
        }
        keydb = mock.Mock()
        keydb.get_privkey.return_value = "porter-wif"
        account_stats = txgen.get_account_stats(conf)

        created = next(txgen.create_accounts(account_stats, conf, keydb))
        updated = next(txgen.update_accounts(account_stats, conf, keydb))

        create_value = created["operations"][0]["value"]
        self.assertEqual(
            create_value["owner"]["account_auths"], [["snapshot-porter", 1]]
        )
        self.assertEqual(created["wif_sigs"], ["porter-wif"])
        self.assertEqual(updated["wif_sigs"], ["porter-wif"])
        keydb.get_privkey.assert_called_with("snapshot-porter")

    def test_port_snapshot_reserves_account_creation_fees(self):
        conf = {
            "account_creation_fee": txgen.amount(30),
            "total_port_balance": txgen.amount(1000),
            "accounts": {
                "initminer": {"name": "initminer"},
                "porter": {"name": "porter"},
            },
        }
        account_stats = {"account_names": {"alice", "bob"}}
        transaction = next(txgen.port_snapshot(
            account_stats, conf, prockey.ProceduralKeyDatabase()
        ))
        transfer = transaction["operations"][0]["value"]
        self.assertEqual(transfer["amount"], txgen.amount(1060))

    def test_normalize_authority_enforces_combined_membership_limit(self):
        authority = {
            "weight_threshold": 2,
            "account_auths": [["alice", 1], ["missing", 1]],
            "key_auths": [["STMabc", 1], ["STMdef", 1]],
        }
        normalized = txgen.normalize_authority(
            authority, {"alice"}, set(), "tnman", "HIVE", 3
        )
        self.assertEqual(
            normalized["account_auths"], [["alice", 1], ["tnman", 2]]
        )
        self.assertEqual(normalized["key_auths"], [["HIVEabc", 1]])
        self.assertEqual(
            len(normalized["account_auths"]) + len(normalized["key_auths"]), 3
        )


    def test_update_accounts(self):
        conf = {
          "snapshot_file" : self.copy_fixture("test-snapshot.json"),
          "min_vesting_per_account": {"amount" : "1", "precision" : 3, "nai" : "@@000000021"},
          "total_port_balance" : {"amount" : "200000000000", "precision" : 3, "nai" : "@@000000021"},
          "accounts": {
              "manager": {"name": "tnman"},
              "porter": {"name": "porter"},
          }
        }
        keydb = prockey.ProceduralKeyDatabase()
        account_stats = txgen.get_account_stats(conf)
        
        for account in txgen.update_accounts(account_stats, conf, keydb):
            self.assertEqual(len(account["operations"]), 1)
            self.assertEqual(len(account["wif_sigs"]), 1)
            for op in account["operations"]:
                value = op["value"]
                self.assertIn(["tnman", 1], value["owner"]["account_auths"])
                self.assertLessEqual(len(value["owner"]["account_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                self.assertLessEqual(len(value["active"]["account_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                self.assertLessEqual(len(value["posting"]["account_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                self.assertLessEqual(len(value["owner"]["key_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                self.assertLessEqual(len(value["active"]["key_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                self.assertLessEqual(len(value["posting"]["key_auths"]), txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP)
                for authority_name in ("owner", "active", "posting"):
                    authority = value[authority_name]
                    self.assertLessEqual(
                        len(authority["account_auths"]) + len(authority["key_auths"]),
                        txgen.HIVE_MAX_AUTHORITY_MEMBERSHIP,
                    )
            
    def test_build_actions(self):
        conf = copy.deepcopy(FULL_CONF)
        conf["snapshot_file"] = self.copy_fixture("test-snapshot.json")
        conf["backfill_file"] = self.copy_fixture("test-backfill.actions")

        for action in txgen.build_actions(conf):
            cmd, args = action
            
            if cmd == "metadata":
                if not args.get("post_backfill"):
                    self.assertEqual(args["txgen:semver"], "0.3")
                    self.assertEqual(args["txgen:transactions_per_block"], 40)
                    self.assertIsNotNone(args["epoch:created"])
                    self.assertEqual(args["actions:count"], 73)
                    self.assertGreater(args["recommend:miss_blocks"], 28631339)
                    self.assertEqual(args["snapshot:semver"], "0.2")
                    self.assertEqual(args["snapshot:origin_api"], "http://calculon.local")
            elif cmd == "wait_blocks":
                self.assertGreater(args["count"], 0)
            elif cmd == "submit_transaction":
                self.assertGreater(len(args["tx"]["operations"]), 0)
                self.assertIsInstance(args["tx"]["wif_sigs"], list)
                for wif in args["tx"]["wif_sigs"]:
                    if isinstance(wif, str):
                        esc = args.get("esc", None)
                        
                        if esc and len(wif) < 51:
                            self.assertEqual(esc, wif[0])
                            self.assertEqual(esc, wif[-1])
                        else:
                            self.assertEqual(len(wif), 51)
                    else:
                        self.assertIsInstance(wif, prockey.ProceduralPrivateKey)
            else:
                self.fail("Unexpected action: %s" % cmd)

    def test_build_actions_future_snapshot(self):
        conf = copy.deepcopy(FULL_CONF)
        conf["snapshot_file"] = self.copy_fixture("test-future-snapshot.json")
        
        with self.assertRaises(RuntimeError) as ctx:
            for action in txgen.build_actions(conf):
                cmd, args = action
        
        self.assertIn('Unsupported snapshot', str(ctx.exception))

    def test_build_actions_no_main_accounts_snapshot(self):
        system_account_names = ["init-0", "init-1", "init-2", "init-3", "init-4",
            "init-5", "init-6", "init-7", "init-8", "init-9", "init-10", "init-11",
            "init-12", "init-13", "init-14", "init-15", "init-16", "init-17",
            "init-18", "init-19", "init-20", "elect-0", "elect-1", "elect-2",
            "elect-3", "elect-4", "elect-5", "elect-6", "elect-7", "elect-8",
            "elect-9", "tnman", "porter"]
        
        conf = copy.deepcopy(FULL_CONF)
        conf["snapshot_file"] = self.copy_fixture("test-no-main-accounts-snapshot.json")
        created_account_names = []

        for action in txgen.build_actions(conf):
            cmd, args = action
            
            if cmd == "submit_transaction":
                for operation in args["tx"]["operations"]:
                    if operation["type"] == 'account_create_operation':
                        new_account_name = operation["value"]['new_account_name']
                        self.assertIn(new_account_name, system_account_names)
                        created_account_names.append(new_account_name)

        self.assertEqual(set(created_account_names), set(system_account_names))
