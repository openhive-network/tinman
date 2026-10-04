#!/usr/bin/env python3

import datetime


def utc_now():
    """Return the current UTC time in Tinman's historical naive representation."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_fromtimestamp(timestamp):
    """Convert a POSIX timestamp to Tinman's historical naive UTC representation."""
    return datetime.datetime.fromtimestamp(timestamp, datetime.UTC).replace(tzinfo=None)
