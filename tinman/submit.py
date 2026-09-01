#!/usr/bin/env python3

from simple_hive_client.client import HiveRemoteBackend, HiveInterface

from binascii import hexlify, unhexlify

import argparse
import datetime
import hashlib
import itertools
import json
import struct
import subprocess
import sys
import time
import traceback

from . import timeutil
from . import util

ACTIONS_MAJOR_VERSION_SUPPORTED = 0
ACTIONS_MINOR_VERSION_SUPPORTED = 2
HIVE_BLOCK_INTERVAL = 3

class TransactionSigner(object):
    def __init__(self, sign_transaction_exe=None, chain_id=None):
        if(chain_id is None):
            self.proc = subprocess.Popen([sign_transaction_exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        else:
            self.proc = subprocess.Popen([sign_transaction_exe, "--chain-id="+chain_id], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        return

    def sign_transaction(self, tx, wif):
        json_data = json.dumps({"tx":tx, "wif":wif}, separators=(",", ":"), sort_keys=True)
        json_data_bytes = json_data.encode("ascii")
        self.proc.stdin.write(json_data_bytes)
        self.proc.stdin.write(b"\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline().decode("utf-8")
        return json.loads(line)

class CachedDgpo(object):
    def __init__(self, timefunc=time.time, refresh_interval=1.0, hived=None):
        self.timefunc = timefunc
        self.refresh_interval = refresh_interval
        self.hived = hived

        self.dgpo = None
        self.last_refresh = self.timefunc()

        return

    def reset(self):
        self.dgpo = None

    def get(self):
        now = self.timefunc()
        if (now - self.last_refresh) > self.refresh_interval:
            self.reset()
        if self.dgpo is None:
            self.dgpo = self.hived.database_api.get_dynamic_global_properties()
            self.last_refresh = now
        return self.dgpo

def wait_for_real_time(when):
    while True:
        rtc_now = timeutil.utc_now()
        if rtc_now >= when:
            break
        time.sleep(0.4)

def broadcast_transaction(hived, tx):
    return hived.network_broadcast_api.broadcast_transaction(
        trx=tx,
        max_block_age=-1,
        )

def generate_blocks(hived, args, cached_dgpo=None, now=None, produce_realtime=False):
    if args["count"] <= 0:
        return

    miss_blocks = args.get("miss_blocks", 0)

    if not produce_realtime:
        hived.debug_node_api.debug_generate_blocks(
            debug_key="5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n",
            count=args["count"],
            skip=0,
            miss_blocks=miss_blocks,
            )
        return
    dgpo = cached_dgpo.get()
    now = dgpo["time"]

    head_block_time = datetime.datetime.strptime(dgpo["time"], "%Y-%m-%dT%H:%M:%S")
    next_time = head_block_time + datetime.timedelta(seconds=3*(1+miss_blocks))

    print("wait_for_real_time( {} )".format(next_time))
    wait_for_real_time(next_time)
    print("calling debug_generate_blocks, miss_blocks={}".format(miss_blocks))
    hived.debug_node_api.debug_generate_blocks(
           debug_key="5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n",
           count=1,
           skip=0,
           miss_blocks=miss_blocks,
           )
    print("entering loop")
    for i in range(1, args["count"]):
        next_time += datetime.timedelta(seconds=3)
        wait_for_real_time(next_time)
        hived.debug_node_api.debug_generate_blocks(
               debug_key="5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n",
               count=1,
               skip=0,
               miss_blocks=0,
               )
    return

def main(argv):

    parser = argparse.ArgumentParser(prog=argv[0], description="Submit transactions to Hive")
    parser.add_argument("-t", "--testserver", default="http://127.0.0.1:8190", dest="testserver", metavar="URL", help="Specify testnet hived server with debug enabled")
    parser.add_argument("--signer", default="sign_transaction", dest="sign_transaction_exe", metavar="FILE", help="Specify path to sign_transaction tool")
    parser.add_argument("-i", "--input-file", default="-", dest="input_file", metavar="FILE", help="File to read transactions from")
    parser.add_argument("-f", "--fail-file", default="-", dest="fail_file", metavar="FILE", help="File to write failures, - for stdout, die to quit on failure")
    parser.add_argument("-n", "--chain-name", default="", dest="chain_name", metavar="CN", help="Specify chain name")
    parser.add_argument("-c", "--chain-id", default="", dest="chain_id", metavar="CID", help="Specify chain ID")
    parser.add_argument("-tpb", "--transactions-per-block", default="40", dest="transactions_per_block", metavar="INT", help="Transactions per block (default: 40)")
    parser.add_argument("--timeout", default=5.0, type=float, dest="timeout", metavar="SECONDS", help="API timeout")
    parser.add_argument("--realtime", dest="realtime", action="store_true", help="Wait when asked to produce blocks in the future")
    cli_args = parser.parse_args(argv[1:])

    die_on_fail = False
    if cli_args.fail_file == "-":
        fail_file = sys.stdout
    elif cli_args.fail_file == "die":
        fail_file = sys.stdout
        die_on_fail = True
    else:
        fail_file = open(cli_args.fail_file, "w")

    if cli_args.input_file == "-":
        input_file = sys.stdin
    else:
        input_file = open(cli_args.input_file, "r")

    timeout = cli_args.timeout

    backend = HiveRemoteBackend(nodes=[cli_args.testserver], appbase=True, min_timeout=timeout, max_timeout=timeout)
    hived = HiveInterface(backend)
    sign_transaction_exe = cli_args.sign_transaction_exe
    produce_realtime = cli_args.realtime

    cached_dgpo = CachedDgpo(hived=hived)

    if cli_args.chain_name != "":
        chain_id = hashlib.sha256(str.encode(cli_args.chain_name.strip())).digest().hex()
    else:
        chain_id = None

    if cli_args.chain_id != "":
        chain_id = cli_args.chain_id.strip()

    transactions_per_block = int(cli_args.transactions_per_block)
    transactions_count = 0
    signer = TransactionSigner(sign_transaction_exe=sign_transaction_exe, chain_id=chain_id)
    metadata = None

    for line in input_file:
        cmd = None
        action_args = None
        try:
            line = line.strip()
            cmd, action_args = json.loads(line)
            if cmd == "metadata":
                metadata = action_args
                
                if action_args.get("post_backfill"):
                    dgpo = cached_dgpo.get()
                    now = timeutil.utc_now()
                    head_block_time = datetime.datetime.strptime(dgpo["time"], "%Y-%m-%dT%H:%M:%S")
                    join_head = int((now - head_block_time).total_seconds()) // HIVE_BLOCK_INTERVAL
                    
                    if join_head > HIVE_BLOCK_INTERVAL:
                        generate_blocks(hived, {"count": join_head}, cached_dgpo=cached_dgpo, produce_realtime=produce_realtime)
                        cached_dgpo.reset()
                else:
                    transactions_per_block = metadata.get("txgen:transactions_per_block", transactions_per_block)
                    semver = metadata.get("txgen:semver", '0.0')
                    major_version, minor_version = semver.split('.')
                    major_version = int(major_version)
                    minor_version = int(minor_version)

                    if major_version == ACTIONS_MAJOR_VERSION_SUPPORTED:
                        print("metadata:", metadata)
                    else:
                        raise RuntimeError("Unsupported actions:", metadata)
                        
                    if minor_version < ACTIONS_MINOR_VERSION_SUPPORTED:
                        print("WARNING: Older actions encountered.", file=sys.stderr)
            elif cmd == "wait_blocks":
                if metadata and action_args.get("count") == 1 and action_args.get("miss_blocks"):
                    if action_args["miss_blocks"] < metadata["recommend:miss_blocks"]:
                        action_args["miss_blocks"] = metadata["recommend:miss_blocks"]
                generate_blocks(hived, action_args, cached_dgpo=cached_dgpo, produce_realtime=produce_realtime)
                cached_dgpo.reset()
            elif cmd == "submit_transaction":
                tx = action_args["tx"]
                dgpo = cached_dgpo.get()
                tx["ref_block_num"] = dgpo["head_block_number"] & 0xFFFF
                tx["ref_block_prefix"] = struct.unpack_from("<I", unhexlify(dgpo["head_block_id"]), 4)[0]
                head_block_time = datetime.datetime.strptime(dgpo["time"], "%Y-%m-%dT%H:%M:%S")
                expiration = head_block_time+datetime.timedelta(minutes=1)
                expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S")
                tx["expiration"] = expiration_str

                wif_sigs = tx["wif_sigs"]
                del tx["wif_sigs"]

                sigs = []
                for wif in wif_sigs:
                    if not isinstance(wif_sigs, list):
                        raise RuntimeError("wif_sigs is not list")
                    result = signer.sign_transaction(tx, wif)
                    if "error" in result:
                        raise RuntimeError(
                            "could not sign transaction: {}".format(result["error"])
                        )
                    sigs.append(result["result"]["sig"])
                tx["signatures"] = sigs
                print("bcast:", json.dumps(tx, separators=(",", ":")))

                broadcast_transaction(hived, tx)
                transactions_count += 1

                if (metadata and transactions_count > 0
                        and transactions_count % transactions_per_block == 0):
                    generate_blocks(
                        hived, {"count": 1}, cached_dgpo=cached_dgpo,
                        produce_realtime=produce_realtime
                    )
                    cached_dgpo.reset()
        except Exception as e:
            failed_args = action_args if action_args is not None else {"raw": line}
            fail_file.write(json.dumps([cmd, failed_args, str(e)])+"\n")
            fail_file.flush()
            if die_on_fail:
                raise
        

if __name__ == "__main__":
    main(sys.argv)
