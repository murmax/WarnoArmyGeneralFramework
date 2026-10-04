import unittest
from unittest.mock import patch
from warno_ag.ai_distances import mission_radii


class AIDistanceTests(unittest.TestCase):
    def test_native_cells_are_distinct_from_legacy_gru(self):
        units={'native_cell_gru':176.67844572732616}
        c={'adapter':{'ai_distance_units':units},'campaign':{'ai_policy':{
            'attack_radius':2120,'attack_radius_cells':1.5,'transit_radius_cells':0.5,
            'support_radius_cells':0.5,'waypoint_radius_cells':0.8,'transit_waypoints':['inland']}},'map':{'flags':[{'id':'balaklava'}]}}
        with patch('warno_ag.ai_distances.compile_distance_units',return_value=units):
            self.assertEqual(mission_radii(c,defensive=False,target='balaklava',final_target='city'),(265,141))
            self.assertEqual(mission_radii(c,defensive=False,target='inland',final_target='city'),(88,141))
            self.assertEqual(mission_radii(c,defensive=False,target='bakh',final_target='bakh'),(265,141))
            self.assertEqual(mission_radii(c,defensive=True,target='rear',final_target='rear',support=True),(88,141))
            self.assertEqual(mission_radii(c,defensive=True,target='guard',final_target='guard'),(265,141))
            self.assertEqual(mission_radii(c,defensive=False,target='crossroads',final_target='city'),(265,141))

    def test_legacy_campaigns_keep_old_descriptor_values(self):
        c={'campaign':{'ai_policy':{'attack_radius':2120}}}
        self.assertEqual(mission_radii(c,defensive=False,target='road',final_target='city'),(2120,707))

    def test_conversion_provenance_cannot_silently_change(self):
        c={'adapter':{'ai_distance_units':{'native_cell_gru':706}},'campaign':{'ai_policy':{'attack_radius_cells':1}}}
        with patch('warno_ag.ai_distances.compile_distance_units',return_value={'native_cell_gru':176}):
            with self.assertRaisesRegex(ValueError,'provenance'):
                mission_radii(c,defensive=False,target='city',final_target='city')
