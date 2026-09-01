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
| Hive testnet 1.28.7 | Pending | Fastgen | `make compat-fastgen` with the pinned image below |
| Tin Toy's current `testnet:latest` image | Pending | Fastgen | Run against the captured digest below |
| Unpinned `latest` images | Unsupported | — | Floating images cannot produce reproducible evidence |

The current stable test target is:

```text
registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79
```

Tin Toy currently names `registry.gitlab.syncad.com/hive/hive/testnet:latest`.
On 2026-08-31 its linux/amd64 manifest resolved to:

```text
registry.gitlab.syncad.com/hive/hive/testnet@sha256:89be820efd988a8864c88225f6a26de92e36086af27dd8dde387d3067627fc4b
```

The digest is reconnaissance, not yet a passing compatibility result. A
fastgen report records both the digest-qualified image supplied by the operator
and `database_api.get_version` returned by its endpoint.

## RPC contract

Tinman uses direct JSON-RPC names by default and deterministically tests these
contracts on every commit:

- `database_api.list_accounts`
- `database_api.list_witnesses`
- `database_api.get_dynamic_global_properties`
- `debug_node_api.debug_generate_blocks`
- `network_broadcast_api.broadcast_transaction`

The bundled client retains the older `call` envelope through
`rpc_style="legacy_call"`, but direct method names are the supported default.

## Live profiles

The read-only profile samples account and witness pagination, dynamic global
properties, and the node version without modifying chain state:

```bash
make compat-read-only
```

The fastgen profile is destructive and must target a fresh local testnet. It
generates actions from the small fixture, substitutes keys, submits signed
transactions, advances blocks through `debug_node_api`, and verifies the
resulting `porter` account. It refuses to run unless the Hive image is supplied
by digest:

```bash
make compat-fastgen \
  FASTGEN_RPC=http://127.0.0.1:9990 \
  HIVE_IMAGE=registry.gitlab.syncad.com/hive/hive/testnet:1.28.7@sha256:4b5720852668ab9cbdd41e2f16543c3ccd30fb3fc217174d312f38ff86867c79 \
  GET_DEV_KEY=/path/to/get_dev_key \
  SIGN_TRANSACTION=/path/to/sign_transaction
```

GitLab runs the fast Python, packaging, RPC-contract, and Tinman-container
checks on every commit. Live Hive jobs are scheduled or manual. The destructive
job requires a runner tagged `hive-fastgen`, a fresh endpoint in
`TINMAN_FASTGEN_RPC`, the exact image in `TINMAN_HIVE_IMAGE`, and both Hive
utility binaries on `PATH`.
