import unittest
import json
from unittest import mock

from tinman import keysub

class KeysubTest(unittest.TestCase):
    def test_process_esc(self):
        self.assertRaises(AttributeError, keysub.process_esc, 'Bpublickey:owner-initminerB', 'B')
    
    def test_process_esc_ignored(self):
        result = keysub.process_esc('foo:bar', 'baz')
        expected_result = 'foo:bar'
        self.assertEqual(result, expected_result)

    def test_compute_keypair_from_seed(self):
        response = json.dumps([{
            "public_key": "TST-public",
            "private_key": "private",
        }]).encode("utf-8")
        with mock.patch.object(
                keysub.subprocess, "check_output", return_value=response) as check:
            result = keysub.compute_keypair_from_seed('1234', 'secret')

        self.assertEqual(result, ("TST-public", "private"))
        check.assert_called_once_with(["get_dev_key", "secret", "1234"])
