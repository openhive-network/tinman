#!/usr/bin/env python3
"""Run `unittest discover` exactly as CI does and also write a junit report.

    unittest_junit.py JUNIT START_DIR PATTERN

Same discovery and same pass/fail as `python -m unittest discover -s START_DIR
-p PATTERN` (warnings filters come from the interpreter's -W options); the
junit file has one case per test method. Stdlib only.
"""
import os
import sys
import time
import traceback
import unittest
from xml.sax.saxutils import escape, quoteattr


class JunitResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self._started = {}

    def startTest(self, test):
        self._started[test.id()] = time.monotonic()
        super().startTest(test)

    def _record(self, test, kind, detail=""):
        elapsed = time.monotonic() - self._started.get(test.id(), time.monotonic())
        self.records.append((test.id(), kind, detail, elapsed))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failure", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._record(test, "pass")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._record(test, "failure", "unexpected success")


def write_junit(path, records):
    body = []
    for test_id, kind, detail, elapsed in records:
        classname, _, name = test_id.rpartition(".")
        head = "<testcase classname=%s name=%s time=\"%.3f\">" % (quoteattr(classname), quoteattr(name), elapsed)
        first = (detail.strip().splitlines() or [""])[-1][:300]
        if kind in ("failure", "error"):
            body.append("%s<%s message=%s>%s</%s></testcase>" % (head, kind, quoteattr(first), escape(detail), kind))
        elif kind == "skipped":
            body.append("%s<skipped message=%s/></testcase>" % (head, quoteattr(detail)))
        else:
            body.append(head + "</testcase>")
    n = lambda k: sum(1 for r in records if r[1] == k)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<testsuite name="unittest" tests="%d" failures="%d" errors="%d" skipped="%d" time="%.3f">\n'
                % (len(records), n("failure"), n("error"), n("skipped"), sum(r[3] for r in records)))
        f.write("\n".join(body) + "\n</testsuite>\n")


def main(junit, start_dir, pattern):
    try:
        suite = unittest.defaultTestLoader.discover(start_dir, pattern=pattern)
    except Exception:
        traceback.print_exc()
        write_junit(junit, [("unittest.discover", "error", traceback.format_exc(), 0.0)])
        return 1
    runner = unittest.TextTestRunner(resultclass=JunitResult, verbosity=2)
    result = runner.run(suite)
    records = list(result.records)
    # Import failures surface as _FailedTest errors and are already recorded.
    write_junit(junit, records)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
