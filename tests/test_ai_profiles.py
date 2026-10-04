import unittest
from warno_ag.refresh_ai import battle_profile


class AIProfileTests(unittest.TestCase):
    def test_nato_opening_and_default_restoration(self):
        policy={'aggressive_until':{'nato':9}}
        self.assertEqual([battle_profile(policy,'nato',t) for t in range(1,21)],[4]*9+[0]*11)
        self.assertEqual([battle_profile(policy,'pact',t) for t in range(1,21)],[0]*20)
        self.assertEqual([battle_profile(policy,'nato',t,True) for t in range(1,21)],[0]*20)

    def test_legacy_policy_keeps_default(self):
        self.assertEqual(battle_profile({},'nato',1),0)
        self.assertEqual(battle_profile({},'pact',10),0)

    def test_independent_side_windows(self):
        policy={'aggressive_until':{'nato':9,'pact':3}}
        self.assertEqual(battle_profile(policy,'pact',3),4)
        self.assertEqual(battle_profile(policy,'pact',4),0)
        self.assertEqual(battle_profile(policy,'nato',4),4)
