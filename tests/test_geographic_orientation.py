"""Geographic landmarks must stay north-up through real raster rendering."""
from pathlib import Path
import json
import sqlite3
import struct
import tempfile
import unittest

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_bounds
from shapely.geometry import box

from warno_ag.geotiff import crop_geotiff
from warno_ag.osm_tiles import render_osm_tiles


class GeographicOrientationTests(unittest.TestCase):
    def test_surface_height_and_movement_cells_share_four_geographic_quadrants(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bounds = [33, 44, 33.4, 44.4]
            dem = root / 'dem.tif'
            # Four different geographic landmarks: NW sea, NE mountain forest,
            # SW urban plateau, SE low plain. No framework helper constructs
            # this fixture's orientation: GeoTIFF's transform is north-up.
            heights = np.full((64, 64), 50, dtype='float32')
            heights[:32, :32] = 0
            heights[:32, 32:] = 100
            heights[32:, :32] = 80
            with rasterio.open(dem, 'w', driver='GTiff', width=64, height=64,
                               count=1, dtype='float32', crs='EPSG:4326',
                               transform=from_bounds(*bounds, 64, 64)) as target:
                target.write(heights, 1)
            gpkg = root / 'source.gpkg'
            with sqlite3.connect(gpkg) as db:
                tables = ['landuse_a', 'natural_a', 'water_a', 'buildings_a',
                          'waterways', 'railways', 'roads']
                for name in tables:
                    db.execute('CREATE TABLE gis_osm_' + name + '_free (geom BLOB, fclass TEXT, name TEXT)')
                def feature(polygon, kind):
                    header = b'GP' + bytes([0, 1]) + struct.pack('<i', 4326)
                    db.execute('INSERT INTO gis_osm_landuse_a_free VALUES (?, ?, ?)',
                               (header + polygon.wkb, kind, ''))
                feature(box(33.2, 44.2, 33.4, 44.4), 'forest')
                feature(box(33, 44, 33.2, 44.2), 'residential')
            db.close()
            crop = crop_geotiff(dem, bounds, 128, root / 'height', elevation_ceiling_m=200)
            render = render_osm_tiles(gpkg, dem, bounds, root / 'surface',
                                      zoom=8, surface_size=512, render_labels=False)
            self.assertEqual(crop['raster_origin'], 'northwest')
            self.assertEqual(render['raster_origin'], 'northwest')
            cells = {(c['row'], c['column']): c['terrain'] for c in
                     json.loads((root / 'surface/strategic-grid-cells.json').read_text())}
            for row, column, expected in [(25, 25, 'StrategicWater'),
                                          (25, 75, 'StrategicForest'),
                                          (75, 25, 'StrategicUrban'),
                                          (75, 75, 'StrategicPlain')]:
                with self.subTest(row=row, column=column):
                    self.assertEqual(cells[row, column], expected)
            with Image.open(root / 'height/heightmap.png') as image:
                self.assertEqual(image.mode, 'I;16')
                for point, meters in [((32, 32), 0), ((96, 32), 100),
                                      ((32, 96), 80), ((96, 96), 50)]:
                    self.assertAlmostEqual(image.getpixel(point) / 65535 * 200, meters, delta=.01)
            with Image.open(root / 'surface/surface.png') as image:
                sea = image.getpixel((128, 128))
                plain = image.getpixel((384, 384))
                self.assertGreater(sea[2], sea[0])
                self.assertGreater(plain[0], plain[2])


if __name__ == '__main__':
    unittest.main()
