import copy
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
import yaml

from warno_ag.stock_scenery import load_stock_scenery, scenery_catalog_from_graph
from warno_ag.world_authoring import compile_world, sample_height_lbu


STOCK = Path(r'C:/Program Files (x86)/Steam/steamapps/common/WARNO/Data/PC/201602/DecorsSets/Steelman_Definition.dat')


def catalog_graph():
    return {'objects': [{'id': 0, 'class': 'TSceneryDescriptorMultiState', 'is_top_object': True,
                         'properties': [{'property_name': 'RegistrationName',
                                         'value': {'value': 'House_Stock'}}]}]}


class StockSceneryTests(unittest.TestCase):
    def test_catalog_includes_only_registered_top_level_point_objects(self):
        graph = catalog_graph()
        for name, top in [('TSceneryDescriptorFX', True), ('TSceneryDescriptorModel3D', False)]:
            obj = copy.deepcopy(graph['objects'][0])
            obj.update(id=len(graph['objects']), is_top_object=top)
            obj['class'] = name
            graph['objects'].append(obj)
        catalog = scenery_catalog_from_graph(graph, 'Steelman', 'a' * 64)
        self.assertEqual(set(catalog['registrations']), {'House_Stock'})
        self.assertEqual(catalog['archive_sha256'], 'a' * 64)

    def test_duplicate_registration_and_missing_fingerprint_are_rejected(self):
        graph = catalog_graph()
        graph['objects'].append(copy.deepcopy(graph['objects'][0]))
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            scenery_catalog_from_graph(graph, 'Steelman', 'a' * 64)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            scenery_catalog_from_graph(catalog_graph(), 'Steelman', '')

    @unittest.skipUnless(STOCK.is_file(), 'Installed strategic scenery catalog required')
    def test_native_steelman_has_strategic_houses_and_trees(self):
        catalog = load_stock_scenery(STOCK)
        for name in ('Habitation_German_01_A_Steelman', 'Steelman_Hornbeam_Group_01',
                     'Steelman_Douglas_01'):
            self.assertIn(name, catalog['registrations'])
        self.assertNotIn('Bezier_SM_River', catalog['registrations'])


class WorldAuthoringTests(unittest.TestCase):
    def test_georeference_records_new_north_up_and_preserves_legacy_south_up(self):
        for origin in ('northwest', 'southwest'):
            with self.subTest(origin=origin):
                self.document['georeference'] = {
                    'crs': 'EPSG:4326', 'bounds_wgs84': [33, 44, 34, 45],
                    'elevation_ceiling_m': 1200, 'source_sha256': 'a' * 64,
                    'raster_origin': origin,
                }
                compiled, _ = self.compile()
                self.assertEqual(compiled['georeference']['raster_origin'], origin)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'world.yaml'
        self.catalog = scenery_catalog_from_graph(catalog_graph(), 'Steelman', 'a' * 64)
        image = Image.new('RGB', (9, 7), (80, 100, 60))
        image.putpixel((0, 0), (200, 10, 25))
        image.putpixel((8, 6), (30, 50, 200))
        image.save(self.root / 'manual.png')
        self.document = {
            'schema': 'agf-world/v1', 'id': 'relief_probe', 'map_name': 'AGFReliefProbe',
            'bounds': [0, 0, 1310720, 1310720], 'render_cases': {'width': 2, 'height': 2},
            'raster_axes': 'columns_x_rows_y',
            'heightmap': {'samples': [[0, 0, 0], [0, 1, 0], [0, 0, 0]],
                          'resolution': [5, 5], 'max_altitude_lbu': 2.0},
            'surface': {'file': 'manual.png'},
            'objects': [{'id': 'house', 'asset': 'House_Stock', 'position': [655360, 655360],
                         'rotation_degrees': 90, 'scale': 1.0, 'ground_offset_lbu': 0.125}],
        }

    def compile(self, destination=None):
        self.source.write_text(yaml.safe_dump(self.document), encoding='utf-8')
        return compile_world(self.source, destination, scenery_catalog=self.catalog)

    def test_inline_heightmap_and_external_surface_roundtrip(self):
        destination = self.root / 'compiled'
        compiled, report = self.compile(destination)
        self.assertEqual(json.loads((destination / 'world.compiled.json').read_text(encoding='utf-8')), compiled)
        with Image.open(destination / 'HeightMap.png') as image:
            self.assertEqual(image.mode, 'I;16')
            self.assertEqual(image.getpixel((2, 2)), 65535)
            self.assertEqual(image.getpixel((0, 0)), 0)
            self.assertEqual(image.getpixel((1, 2)), 32768)
        with Image.open(destination / 'Div_map.webp') as image, Image.open(self.root / 'manual.png') as original:
            self.assertEqual(image.tobytes(), original.tobytes())
        self.assertEqual(report['heightmap_size'], [5, 5])
        self.assertEqual(report['surface_size'], [9, 7])
        self.assertEqual(compiled['objects'][0]['sampled_ground_lbu'], 2.0)
        self.assertEqual(compiled['objects'][0]['placement_height_lbu'], 2.125)
        self.assertFalse(report['runtime_verified'])
        self.assertFalse(report['engine_scene_emitted'])

    def test_determinism_and_surface_change_are_visible(self):
        first, report = self.compile()
        self.assertEqual((first, report), self.compile())
        Image.new('RGB', (9, 7), (10, 20, 30)).save(self.root / 'manual.png')
        second, _ = self.compile()
        self.assertNotEqual(first['surface']['sha256'], second['surface']['sha256'])
        self.assertNotEqual(first['generated_images']['Div_map.webp'], second['generated_images']['Div_map.webp'])
        self.assertEqual(first['generated_images']['HeightMap.png'], second['generated_images']['HeightMap.png'])

    def test_external_heightmap_is_not_downgraded_to_eight_bits(self):
        image = Image.frombytes('I;16', (2, 2), b'\x00\x00\xff\xff\x00\x00\xff\xff')
        image.save(self.root / 'height.png')
        self.document['heightmap'] = {'file': 'height.png', 'max_altitude_lbu': 4.0}
        compiled, _ = self.compile(self.root / 'compiled')
        self.assertEqual(compiled['heightmap']['input']['mode'], 'I;16')
        self.assertEqual(compiled['objects'][0]['sampled_ground_lbu'], 2.0)

    def test_image_axes_corners_and_ground_sampling_are_explicit(self):
        image = Image.frombytes('I;16', (2, 2), b'\x00\x00\xff\xff\x00\x00\xff\xff')
        for position, expected in [([0, 0], 0), ([100, 0], 2), ([0, 200], 0),
                                   ([100, 200], 2), ([50, 100], 1)]:
            self.assertEqual(sample_height_lbu(image, [0, 0, 100, 200], position, 2), expected)
        with self.assertRaisesRegex(ValueError, 'outside'):
            sample_height_lbu(image, [0, 0, 100, 200], [101, 0], 2)

    def test_invalid_height_data_and_render_cases_fail_closed(self):
        original = copy.deepcopy(self.document)
        mutations = [
            ('samples', [[0, 0], [0]]), ('samples', [[0, True], [0, 0]]),
            ('samples', [[0, float('nan')], [0, 0]]), ('samples', [[0, 1.1], [0, 0]]),
            ('resolution', [True, 5]), ('max_altitude_lbu', 0), ('max_altitude_lbu', float('inf')),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self.document = copy.deepcopy(original)
                self.document['heightmap'][field] = value
                with self.assertRaises(ValueError):
                    self.compile()
        self.document = copy.deepcopy(original)
        self.document['render_cases']['width'] = True
        with self.assertRaises(ValueError):
            self.compile()

    def test_unknown_duplicate_or_out_of_bounds_objects_are_rejected(self):
        original = copy.deepcopy(self.document)
        for field, value in [('asset', 'Unregistered'), ('position', [0, -1]),
                             ('position', [float('nan'), 0]), ('scale', 0),
                             ('rotation_degrees', float('inf')), ('ground_offset_lbu', True)]:
            with self.subTest(field=field):
                self.document = copy.deepcopy(original)
                self.document['objects'][0][field] = value
                with self.assertRaises(ValueError):
                    self.compile()
        self.document = copy.deepcopy(original)
        self.document['objects'].append(copy.deepcopy(self.document['objects'][0]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            self.compile()

    def test_path_escape_bad_formats_and_implicit_alpha_loss_are_rejected(self):
        for relative in ('../manual.png', str(self.root / 'manual.png'), 'nested/../manual.png',
                         './manual.png', 'nested\\manual.png'):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                self.document['surface']['file'] = relative
                self.compile()
        self.document['surface']['file'] = 'manual.png'
        Image.new('RGBA', (9, 7)).save(self.root / 'manual.png')
        with self.assertRaisesRegex(ValueError, 'opaque RGB'):
            self.compile()
        Image.new('RGB', (9, 7)).save(self.root / 'manual.png')
        Image.new('L', (2, 2)).save(self.root / 'height.png')
        self.document['heightmap'] = {'file': 'height.png', 'max_altitude_lbu': 2}
        with self.assertRaisesRegex(ValueError, '16-bit'):
            self.compile()

    def test_existing_outputs_and_duplicate_yaml_keys_are_rejected(self):
        destination = self.root / 'compiled'
        self.compile(destination)
        with self.assertRaises(FileExistsError):
            self.compile(destination)
        self.source.write_text('schema: agf-world/v1\nschema: agf-world/v1\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Duplicate YAML key'):
            compile_world(self.source)

    def test_objects_require_catalog_but_empty_scene_does_not(self):
        self.compile()
        with self.assertRaisesRegex(ValueError, 'inspected stock'):
            compile_world(self.source)
        self.document['objects'] = []
        self.compile()
        compiled, _ = compile_world(self.source)
        self.assertEqual(compiled['objects'], [])
