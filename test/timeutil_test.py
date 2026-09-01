import datetime
import unittest

from tinman import timeutil


class TimeutilTest(unittest.TestCase):
    def test_utc_fromtimestamp_preserves_naive_wire_representation(self):
        result = timeutil.utc_fromtimestamp(0)
        self.assertEqual(result, datetime.datetime(1970, 1, 1))
        self.assertIsNone(result.tzinfo)

    def test_utc_now_preserves_naive_wire_representation(self):
        before = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        result = timeutil.utc_now()
        after = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        self.assertLessEqual(before, result)
        self.assertLessEqual(result, after)
        self.assertIsNone(result.tzinfo)
