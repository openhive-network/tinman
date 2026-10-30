# Automated contributions

This directory configures the automated development platform that contributes to this
repository. This note says which branches it uses here and how its work reaches the
project's main line.

## Branches

- `aidev/integration` — the integration branch. Automated work lands here and nowhere else.
- `develop` — the project's main line; reached from `aidev/integration` only by merge request
  (`aidev handoff`). Merge integration MRs **keeping the source branch**
  (`aidev/integration` is protected, so GitLab never deletes it).
- `ai/*` — one branch per task, created and deleted by the platform. Do not commit to them.
- `session/*` — a session's accumulated work, landed on the integration branch as a batch.

## How work reaches the main line

Task and session branches never reach `aidev/integration` through merge requests; the platform
lands them after its own verification. `aidev/integration` reaches `develop` by this project's
usual process, merge requests included — the platform never merges into any other branch.

Whether this project's CI pipelines skip `ai/*` and `session/*` branches is decided by the
project's CI rules (today `.gitlab-ci.yml` runs for every push, merge request, schedule and web pipeline, so `ai/*` and `session/*` pushes start pipelines too).

## Suites run before work lands

Declared in `.aidev/project.yaml` under `verification`, all through `.aidev/run-checks.sh`,
which writes `test-results/<slot>/junit.xml` (one case per step, plus unittest's per-test junit as `unit-junit.xml`):

- `quick`, `full`, `canary`, `system` — `unit cli package compile`
- `baseline`, `coverage` — `unit`
- `static` — `compile`

Steps mirror CI's test and package jobs (`tox.ini`): `unit` is `python -W error::DeprecationWarning -m unittest discover -s test -p "*_test.py"` (run through `.aidev/unittest_junit.py`, same discovery and verdict, plus junit), `cli` is `python -m tinman --help` and `python -m tinman server --help`, `package` is `scripts/check_artifacts.py` (tox's `package` env: build the wheel and sdist, smoke-install each in a venv; pip resolves offline from the image's wheelhouse), and `compile` is `python -m compileall` over `tinman`, `simple_hive_client`, `scripts` and `test`. The suite runs from the checkout (`PYTHONPATH` = repository root) on Python 3.12; CI also runs 3.13 and 3.14. The whole set takes about 20 seconds.

The repository has no linter, so `static` is `compile` (syntax only), and no coverage tool, so `coverage` runs the unit suite without measuring. `system` has no real services to run against and repeats the full set. One unit test, `cli_test.CliTest.test_installed_console_script_help`, skips itself outside an installed environment.

### Not run

- CI's `container` job (`docker build` of the Dockerfile and the suite inside it): needs a docker daemon.
- `hive-read-only` (manual/scheduled): talks to `https://api.hive.blog`.
- `hive-fastgen` (manual/scheduled): needs a live fastgen node and a hive testnet image.

`test-results/` is not in `.gitignore`; do not commit it.

## Test runtime

`.aidev/runtime/Dockerfile` builds on `python:3.12` (CI's package-job image), pinned by digest, installs the runtime and `server` dependencies of `pyproject.toml`, and keeps a wheelhouse (`/opt/wheels`, with `PIP_NO_INDEX`/`PIP_FIND_LINKS` set) for `check_artifacts.py`'s isolated builds. The dependency list is spelled out in the Dockerfile: when `pyproject.toml`'s dependencies change (`environment.inputs`), update it, rebuild and re-pin with `.aidev/runtime/build.sh --push`, and put the printed `repo@sha256:…` into `environment.image`.
