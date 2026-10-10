"""GeoTIFF crop orientation and source provenance for the editor wizard."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds

from warno_ag.geotiff import crop_geotiff, inspect_geotiff
from warno_ag.storage import sha256


class GeoTiffEditorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'north-up.tif'
        samples = np.array([[100, 100, 100, 100], [75, 75, 75, 75],
                            [40, 40, 40, 40], [1, 1, 1, 1]], dtype='float32')
        with rasterio.open(self.source, 'w', driver='GTiff', width=4, height=4,
                           count=1, dtype='float32', crs='EPSG:4326',
                           transform=from_bounds(33, 44, 34, 45, 4, 4), nodata=-9999) as output:
            output.write(samples, 1)

    def test_preview_and_crop_are_north_up(self):
        before = sha256(self.source.read_bytes())
        report = inspect_geotiff(self.source, self.root / 'preview')
        self.assertEqual(report['bounds_wgs84'], [33, 44, 34, 45])
        self.assertEqual(report['preview_origin'], 'northwest')
        self.assertTrue((self.root / 'preview/preview.png').is_file())
        result = crop_geotiff(self.source, [33, 44, 34, 45], 128,
                              self.root / 'crop', elevation_ceiling_m=200)
        self.assertEqual(result['raster_origin'], 'northwest')
        with Image.open(self.root / 'crop/heightmap.png') as image:
            self.assertEqual(image.mode, 'I;16')
            self.assertGreater(image.getpixel((64, 4)), image.getpixel((64, 123)))
        self.assertEqual(sha256(self.source.read_bytes()), before)

    def test_outside_crop_and_missing_crs_fail_without_output(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            crop_geotiff(self.source, [32, 44, 34, 45], 128, self.root / 'outside')
        self.assertFalse((self.root / 'outside').exists())
        without_crs = self.root / 'no-crs.tif'
        with rasterio.open(without_crs, 'w', driver='GTiff', width=4, height=4,
                           count=1, dtype='float32', transform=from_bounds(0, 0, 1, 1, 4, 4)) as output:
            output.write(np.ones((4, 4), dtype='float32'), 1)
        with self.assertRaisesRegex(ValueError, 'CRS'):
            inspect_geotiff(without_crs, self.root / 'invalid')
        self.assertFalse((self.root / 'invalid').exists())
