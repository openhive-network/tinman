import unittest
from unittest import mock

from tinman import util

from simple_hive_client.client import HiveInterface, HiveRPCException

class UtilTest(unittest.TestCase):
    def test_tag_escape_sequences(self):
        result = list(util.tag_escape_sequences('now "is" the time; "the hour" has "come"', '"'))
        expected_result = [('now ', False), ('is', True), (' the time; ', False), ('the hour', True), (' has ', False), ('come', True), ('', False)]
        self.assertEqual(result, expected_result)
    
    def test_batch(self):
        result = list(util.batch("spamspam", 3))
        expected_result = [['s', 'p', 'a'], ['m', 's', 'p'], ['a', 'm']]
        self.assertEqual(result, expected_result)

    def test_find_non_substr(self):
        self.assertEqual(util.find_non_substr('hive'), 'a')
        self.assertEqual(util.find_non_substr('hivean'), 'b')
        self.assertEqual(util.find_non_substr('hivean bob'), 'c')
        self.assertEqual(util.find_non_substr('hivean bob can'), 'd')
        # skip 'e' because 'hive' contains 'e'
        self.assertEqual(util.find_non_substr('hivean bob can do'), 'f')
        self.assertEqual(util.find_non_substr('hivean bob can do fun'), 'g')
        self.assertEqual(util.find_non_substr('hivean bob can do fun things'), 'j')

    def test_iterate_operations_from(self):
        hived = HiveInterface()
        hived.block_api = mock.Mock()
        hived.block_api.get_block.return_value = {"block": {"transactions": [{
            "operations": [{"type": "pow_operation", "value": {
                "worker_account": "alice",
            }}],
        }]}}
        result = util.iterate_operations_from(hived, True, 1102, 1103, set())
        self.assertEqual(list(result), [{
            "type": "pow_operation", "value": {"worker_account": "alice"},
        }])
        hived.block_api.get_block.assert_called_once_with(block_num=1102)

    def test_retry_hive_rpc_preserves_unrecognized_error(self):
        error = HiveRPCException({})
        with self.assertRaises(HiveRPCException) as raised:
            util.retry_hive_rpc(lambda: (_ for _ in ()).throw(error), {
                "Internal Error",
            }, 3, sleep=lambda seconds: None)
        self.assertIs(raised.exception, error)

    def test_retry_hive_rpc_retries_then_returns(self):
        call = mock.Mock(side_effect=[
            HiveRPCException({"error": {"message": "Internal Error"}}),
            "ok",
        ])
        self.assertEqual(util.retry_hive_rpc(
            call, {"Internal Error"}, 3, sleep=lambda seconds: None
        ), "ok")
        self.assertEqual(call.call_count, 2)

    def test_action_to_str(self):
        action = ["metadata", {}]
        result = util.action_to_str(action)
        self.assertEqual(result, '["metadata",{"esc":"b"}]')

    def test_action_to_str_with_esc(self):
        action = ["metadata", {"esc": "C"}]
        result = util.action_to_str(action)
        self.assertEqual(result, '["metadata",{"esc":"C"}]')
