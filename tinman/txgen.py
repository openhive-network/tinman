#!/usr/bin/env python3

import argparse
import datetime
import hashlib
import itertools
import json
import os
import os.path
import random
import sys

import ijson
    
from . import __version__
from . import prockey
from . import timeutil
from . import util

SNAPSHOT_MAJOR_VERSION_SUPPORTED = 0
SNAPSHOT_MINOR_VERSION_SUPPORTED = 2
HIVE_GENESIS_TIMESTAMP = 1451606400
HIVE_BLOCK_INTERVAL = 3
NUM_BLOCKS_TO_CLEAR_WITNESS_ROUND = 21
TRANSACTION_WITNESS_SETUP_PAD = 100
HIVE_MAX_AUTHORITY_MEMBERSHIP = 10
DENOM = 10**12        # we need stupidly high precision because VESTS
HIVE_BLOCKS_PER_DAY = 28800
HIVE_ADDRESS_PREFIX = "TST"
HIVE_INIT_MINER_NAME = "initminer"
HIVE_LIQUID_NAI = "@@000000021"


def account_creation_fee(conf):
    fee = conf.get("account_creation_fee", amount(0))
    if not isinstance(fee, dict):
        raise RuntimeError("account_creation_fee must be an asset object")
    if fee.get("nai") != HIVE_LIQUID_NAI or fee.get("precision") != 3:
        raise RuntimeError("account_creation_fee must be a precision-3 HIVE asset")
    try:
        fee_amount = int(fee["amount"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("account_creation_fee has an invalid amount") from error
    if fee_amount < 0:
        raise RuntimeError("account_creation_fee cannot be negative")
    return amount(fee_amount)


def add_asset_units(asset, units):
    if asset.get("nai") != HIVE_LIQUID_NAI or asset.get("precision") != 3:
        raise RuntimeError("expected a precision-3 HIVE asset")
    return amount(satoshis(asset) + units)


def porter_vesting(conf, account_stats):
    configured = conf["accounts"]["porter"]["vesting"]
    per_account = conf.get("porter_vesting_per_snapshot_account", amount(0))
    if per_account.get("nai") != HIVE_LIQUID_NAI or per_account.get("precision") != 3:
        raise RuntimeError(
            "porter_vesting_per_snapshot_account must be a precision-3 HIVE asset"
        )
    required = satoshis(per_account) * len(account_stats["account_names"])
    return amount(max(satoshis(configured), required))


def replace_key_prefix(key, prefix):
    if not isinstance(key, str) or len(key) <= 3:
        raise RuntimeError("invalid public key")
    return prefix + key[3:]


def normalize_authority(authority, account_names, system_account_names,
                        manager_name, address_prefix, membership_limit):
    if membership_limit < 1:
        raise RuntimeError("hive_max_authority_membership must be positive")
    try:
        threshold = int(authority["weight_threshold"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("authority has an invalid weight threshold") from error
    if threshold < 1:
        raise RuntimeError("authority weight threshold must be positive")

    account_auths = []
    for account_name, weight in authority.get("account_auths", []):
        if account_name in account_names and account_name not in system_account_names:
            account_auths.append([account_name, weight])

    # The manager authority guarantees that each ported account remains operable.
    account_auths = account_auths[:membership_limit - 1]
    account_auths.append([manager_name, threshold])
    remaining = membership_limit - len(account_auths)
    key_auths = [
        [replace_key_prefix(key, address_prefix), weight]
        for key, weight in authority.get("key_auths", [])[:remaining]
    ]
    return {
        "account_auths": account_auths,
        "key_auths": key_auths,
        "weight_threshold": threshold,
    }

def create_system_accounts(conf, keydb, name, vesting_override=None):
    hive_init_miner_name = conf.get("hive_init_miner_name", HIVE_INIT_MINER_NAME)
    desc = conf["accounts"][name]
    for index in range(desc.get("count", 1)):
        name = desc["name"].format(index=index)
        yield {"operations" : [{"type" : "account_create_operation", "value" : {
            "fee" : account_creation_fee(conf),
            "creator" : desc["creator"],
            "new_account_name" : name,
            "owner" : keydb.get_authority(name, "owner"),
            "active" : keydb.get_authority(name, "active"),
            "posting" : keydb.get_authority(name, "posting"),
            "memo_key" : keydb.get_pubkey(name, "memo"),
            "json_metadata" : "",
           }}, {"type" : "transfer_to_vesting_operation", "value" : {
            "from" : hive_init_miner_name,
            "to" : name,
            "amount" : vesting_override or desc["vesting"],
           }}],
           "wif_sigs" : [keydb.get_privkey(desc["creator"])]}

    return

def vote_accounts(conf, keydb, elector, elected):
    er_desc = conf["accounts"][elector]
    ed_desc = conf["accounts"][elected]

    er_count = er_desc["count"]
    ed_count = ed_desc["count"]

    rr = itertools.cycle(range(ed_count))

    rand = random.Random(er_desc["randseed"])

    for er_index in range(er_desc["count"]):
        votes = []
        for i in range(er_desc["round_robin_votes_per_elector"]):
            votes.append(next(rr))
        for i in range(er_desc["random_votes_per_elector"]):
            votes.append(rand.randrange(0, ed_count))
        votes = sorted(set(votes))
        ops = []
        er_name = er_desc["name"].format(index=er_index)
        for ed_index in votes:
           ed_name = ed_desc["name"].format(index=ed_index)
           ops.append({"type" : "account_witness_vote_operation", "value" : {
            "account" : er_name,
            "witness" : ed_name,
            "approve" : True,
            }})
        yield {"operations" : ops, "wif_sigs" : [keydb.get_privkey(er_name)]}
    return

def update_witnesses(conf, keydb, name):
    desc = conf["accounts"][name]
    for index in range(desc["count"]):
        name = desc["name"].format(index=index)
        block_signing_key = keydb.get_pubkey(name, 'block')
        yield {"operations" : [{"type" : "witness_update_operation", "value" : {
            "owner" : name,
            "url" : "https://hive.blog/",
            "block_signing_key" : block_signing_key,
            "props" : {},
            "fee" : amount(0),
           }}],
           "wif_sigs" : [keydb.get_privkey(name)]}
    return

def build_setup_transactions(account_stats, conf, keydb, silent=True):
    yield from create_system_accounts(conf, keydb, "init")
    yield from create_system_accounts(conf, keydb, "elector")
    yield from create_system_accounts(conf, keydb, "manager")
    yield from create_system_accounts(
        conf, keydb, "porter", porter_vesting(conf, account_stats))
    yield from port_snapshot(account_stats, conf, keydb, silent)

def build_initminer_tx(conf, keydb):
    hive_init_miner_name = conf.get("hive_init_miner_name", HIVE_INIT_MINER_NAME)
    
    return {"operations" : [
     {"type" : "account_update_operation",
      "value" : {
       "account" : hive_init_miner_name,
       "owner" : keydb.get_authority(hive_init_miner_name, "owner"),
       "active" : keydb.get_authority(hive_init_miner_name, "active"),
       "posting" : keydb.get_authority(hive_init_miner_name, "posting"),
       "memo_key" : keydb.get_pubkey(hive_init_miner_name, "memo"),
       "json_metadata" : "",
      }},
     {"type" : "transfer_to_vesting_operation",
      "value" : {
       "from" : hive_init_miner_name,
       "to" : hive_init_miner_name,
       "amount" : conf["accounts"][hive_init_miner_name]["vesting"],
      }},
     {"type" : "account_witness_vote_operation",
      "value" : {
       "account" : hive_init_miner_name,
       "witness" : hive_init_miner_name,
       "approve" : True,
      }},
    ],
    "wif_sigs" : ["5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n"]}

def satoshis(s):
    return int(s["amount"])

def amount(satoshis, prec=3, symbol="@@000000021"):
    return {"amount" : str(satoshis), "precision" : prec, "nai" : symbol}

def get_system_account_names(conf):
    for desc in conf["accounts"].values():
        for index in range(desc.get("count", 1)):
            name = desc["name"].format(index=index)
            yield name
    yield from conf.get("existing_account_names", [])
    return

def get_account_stats(conf, silent=True):
    system_account_names = set(get_system_account_names(conf))
    vests = 0
    total_hive = 0
    account_names = set()
    
    with open(conf["snapshot_file"], "rb") as f:
        for acc in ijson.items(f, "accounts.item"):
            if acc["name"] in system_account_names:
                continue
            
            account_names.add(acc["name"])
            vests += satoshis(acc["vesting_shares"])
            total_hive += satoshis(acc["balance"])

            if not silent:
                n = len(account_names)
                if n % 100000 == 0:
                    print("Accounts read:", n)
    
    return {
      "account_names": account_names,
      "total_vests": vests,
      "total_hive": total_hive
    }

def get_proportions(account_stats, conf, silent=True):
    """
    We have a fixed amount of HIVE to give out, specified by total_port_balance
    This needs to be given out subject to the following constraints:
    - The ratio of vesting : liquid HIVE is the same on testnet,
    - Everyone's testnet balance is proportional to their mainnet balance
    - Everyone has at least min_vesting_per_account
    """
    
    total_vests = account_stats["total_vests"]
    total_hive = account_stats["total_hive"]
    account_names = account_stats["account_names"]
    num_accounts = len(account_names)
    
    with open(conf["snapshot_file"], "rb") as f:
        for prefix, event, value in ijson.parse(f):
            if prefix == "dynamic_global_properties.total_vesting_fund_hive.amount":
                total_vesting_hive = int(value)
                break
    
    min_vesting_per_account = satoshis(conf["min_vesting_per_account"])
    total_port_balance = satoshis(conf["total_port_balance"])
    avail_port_balance = total_port_balance - min_vesting_per_account * num_accounts
    if avail_port_balance < 0:
        raise RuntimeError("Increase total_port_balance or decrease min_vesting_per_account")
    total_port_vesting = (avail_port_balance * total_vesting_hive) // (total_hive + total_vesting_hive)
    total_port_liquid = (avail_port_balance * total_hive) // (total_hive + total_vesting_hive)
    
    if total_vests == 0:
        vest_conversion_factor = 1
    else:
        vest_conversion_factor  = (DENOM * total_port_vesting) // total_vests
        
    if total_hive == 0:
        hive_conversion_factor = 1
    else:
        hive_conversion_factor = (DENOM * total_port_liquid ) // total_hive
    
    if not silent:
        print("total_vests:", total_vests)
        print("total_hive:", total_hive)
        print("total_vesting_hive:", total_vesting_hive)
        print("total_port_balance:", total_port_balance)
        print("total_port_vesting:", total_port_vesting)
        print("total_port_liquid:", total_port_liquid)
        print("vest_conversion_factor:", vest_conversion_factor)
        print("hive_conversion_factor:", hive_conversion_factor)
    
    return {
      "min_vesting_per_account": min_vesting_per_account,
      "vest_conversion_factor": vest_conversion_factor,
      "hive_conversion_factor": hive_conversion_factor
    }

def create_accounts(account_stats, conf, keydb, silent=True):
    hive_address_prefix = conf.get("hive_address_prefix", HIVE_ADDRESS_PREFIX)
    system_account_names = set(get_system_account_names(conf))
    proportions = get_proportions(account_stats, conf, silent)
    min_vesting_per_account = proportions["min_vesting_per_account"]
    vest_conversion_factor = proportions["vest_conversion_factor"]
    hive_conversion_factor = proportions["hive_conversion_factor"]
    account_names = account_stats["account_names"]
    num_accounts = len(account_names)
    porter = conf["accounts"]["porter"]["name"]
    porter_wif = keydb.get_privkey(porter)
    create_auth = {"account_auths" : [[porter, 1]], "key_auths" : [], "weight_threshold" : 1}
    accounts_created = 0
    
    with open(conf["snapshot_file"], "rb") as f:
        for a in ijson.items(f, "accounts.item"):
            if a["name"] in system_account_names:
                continue
            
            vesting_amount = (satoshis(a["vesting_shares"]) * vest_conversion_factor) // DENOM
            transfer_amount = (satoshis(a["balance"]) * hive_conversion_factor) // DENOM
            name = a["name"]
            vesting_amount = max(vesting_amount, min_vesting_per_account)
            
            ops = [{"type" : "account_create_operation", "value" : {
              "fee" : account_creation_fee(conf),
              "creator" : porter,
              "new_account_name" : name,
              "owner" : create_auth,
              "active" : create_auth,
              "posting" : create_auth,
              "memo_key" : replace_key_prefix(a["memo_key"], hive_address_prefix),
              "json_metadata" : "",
             }}, {"type" : "transfer_to_vesting_operation", "value" : {
              "from" : porter,
              "to" : name,
              "amount" : amount(vesting_amount),
             }}]
            if transfer_amount > 0:
                ops.append({"type" : "transfer_operation", "value" : {
                 "from" : porter,
                 "to" : name,
                 "amount" : amount(transfer_amount),
                 "memo" : "Ported balance",
                 }})
            
            accounts_created += 1
            if not silent:
                if accounts_created % 100000 == 0:
                    print("Accounts created:", accounts_created)
                    print("\t", '%.2f%% complete' % (accounts_created / num_accounts * 100.0))

            yield {"operations" : ops, "wif_sigs" : [porter_wif]}
            
    if not silent:
        print("Accounts created:", accounts_created)
        print("\t100.00%% complete")

def update_accounts(account_stats, conf, keydb, silent=True):
    hive_max_authority_membership = conf.get("hive_max_authority_membership", HIVE_MAX_AUTHORITY_MEMBERSHIP)
    hive_address_prefix = conf.get("hive_address_prefix", HIVE_ADDRESS_PREFIX)
    system_account_names = set(get_system_account_names(conf))
    account_names = account_stats["account_names"]
    num_accounts = len(account_names)
    porter = conf["accounts"]["porter"]["name"]
    porter_wif = keydb.get_privkey(porter)
    tnman = conf["accounts"]["manager"]["name"]
    accounts_updated = 0

    with open(conf["snapshot_file"], "rb") as f:
        for a in ijson.items(f, "accounts.item"):
            if a["name"] in system_account_names:
                continue
            
            new_owner_auth = normalize_authority(
                a["owner"], account_names, system_account_names, tnman,
                hive_address_prefix, hive_max_authority_membership)
            new_active_auth = normalize_authority(
                a["active"], account_names, system_account_names, tnman,
                hive_address_prefix, hive_max_authority_membership)
            new_posting_auth = normalize_authority(
                a["posting"], account_names, system_account_names, tnman,
                hive_address_prefix, hive_max_authority_membership)

            json_metadata = a["json_metadata"]
            if json_metadata:
                try:
                    json.loads(json_metadata)
                except (TypeError, ValueError) as error:
                    raise RuntimeError(
                        "account {} has invalid JSON metadata".format(a["name"])
                    ) from error

            ops = [{"type" : "account_update_operation", "value" : {
              "account" : a["name"],
              "owner" : new_owner_auth,
              "active" : new_active_auth,
              "posting" : new_posting_auth,
              "memo_key" : replace_key_prefix(a["memo_key"], hive_address_prefix),
              "json_metadata" : json_metadata,
              }}]

            accounts_updated += 1
            if not silent:
                if accounts_updated % 100000 == 0:
                    print("Accounts updated:", accounts_updated)
                    print("\t", '%.2f%% complete' % (accounts_updated / num_accounts * 100.0))
            
            yield {"operations" : ops, "wif_sigs" : [porter_wif]}
    
    if not silent:
        print("Accounts updated:", accounts_updated)
        print("\t100.00%% complete")

def port_snapshot(account_stats, conf, keydb, silent=True):
    hive_init_miner_name = conf.get("hive_init_miner_name", HIVE_INIT_MINER_NAME)
    porter = conf["accounts"]["porter"]["name"]

    fee_reserve = satoshis(account_creation_fee(conf)) * len(account_stats["account_names"])
    porter_funding = add_asset_units(conf["total_port_balance"], fee_reserve)

    yield {"operations" : [
      {"type" : "transfer_operation",
      "value" : {"from" : hive_init_miner_name,
       "to" : porter,
       "amount" : porter_funding,
       "memo" : "Fund porting balances and account creation fees",
      }}],
       "wif_sigs" : [keydb.get_privkey(hive_init_miner_name)]}

    yield from create_accounts(account_stats, conf, keydb, silent)
    yield from update_accounts(account_stats, conf, keydb, silent)
    
    return

def build_actions(conf, silent=True):
    keydb = prockey.ProceduralKeyDatabase()
    account_stats_start = timeutil.utc_now()
    account_stats = get_account_stats(conf, silent)
    account_stats_elapsed = timeutil.utc_now() - account_stats_start
    account_names = account_stats["account_names"]
    num_accounts = len(account_names)
    transactions_per_block = conf["transactions_per_block"]
    hive_block_interval = conf.get("hive_block_interval", HIVE_BLOCK_INTERVAL)
    transaction_witness_setup_pad = conf.get("transaction_witness_setup_pad", TRANSACTION_WITNESS_SETUP_PAD)
    
    hive_genesis_timestamp = conf.get("hive_genesis_timestamp", HIVE_GENESIS_TIMESTAMP)
    genesis_time = timeutil.utc_fromtimestamp(hive_genesis_timestamp)
    
    # Three transactions per account (create, trasnfer_to_vesting, and update).
    predicted_transaction_count = num_accounts * 3
    
    # The predicted number of blocks for accounts.
    predicted_block_count = (
        predicted_transaction_count + transactions_per_block - 1
    ) // transactions_per_block
    
    # The number of seconds required to setup transactions is a multiple of
    # the initial time it takes to do the get_account_stats() call.
    predicted_transaction_setup_seconds = (account_stats_elapsed.seconds * 2)
    
    # Pad for update witnesses, vote witnesses, clear rounds, and transaction
    # setup processing time
    predicted_block_count += transaction_witness_setup_pad + (predicted_transaction_setup_seconds // hive_block_interval)
    
    now = timeutil.utc_now()
    start_time = now - datetime.timedelta(seconds=predicted_block_count * hive_block_interval)
    miss_blocks = int((start_time - genesis_time).total_seconds()) // hive_block_interval
    miss_blocks = max(miss_blocks-1, 0)
    origin_api = None
    snapshot_head_block_num = None
    snapshot_semver = None
    has_backfill = False
    
    metadata = {
      "txgen:semver": __version__,
      "txgen:transactions_per_block": transactions_per_block,
      "epoch:created": str(now),
      "actions:count": predicted_transaction_count,
      "recommend:miss_blocks": miss_blocks
    }

    with open(conf["snapshot_file"], "rb") as f:
        for prefix, event, value in ijson.parse(f):
            if prefix == "metadata.snapshot:origin_api":
                metadata["snapshot:origin_api"] = value
            if prefix == "metadata.snapshot:semver":
                metadata["snapshot:semver"] = value
            if prefix == "dynamic_global_properties.head_block_number":
                metadata["snapshot:head_block_num"] = value
            
            if not prefix == '' and not prefix.startswith("metadata") and not prefix.startswith("dynamic_global_properties"):
                break
    
    semver = metadata.get("snapshot:semver", '0.0')
    major_version, minor_version = semver.split('.')
    major_version = int(major_version)
    minor_version = int(minor_version)
    backfill_file = conf.get("backfill_file", None)
    
    if major_version == SNAPSHOT_MAJOR_VERSION_SUPPORTED:
        if not silent:
            print("metadata:", metadata)
    else:
        raise RuntimeError("Unsupported snapshot:", metadata)
    
    if minor_version < SNAPSHOT_MINOR_VERSION_SUPPORTED:
        print("WARNING: Older snapshot encountered.", file=sys.stderr)
    
    if backfill_file and os.path.exists(backfill_file) and os.path.isfile(backfill_file):
        with open(backfill_file, "r") as f:
            num_lines = sum(1 for line in f)
        
        if num_lines > 0:
            metadata["backfill_actions:count"] = num_lines
            metadata["actions:count"] += num_lines
            miss_blocks -= max(num_lines // transactions_per_block, HIVE_BLOCKS_PER_DAY * 30)
            metadata["recommend:miss_blocks"] = miss_blocks
            has_backfill = True
    
    yield ["metadata", metadata]
    yield ["wait_blocks", {"count" : 1, "miss_blocks" : miss_blocks}]
    yield ["submit_transaction", {"tx" : build_initminer_tx(conf, keydb)}]
    for b in util.batch(build_setup_transactions(account_stats, conf, keydb, silent), transactions_per_block):
        for tx in b:
            yield ["submit_transaction", {"tx" : tx}]
    
    if has_backfill:
        with open(backfill_file, "r") as f:
            for line in f:
                yield json.loads(line)
        
        yield ["metadata", {"post_backfill" : True}]
    
    for tx in update_witnesses(conf, keydb, "init"):
        yield ["submit_transaction", {"tx" : tx}]
    for tx in vote_accounts(conf, keydb, "elector", "init"):
        yield ["submit_transaction", {"tx" : tx}]

    yield ["wait_blocks", {"count" : conf.get("num_blocks_to_clear_witness_round", NUM_BLOCKS_TO_CLEAR_WITNESS_ROUND)}]
    return

def log_config(conf, file):
    keys = ["transactions_per_block", "hive_block_interval",
      "num_blocks_to_clear_witness_round", "transaction_witness_setup_pad",
      "hive_max_authority_membership", "hive_address_prefix",
      "hive_init_miner_name", "hive_genesis_timestamp",
      "account_creation_fee", "porter_vesting_per_snapshot_account"]
    
    print("Using config:", file, file=sys.stderr)
    
    for key in keys:
        print(key, "=", conf.get(key, "<DEFAULT>"), file=sys.stderr)
    
def main(argv):
    parser = argparse.ArgumentParser(prog=argv[0], description="Generate transactions for Hive testnet")
    parser.add_argument("-c", "--conffile", default="txgen.conf", dest="conffile", metavar="FILE", help="Specify configuration file")
    parser.add_argument("-o", "--outfile", default="-", dest="outfile", metavar="FILE", help="Specify output file, - means stdout")
    args = parser.parse_args(argv[1:])

    with open(args.conffile, "r") as f:
        conf = json.load(f)
        log_config(conf, args.conffile)
    
    if args.outfile == "-":
        outfile = sys.stdout
    else:
        outfile = open(args.outfile, "w")

    for action in build_actions(conf, args.outfile == "-"):
        outfile.write(util.action_to_str(action))
        outfile.write("\n")

    outfile.flush()
    if args.outfile != "-":
        outfile.close()

if __name__ == "__main__":
    main(sys.argv)
