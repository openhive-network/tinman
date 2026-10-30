#!/usr/bin/env python3
"""Write a junit file from the step log of .aidev/run-checks.sh (stdlib only).

    junit_cases.py JUNIT SUITE CASES

CASES is a file of tab-separated lines the script appended as it went:
    case<TAB>NAME<TAB>pass|fail|skip<TAB>SECONDS<TAB>MESSAGE[<TAB>LOG]
Writes JUNIT as one testsuite SUITE with a case per line; a failing case's body
is the tail of LOG when given.
"""
import os
import re
import sys
from xml.sax.saxutils import escape, quoteattr


def tail(path, lines=80):
    if not path or not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return "\n".join(text.split("\n")[-lines:])


def main(junit, suite, cases_file):
    cases = []
    with open(cases_file, encoding="utf-8") as f:
        for line in f.read().split("\n"):
            kind, *fields = line.split("\t")
            if kind != "case":
                continue
            fields += [""] * (5 - len(fields))
            name, status, seconds, message, log = fields[:5]
            cases.append((name, status, float(seconds or 0), message, log))
    body = []
    for name, status, seconds, message, log in cases:
        head = "<testcase classname=%s name=%s time=\"%s\">" % (quoteattr(suite), quoteattr(name), seconds)
        if status == "fail":
            body.append("%s<failure message=%s>%s</failure></testcase>" % (head, quoteattr(message), escape(tail(log))))
        elif status == "skip":
            body.append("%s<skipped message=%s/></testcase>" % (head, quoteattr(message)))
        else:
            body.append(head + "</testcase>")
    count = lambda s: sum(1 for c in cases if c[1] == s)
    os.makedirs(os.path.dirname(junit) or ".", exist_ok=True)
    with open(junit, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<testsuite name=%s tests="%d" failures="%d" errors="0" skipped="%d" time="%s">\n'
                % (quoteattr(suite), len(cases), count("fail"), count("skip"), sum(c[2] for c in cases)))
        f.write("\n".join(body) + "\n</testsuite>\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
