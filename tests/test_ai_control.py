import unittest
from warno_ag.ai_control import native_controlled


class AIControlTests(unittest.TestCase):
    def test_stock_control_and_specific_exception(self):
        c={'campaign':{'ai_policy':{'native_controller_sides':['nato'],'scripted_exceptions':['flank']}}}
        self.assertTrue(native_controlled(c,'nato',['main']))
        self.assertFalse(native_controlled(c,'nato',['flank']))
        self.assertFalse(native_controlled(c,'pact',['guard']))
        self.assertFalse(native_controlled(c,'nato',['main','flank']))

    def test_legacy_campaign_remains_scripted(self):
        self.assertFalse(native_controlled({'campaign':{}},'nato',['main']))
