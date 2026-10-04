import os
import tempfile
import unittest
from unittest.mock import patch
from hm.player_profile import load,save

class PlayerProfileTests(unittest.TestCase):
    def test_no_login_and_no_invented_history(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,LOCALAPPDATA=temp):
            self.assertIsNone(load())
            first=save('Jogador#BR1','BR')
            self.assertFalse(first['identity_verified'])
            self.assertFalse(first['external_history_connected'])
            self.assertEqual(save('Jogador#BR1','BR')['profile_id'],first['profile_id'])
            self.assertNotEqual(save('Outra conta#123','BR')['profile_id'],first['profile_id'])
            with self.assertRaises(ValueError):save('Jogador','invalid')
