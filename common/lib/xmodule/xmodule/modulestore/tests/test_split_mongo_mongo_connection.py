""" Test the behavior of split_mongo/MongoConnection """
import unittest
from mock import patch
from xmodule.modulestore.split_mongo.mongo_connection import MongoConnection
from xmodule.exceptions import HeartbeatFailure


class TestHeartbeatFailureException(unittest.TestCase):
    """ Test that a heartbeat failure is thrown at the appropriate times """
    shard = 2

    @patch('pymongo.MongoClient')
    @patch('pymongo.database.Database')
    def test_heartbeat_raises_exception_when_connection_alive_is_false(self, *calls):
        # pylint: disable=W0613
        with patch('mongodb_proxy.MongoProxy') as mock_proxy:
            mock_proxy.return_value.alive.return_value = False
            useless_conn = MongoConnection('useless', 'useless', 'useless')

            with self.assertRaises(HeartbeatFailure):
                useless_conn.heartbeat()
