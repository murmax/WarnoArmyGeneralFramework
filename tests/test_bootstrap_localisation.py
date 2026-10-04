"""Fixture-free bootstrap contract for the public source repository."""

from pathlib import Path
import tempfile
import unittest

from scripts.bootstrap_authored_localisation import bootstrap
from warno_ag.current_campaign import _dictionary_keys, _early_maps_keys


ROOT = Path(__file__).resolve().parents[1]


class BootstrapLocalisationTests(unittest.TestCase):
    def test_source_recipe_builds_local_compatibility_dictionaries(self):
        artifacts = ROOT / 'artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='agf-bootstrap-', dir=artifacts) as folder:
            destination = Path(folder) / 'corpus'
            report = bootstrap(destination)
            generated = destination / 'Gen/Localisation/Localisation'
            self.assertEqual(report['files'], 26)
            self.assertEqual(len(_dictionary_keys(generated)), 187)
            self.assertEqual(len(_early_maps_keys(generated)), 38)
            with self.assertRaises(FileExistsError):
                bootstrap(destination)


if __name__ == '__main__':
    unittest.main()
