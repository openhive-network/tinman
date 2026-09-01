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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from simple_hive_client.client import HiveInterface, HiveRemoteBackend


DEFAULT_SNAPSHOT = PROJECT_ROOT / "test" / "test-no-main-accounts-snapshot.json"
DEFAULT_CONFIG = PROJECT_ROOT / "txgen.conf.example"


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
    dgpo = hive.database_api.get_dynamic_global_properties()
    accounts = hive.database_api.list_accounts(
        start="", limit=1, order="by_name"
    )
    witnesses = hive.database_api.list_witnesses(
        start="", limit=1, order="by_name"
    )

    require(isinstance(version, dict), "database_api.get_version returned no object")
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
                result.returncode, result.stdout[-4000:], result.stderr[-4000:]
            )
        )
    return result


def fastgen_probe(args, hive, initial):
    require(
        args.hive_image and "@sha256:" in args.hive_image,
        "fastgen runs must identify the Hive image by digest with --hive-image",
    )
    get_dev_key = resolve_executable(args.get_dev_key, "--get-dev-key")
    signer = resolve_executable(args.signer, "--signer")
    snapshot = Path(args.snapshot).resolve()
    require(snapshot.is_file(), "snapshot fixture was not found: {}".format(snapshot))

    before_porter = hive.database_api.find_accounts(accounts=["porter"])
    with tempfile.TemporaryDirectory(prefix="tinman-fastgen-") as temporary:
        temporary_path = Path(temporary)
        config = json.loads(DEFAULT_CONFIG.read_text())
        config["snapshot_file"] = str(snapshot)
        config["backfill_file"] = None
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
        submit_result = run([
            sys.executable,
            "-m",
            "tinman",
            "submit",
            "--testserver",
            args.endpoint,
            "--signer",
            signer,
            "--input-file",
            str(keyed_path),
            "--fail-file",
            "die",
            "--timeout",
            str(args.timeout),
        ], cwd=PROJECT_ROOT)

    final = read_only_probe(hive)
    after_porter = hive.database_api.find_accounts(accounts=["porter"])
    require(
        final["head_block_number"] > initial["head_block_number"],
        "the fastgen pipeline did not advance the head block",
    )
    require(
        after_porter.get("accounts"),
        "the fastgen pipeline did not leave the porter account on chain",
    )
    return {
        "head_block_number_before": initial["head_block_number"],
        "head_block_number_after": final["head_block_number"],
        "porter_existed_before": bool(before_porter.get("accounts")),
        "porter_exists_after": True,
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
