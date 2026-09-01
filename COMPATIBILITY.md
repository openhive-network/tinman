# Compatibility

This document defines Tinman's compatibility claims and the evidence required
to make them. A passing cell is evidence for the exact version or image tested;
it is not a promise about untested future releases.

## Status terms

- **Supported** — part of the maintained compatibility contract and required to
  pass before release.
- **Tested** — observed to pass, but not necessarily run for every commit.
- **Best effort** — expected to work, without continuous compatibility evidence.
- **Unsupported** — outside the maintained contract.

## Python and packaging matrix

| Surface | 3.12 | 3.13 | 3.14 | Evidence |
| --- | --- | --- | --- | --- |
| Core wheel install, unit tests, CLI | Supported | Supported | Supported | `tox -e py312,py313,py314` |
| `server` extra and CLI | Supported | Supported | Supported | `tox -e py312-server,py313-server,py314-server` |
| Wheel and sdist isolated install | Supported | Best effort | Best effort | `tox -e package` on Python 3.12 |

The package matrix runs on Linux in GitLab CI. Local macOS results are useful
development evidence, but Linux is the release platform contract. The Tinman
container is based on Python 3.12 and is built and smoke-tested on every commit.

## Hive compatibility matrix

| Target | Status | Profile | Evidence |
| --- | --- | --- | --- |
| Current public Hive API | Tested | Read-only | `make compat-read-only` |
| Hive testnet 1.28.7 | Tested | Fastgen | `make compat-matrix` with the pinned image below |
| Captured Hive testnet 1.29.0 image | Tested | Fastgen | `make compat-matrix` with the captured digest below |
| Unpinned `latest` images | Unsupported | — | Floating images cannot produce reproducible evidence |

The current stable test target is:

```text
registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79
```

Tin Toy's modernization working tree pins the captured linux/amd64 image that
was resolved on 2026-08-31:

```text
registry.gitlab.syncad.com/hive/hive/testnet@sha256:89be820efd988a8864c88225f6a26de92e36086af27dd8dde387d3067627fc4b
```

Both digest-pinned cells passed on linux/amd64 on 2026-09-01. Each processed 67
submissions, advanced a pristine chain from the preflight block to block 24,
and created `porter`. The 1.29.0 cell observed an active hardfork of 1.28.0 and
a median account-creation fee of 0.030 HIVE; binary version and active hardfork
are intentionally reported separately.

## RPC contract

Tinman uses direct JSON-RPC names by default and deterministically tests these
contracts on every commit:

- `database_api.list_accounts`
- `database_api.list_witnesses`
- `database_api.get_version`
- `database_api.get_config`
- `database_api.get_hardfork_properties`
- `database_api.get_witness_schedule`
- `database_api.get_dynamic_global_properties`
- `debug_node_api.debug_generate_blocks`
- `network_broadcast_api.broadcast_transaction`

The bundled client retains the older `call` envelope through
`rpc_style="legacy_call"`, but direct method names are the supported default.

## Live profiles

The read-only profile samples account and witness pagination, dynamic global
properties, node and active-hardfork versions, chain ID, address prefix,
authority membership cap, block interval, and median account-creation fee
without modifying chain state:

```bash
make compat-read-only
```

The fastgen profile is destructive and must target a fresh local testnet. It
generates actions from the small fixture, substitutes keys, submits signed
transactions, advances blocks through `debug_node_api`, and verifies the
resulting `porter` account. It refuses to run unless the Hive image is supplied
by digest. On a pristine chain it first advances chain time through the initial
hardfork boundary, leaving enough time before wall clock for the predicted
snapshot action stream, then re-reads the live profile before generating
actions. The live fee is used for every account creation and added to Porter's
funding reserve. Live genesis accounts are excluded from snapshot creation,
Porter's vesting reserve scales with snapshot size, and imported accounts
receive the configured minimum vesting needed to update their authorities.

The current 2,000-account Tin Toy sample is the scale test for those reserves.
On Calculon it imported 1,998 non-genesis accounts, activated 21 deterministic
witnesses, reached majority version 1.29.0, and sustained block production.

Run the reproducible two-image matrix on the configured remote Docker context:

```bash
make compat-matrix \
  DOCKER_CONTEXT=calculon \
  MATRIX_TINMAN_IMAGE=tinman:modernization
```

The runner uses a fresh network, container, and named utility volume for every
cell, extracts signing tools from the exact Hive image, and cleans up all three
resources on success or failure. Images must already be cached unless the
runner is invoked directly with `--pull`.

For an already-running testnet, the lower-level profile remains available:

```bash
make compat-fastgen \
  FASTGEN_RPC=http://127.0.0.1:9990 \
  HIVE_IMAGE=registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79 \
  GET_DEV_KEY=/path/to/get_dev_key \
  SIGN_TRANSACTION=/path/to/sign_transaction
```

Hive's upstream Python test harness informed the lifecycle and chain-property
checks, but it is not a Tinman dependency: the current harness requires Python
3.14 and private `hiveio-*` packages. Tinman's matrix stays self-contained and
uses the public Docker image plus JSON-RPC contracts.

GitLab runs the fast Python, packaging, RPC-contract, and Tinman-container
checks on every commit. Live Hive jobs are scheduled or manual. The destructive
job requires a runner tagged `hive-fastgen`, a fresh endpoint in
`TINMAN_FASTGEN_RPC`, the exact image in `TINMAN_HIVE_IMAGE`, and both Hive
utility binaries on `PATH`.
