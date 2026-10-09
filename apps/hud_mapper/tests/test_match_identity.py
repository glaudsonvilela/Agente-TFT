import unittest

from hm.match_identity import MatchIdentity


class MatchIdentityTests(unittest.TestCase):
    def test_new_game_needs_two_early_round_reads(self):
        identity = MatchIdentity('0123456789abcdef0123456789abcdef')
        first = identity.observe('4-5')
        self.assertEqual(identity.observe('2-1'), first)
        second = identity.observe('2-1')
        self.assertNotEqual(second, first)
        self.assertEqual(identity.observe('2-2'), second)

    def test_one_bad_stage_read_does_not_split_match(self):
        identity = MatchIdentity('0123456789abcdef0123456789abcdef')
        first = identity.observe('5-1')
        identity.observe('2-1')
        identity.observe('5-2')
        self.assertEqual(identity.observe('5-3'), first)
        self.assertEqual(identity.generation, 0)


if __name__ == '__main__':
    unittest.main()
