#!/usr/bin/env bash
# Run the checks named after the suite and write test-results/<suite>/junit.xml.
#
#   .aidev/run-checks.sh <suite> <step>...
#
# Steps, one junit case each (unit also keeps unittest's per-test junit as
# unit-junit.xml):
#
#   unit     python -W error::DeprecationWarning -m unittest discover -s test
#            -p "*_test.py" (tox.ini's commands, CI's python/server jobs)
#   cli      python -m tinman --help and python -m tinman server --help
#            (the rest of tox.ini's py3xx / py3xx-server commands)
#   package  scripts/check_artifacts.py (tox -e package, CI's package job):
#            builds the wheel and sdist and smoke-installs each in a venv;
#            offline, pip resolves from the image's wheelhouse
#   compile  python -m compileall over the packages, scripts and tests (the
#            repository has no linter; this catches syntax errors only)
#
# Not run: CI's container job (docker build), hive-read-only (api.hive.blog)
# and hive-fastgen (a live fastgen node). See .aidev/README.md.
#
# Runs offline in the image of .aidev/runtime/Dockerfile.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
root="$PWD"
suite="${1:?usage: $0 <suite> <step>...}"; shift
out="$root/test-results/$suite"
rm -rf "$out"; mkdir -p "$out"
cases="$out/cases.tsv"; : > "$cases"
export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" PYTHONDONTWRITEBYTECODE=1

status=0
step() {
    local name="$1"; shift
    local log="$out/$name.log" t0=$SECONDS rc=0
    echo "== $name" >&2
    ( cd "$root" && "$@" ) > "$log" 2>&1 < /dev/null || rc=$?
    if [ "$rc" -eq 0 ]; then
        printf 'case\t%s\tpass\t%s\t\n' "$name" "$((SECONDS - t0))" >> "$cases"
    else
        status=1; tail -40 "$log" >&2
        printf 'case\t%s\tfail\t%s\texit %s\t%s\n' "$name" "$((SECONDS - t0))" "$rc" "$log" >> "$cases"
    fi
    return "$rc"
}

cli() {
    python -m tinman --help && python -m tinman server --help
}

for s in "$@"; do
    case "$s" in
        unit) step unit python -W error::DeprecationWarning .aidev/unittest_junit.py "$out/unit-junit.xml" test "*_test.py" ;;
        cli) step cli cli ;;
        package) step package python scripts/check_artifacts.py ;;
        compile) step compile python -m compileall -q tinman simple_hive_client scripts test ;;
        *) printf 'case\t%s\tfail\t0\tunknown step\n' "$s" >> "$cases"; status=1 ;;
    esac
done
python .aidev/junit_cases.py "$out/junit.xml" "$suite" "$cases"
exit "$status"
