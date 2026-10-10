"""Bounded on-demand geographic import and checked source cache."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box, mapping

from warno_ag.geodata_download import _bounds, _download, _geofabrik_region
from warno_ag.geodata_import import import_geographic_map


class _Response:
    status_code = 200
    url = 'https://example.org/extract.gpkg.zip'
    headers = {'Content-Length': '6'}

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def raise_for_status(self): pass
    def iter_content(self, _): yield b'OSMDEM'


class _Session:
    def __init__(self): self.calls = 0
    def get(self, *_args, **_kwargs):
        self.calls += 1
        return _Response()


class GeodataImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_bounds_reject_large_or_misordered_requests(self):
        self.assertEqual(_bounds([32, 44, 34, 45]), (32, 44, 34, 45))
        for value in ([34, 44, 32, 45], [32, 44, 36, 45],
                      [32, 44, 34, float('nan')]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _bounds(value)

    def test_compact_extract_wins_when_coverage_is_nearly_equal(self):
        features = []
        for identifier, polygon in [('country', box(30, 40, 40, 50)),
                                    ('regional', box(32.4, 44.2, 34.2, 45.6))]:
            features.append({'geometry': mapping(polygon), 'properties': {
                'id': identifier, 'urls': {'shp':
                    f'https://example.org/{identifier}-latest-free.shp.zip'}}})
        region, url = _geofabrik_region({'features': features},
                                       (32.45, 44.28, 34.15, 45.55))
        self.assertEqual(region, 'regional')
        self.assertTrue(url.endswith('regional-latest-free.gpkg.zip'))

    def test_cache_is_reused_only_when_receipt_matches_bytes_and_url(self):
        session = _Session()
        target = self.root / 'extract.zip'
        url = 'https://example.org/extract.gpkg.zip'
        record = _download(session, url, target, 100)
        self.assertEqual(record['sha256'], hashlib.sha256(b'OSMDEM').hexdigest())
        self.assertEqual(_download(session, url, target, 100), record)
        self.assertEqual(session.calls, 1)
        target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            _download(session, url, target, 100)

    def test_pipeline_reports_aligned_outputs_and_keeps_source_receipts(self):
        def downloaded(bounds, destination, _cache, **_):
            destination.mkdir()
            (destination / ('dem-source.tif' if destination.name == 'dem' else 'source.gpkg')).write_bytes(b'raw')
            return {'requested_bounds_wgs84': list(bounds)}

        def output_report(destination, name, report, assets):
            destination.mkdir()
            for filename in assets:
                (destination / filename).write_bytes(b'asset')
            (destination / name).write_text(json.dumps(report), encoding='utf-8')
            return report

        def cropped(_source, bounds, _resolution, destination, **_):
            return output_report(destination, 'crop.json',
                                 {'source': 'staging', 'source_sha256': 'a' * 64,
                                  'raster_origin': 'northwest'},
                                 ['heightmap.png'])

        def inspected(_source, destination):
            return output_report(destination, 'geotiff.json', {'source': 'staging'},
                                 ['preview.png'])

        def rendered(_gpkg, _dem, _bounds, destination, **_):
            return output_report(destination, 'osm-tiles.json',
                                 {'source': 'staging', 'dem': 'staging', 'tile_count': 1,
                                  'raster_origin': 'northwest'},
                                 ['surface.png', 'strategic-grid-cells.json'])

        with patch('warno_ag.geodata_import.download_copernicus_dem', downloaded), \
             patch('warno_ag.geodata_import.download_osm_geopackage', downloaded), \
             patch('warno_ag.geodata_import.crop_geotiff', cropped), \
             patch('warno_ag.geodata_import.inspect_geotiff', inspected), \
             patch('warno_ag.geodata_import.render_osm_tiles', rendered):
            updates = []
            report = import_geographic_map((32, 44, 34, 45), self.root / 'result',
                                           self.root / 'cache', progress=lambda *p: updates.append(p))
        destination = self.root / 'result'
        self.assertEqual(report['surface'], 'surface/surface.png')
        self.assertEqual(report['raster_origin'], 'northwest')
        self.assertEqual(report['render']['source'], '../osm/source.gpkg')
        self.assertEqual(report['render']['dem'], '../dem/dem-source.tif')
        self.assertEqual(json.loads((destination / 'heightmap/crop.json').read_text())['source'],
                         '../dem/dem-source.tif')
        self.assertEqual(updates[-1][0], 100)
        self.assertTrue((destination / 'geodata.json').is_file())
        with self.assertRaises(FileExistsError):
            import_geographic_map((32, 44, 34, 45), destination, self.root / 'cache')


if __name__ == '__main__':
    unittest.main()
