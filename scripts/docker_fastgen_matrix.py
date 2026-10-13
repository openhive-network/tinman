#!/usr/bin/env python3
"""Run Tinman's destructive fastgen probe against digest-pinned Hive images."""

import argparse
import json
import subprocess
import sys
import time
import uuid


DEFAULT_HIVE_IMAGES = (
    "registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79",
    "registry.gitlab.syncad.com/hive/hive/testnet@sha256:89be820efd988a8864c88225f6a26de92e36086af27dd8dde387d3067627fc4b",
)


class Docker:
    def __init__(self, context):
        self.prefix = ["docker"]
        if context:
            self.prefix.extend(["--context", context])

    def run(self, arguments, *, check=True):
        command = self.prefix + list(arguments)
        print("+", " ".join(command), file=sys.stderr, flush=True)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if check and result.returncode != 0:
            raise RuntimeError(
                "Command failed with status {}:\n{}\n{}".format(
                    result.returncode, result.stdout[-4000:], result.stderr[-4000:]
                )
            )
        return result

    def image_exists(self, image):
        return self.run(["image", "inspect", image], check=False).returncode == 0


def require_digest(image):
    if "@sha256:" not in image:
        raise RuntimeError("Hive matrix images must be pinned by digest: {}".format(image))


def wait_for_hived(docker, tinman_image, network, endpoint, timeout):
    deadline = time.monotonic() + timeout
    last_error = "hived did not answer"
    while time.monotonic() < deadline:
        result = docker.run([
            "run", "--rm", "--network", network, "--entrypoint", "python",
            tinman_image, "scripts/hive_compatibility.py", "read-only",
            "--endpoint", endpoint, "--timeout", "2",
        ], check=False)
        if result.returncode == 0:
            return
        last_error = (result.stderr or result.stdout)[-2000:]
        time.sleep(2)
    raise RuntimeError("hived readiness timed out:\n{}".format(last_error))


def run_cell(docker, tinman_image, hive_image, readiness_timeout):
    suffix = uuid.uuid4().hex[:10]
    network = "tinman-matrix-net-{}".format(suffix)
    volume = "tinman-matrix-tools-{}".format(suffix)
    node = "tinman-matrix-hived-{}".format(suffix)
    endpoint = "http://{}:8091".format(node)
    result = {"hive_image": hive_image, "status": "failed"}

    try:
        docker.run(["network", "create", network])
        docker.run(["volume", "create", volume])
        docker.run([
            "run", "--rm", "--user", "0", "--entrypoint", "/bin/sh",
            "--mount", "source={},target=/tools".format(volume), hive_image,
            "-c", "cp /home/hived/bin/get_dev_key /home/hived/bin/sign_transaction /tools/",
        ])
        docker.run([
            "run", "-d", "--name", node, "--network", network,
            "--shm-size", "8g", hive_image,
            "--shared-file-size=8G",
            "--plugin=database_api",
            "--plugin=debug_node_api",
            "--plugin=network_broadcast_api",
            "--plugin=witness",
        ])
        wait_for_hived(docker, tinman_image, network, endpoint, readiness_timeout)
        probe = docker.run([
            "run", "--rm", "--network", network, "--entrypoint", "python",
            "--mount", "source={},target=/opt/hive,readonly".format(volume),
            tinman_image, "scripts/hive_compatibility.py", "fastgen",
            "--endpoint", endpoint,
            "--hive-image", hive_image,
            "--get-dev-key", "/opt/hive/get_dev_key",
            "--signer", "/opt/hive/sign_transaction",
        ])
        result["probe"] = json.loads(probe.stdout)
        result["status"] = "passed"
    except Exception as error:
        result["error"] = str(error)
        logs = docker.run(["logs", "--tail", "200", node], check=False)
        result["hived_logs"] = (logs.stdout + logs.stderr)[-12000:]
    finally:
        docker.run(["rm", "-f", node], check=False)
        docker.run(["network", "rm", network], check=False)
        docker.run(["volume", "rm", volume], check=False)
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", help="Docker context (defaults to the selected context)")
    parser.add_argument("--tinman-image", default="tinman:modernization")
    parser.add_argument(
        "--hive-image", action="append", dest="hive_images",
        help="digest-pinned Hive image; repeat for a matrix",
    )
    parser.add_argument("--pull", action="store_true")
    parser.add_argument("--readiness-timeout", type=float, default=90.0)
    parser.add_argument("--report")
    return parser.parse_args()


def main():
    args = parse_args()
    hive_images = tuple(args.hive_images or DEFAULT_HIVE_IMAGES)
    docker = Docker(args.context)
    if not docker.image_exists(args.tinman_image):
        raise RuntimeError("Tinman image is not available: {}".format(args.tinman_image))

    for image in hive_images:
        require_digest(image)
        if not docker.image_exists(image):
            if not args.pull:
                raise RuntimeError(
                    "Hive image is not cached (pass --pull to fetch it): {}".format(image)
                )
            docker.run(["pull", image])

    report = {
        "docker_context": args.context or "default",
        "tinman_image": args.tinman_image,
        "results": [
            run_cell(docker, args.tinman_image, image, args.readiness_timeout)
            for image in hive_images
        ],
    }
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        with open(args.report, "w") as report_file:
            report_file.write(output)
    print(output, end="")
    if any(cell["status"] != "passed" for cell in report["results"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
