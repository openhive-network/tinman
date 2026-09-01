#!/usr/bin/env python3
"""Run read-only or destructive Tinman compatibility probes against Hive."""

import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import ijson

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from simple_hive_client.client import HiveInterface, HiveRemoteBackend


DEFAULT_SNAPSHOT = PROJECT_ROOT / "test" / "test-no-main-accounts-snapshot.json"
DEFAULT_CONFIG = PROJECT_ROOT / "txgen.conf.example"
DEBUG_KEY = "5JNHfZYKGaomSFvd4NUdQ9qMcEAC43kujbfjueTHpVapX1Kzq2n"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def hive_client(endpoint, rpc_style, timeout):
    backend = HiveRemoteBackend(
        nodes=[endpoint],
        appbase=True,
        rpc_style=rpc_style,
        min_timeout=timeout,
        max_timeout=timeout,
        max_retries=0,
    )
    return HiveInterface(backend)


def read_only_probe(hive):
    version = hive.database_api.get_version()
    config = hive.database_api.get_config()
    hardfork = hive.database_api.get_hardfork_properties()
    witness_schedule = hive.database_api.get_witness_schedule()
    dgpo = hive.database_api.get_dynamic_global_properties()
    accounts = hive.database_api.list_accounts(
        start="", limit=1, order="by_name"
    )
    witnesses = hive.database_api.list_witnesses(
        start="", limit=1, order="by_name"
    )

    require(isinstance(version, dict), "database_api.get_version returned no object")
    require(isinstance(config, dict), "database_api.get_config returned no object")
    require(
        isinstance(hardfork.get("current_hardfork_version"), str),
        "hardfork properties omitted current_hardfork_version",
    )
    creation_fee = witness_schedule.get("median_props", {}).get(
        "account_creation_fee"
    )
    require(isinstance(creation_fee, dict), "witness schedule omitted account creation fee")
    require("amount" in creation_fee, "account creation fee omitted amount")
    require(
        isinstance(dgpo.get("head_block_number"), int),
        "dynamic global properties omitted head_block_number",
    )
    require(
        isinstance(dgpo.get("head_block_id"), str),
        "dynamic global properties omitted head_block_id",
    )
    require(isinstance(dgpo.get("time"), str), "dynamic global properties omitted time")
    require(isinstance(accounts.get("accounts"), list), "list_accounts shape changed")
    require(isinstance(witnesses.get("witnesses"), list), "list_witnesses shape changed")

    account = accounts["accounts"][0] if accounts["accounts"] else None
    witness = witnesses["witnesses"][0] if witnesses["witnesses"] else None
    if account is not None:
        require(isinstance(account.get("name"), str), "account shape omitted name")
    if witness is not None:
        require(isinstance(witness.get("owner"), str), "witness shape omitted owner")

    return {
        "hived_version": version,
        "chain_id": version.get("chain_id"),
        "active_hardfork": hardfork["current_hardfork_version"],
        "is_testnet": config.get("IS_TEST_NET", config.get("HIVE_IS_TEST_NET")),
        "address_prefix": config.get("HIVE_ADDRESS_PREFIX"),
        "max_authority_membership": config.get("HIVE_MAX_AUTHORITY_MEMBERSHIP"),
        "block_interval": config.get("HIVE_BLOCK_INTERVAL"),
        "account_creation_fee": creation_fee,
        "head_block_number": dgpo["head_block_number"],
        "head_block_id": dgpo["head_block_id"],
        "head_block_time": dgpo["time"],
        "sample_account": account["name"] if account else None,
        "sample_witness": witness["owner"] if witness else None,
    }


def resolve_executable(value, option):
    resolved = shutil.which(value)
    if resolved is None:
        candidate = Path(value).expanduser()
        if candidate.is_file():
            resolved = str(candidate.resolve())
    require(resolved is not None, "{} executable was not found: {}".format(option, value))
    return resolved


def run(command, *, cwd):
    print("+", " ".join(str(part) for part in command), file=sys.stderr, flush=True)
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed with status {}:\n{}\n{}".format(
                result.returncode,
                result.stdout[:4000] + result.stdout[-4000:],
                result.stderr[:4000] + result.stderr[-4000:],
            )
        )
    return result


def fastgen_chain_profile(hive, initial, lead_blocks=0):
    preflight_block_generated = initial["head_block_number"] == 0
    if preflight_block_generated:
        head_time = datetime.datetime.fromisoformat(
            initial["head_block_time"].replace("Z", "+00:00")
        )
        if head_time.tzinfo is None:
            head_time = head_time.replace(tzinfo=datetime.timezone.utc)
        target_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=lead_blocks * initial["block_interval"]
        )
        miss_blocks = max(
            int((target_time - head_time).total_seconds() / initial["block_interval"])
            - 1,
            0,
        )
        hive.debug_node_api.debug_generate_blocks(
            debug_key=DEBUG_KEY,
            count=1,
            skip=0,
            miss_blocks=miss_blocks,
        )
    return read_only_probe(hive), preflight_block_generated


def fastgen_probe(args, hive, initial):
    require(
        args.hive_image and "@sha256:" in args.hive_image,
        "fastgen runs must identify the Hive image by digest with --hive-image",
    )
    get_dev_key = resolve_executable(args.get_dev_key, "--get-dev-key")
    signer = resolve_executable(args.signer, "--signer")
    snapshot = Path(args.snapshot).resolve()
    require(snapshot.is_file(), "snapshot fixture was not found: {}".format(snapshot))
    require(initial["is_testnet"] is True, "fastgen refuses to mutate a non-testnet chain")

    config_template = json.loads(DEFAULT_CONFIG.read_text())
    with snapshot.open("rb") as snapshot_file:
        snapshot_account_count = sum(
            1 for _ in ijson.items(snapshot_file, "accounts.item")
        )
    predicted_block_count = (
        snapshot_account_count * 3 // config_template["transactions_per_block"]
        + config_template["transaction_witness_setup_pad"]
    )

    # Newer testnets apply their configured hardforks in block 1. Since that can
    # change the witness median fee, cross the boundary before generating actions.
    # Leave enough wall-clock room for txgen's generated blocks to remain valid.
    profile, preflight_block_generated = fastgen_chain_profile(
        hive, initial, lead_blocks=predicted_block_count
    )

    require(profile["chain_id"], "database_api.get_version omitted chain_id")
    require(profile["address_prefix"], "database_api.get_config omitted address prefix")
    require(
        isinstance(profile["max_authority_membership"], int),
        "database_api.get_config omitted authority membership limit",
    )
    require(
        isinstance(profile["block_interval"], int),
        "database_api.get_config omitted block interval",
    )

    before_porter = hive.database_api.find_accounts(accounts=["porter"])
    existing_accounts = hive.database_api.list_accounts(
        start="", limit=1000, order="by_name"
    ).get("accounts", [])
    with tempfile.TemporaryDirectory(prefix="tinman-fastgen-") as temporary:
        temporary_path = Path(temporary)
        config = config_template
        config["snapshot_file"] = str(snapshot)
        config["backfill_file"] = None
        config["account_creation_fee"] = profile["account_creation_fee"]
        config["hive_address_prefix"] = profile["address_prefix"]
        config["hive_max_authority_membership"] = profile["max_authority_membership"]
        config["hive_block_interval"] = profile["block_interval"]
        config["existing_account_names"] = [
            account["name"] for account in existing_accounts
        ]
        head_time = datetime.datetime.fromisoformat(
            profile["head_block_time"].replace("Z", "+00:00")
        )
        if head_time.tzinfo is None:
            head_time = head_time.replace(tzinfo=datetime.timezone.utc)
        config["hive_genesis_timestamp"] = int(
            head_time.timestamp()
            - profile["head_block_number"] * profile["block_interval"]
        )
        config_path = temporary_path / "txgen.json"
        actions_path = temporary_path / "txgen.actions"
        keyed_path = temporary_path / "keyed.actions"
        config_path.write_text(json.dumps(config))

        run([
            sys.executable,
            "-m",
            "tinman",
            "txgen",
            "--conffile",
            str(config_path),
            "--outfile",
            str(actions_path),
        ], cwd=PROJECT_ROOT)
        run([
            sys.executable,
            "-m",
            "tinman",
            "keysub",
            "--get-dev-key",
            get_dev_key,
            "--input-file",
            str(actions_path),
            "--output-file",
            str(keyed_path),
        ], cwd=PROJECT_ROOT)
        submit_command = [
            sys.executable,
            "-m",
            "tinman",
            "submit",
            "--testserver",
            args.endpoint,
            "--signer",
            signer,
            "--chain-id",
            profile["chain_id"],
            "--input-file",
            str(keyed_path),
            "--fail-file",
            "die",
            "--timeout",
            str(args.timeout),
        ]
        submit_result = run(submit_command, cwd=PROJECT_ROOT)

    final = read_only_probe(hive)
    after_porter = hive.database_api.find_accounts(accounts=["porter"])
    require(
        final["head_block_number"] > profile["head_block_number"],
        "the fastgen pipeline did not advance the head block",
    )
    require(
        after_porter.get("accounts"),
        "the fastgen pipeline did not leave the porter account on chain",
    )
    return {
        "head_block_number_before": profile["head_block_number"],
        "head_block_number_after": final["head_block_number"],
        "porter_existed_before": bool(before_porter.get("accounts")),
        "porter_exists_after": True,
        "chain_profile": {
            "active_hardfork": profile["active_hardfork"],
            "account_creation_fee": profile["account_creation_fee"],
            "address_prefix": profile["address_prefix"],
            "max_authority_membership": profile["max_authority_membership"],
            "block_interval": profile["block_interval"],
        },
        "preflight_block_generated": preflight_block_generated,
        "submit_output_lines": len(submit_result.stdout.splitlines()),
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("read-only", "fastgen"))
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("TINMAN_HIVE_RPC", "https://api.hive.blog"),
    )
    parser.add_argument(
        "--rpc-style", choices=("direct", "legacy_call"), default="direct"
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--hive-image", default=os.environ.get("TINMAN_HIVE_IMAGE"))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--get-dev-key", default=os.environ.get("GET_DEV_KEY", "get_dev_key"))
    parser.add_argument("--signer", default=os.environ.get("SIGN_TRANSACTION", "sign_transaction"))
    parser.add_argument("--report")
    return parser.parse_args()


def main():
    args = parse_args()
    hive = hive_client(args.endpoint, args.rpc_style, args.timeout)
    read_only = read_only_probe(hive)
    report = {
        "profile": args.profile,
        "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "endpoint": args.endpoint,
        "rpc_style": args.rpc_style,
        "hive_image": args.hive_image,
        "read_only": read_only,
    }
    if args.profile == "fastgen":
        report["fastgen"] = fastgen_probe(args, hive, read_only)

    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        Path(args.report).write_text(output)
    print(output, end="")


if __name__ == "__main__":
    main()
