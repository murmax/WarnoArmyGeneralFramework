"""Prepare isolated strategic LevelBuild inputs from external world YAML."""
import json
from pathlib import Path
import shutil
import tempfile

from PIL import Image

from .archives import read_directory
from .storage import sha256
from .strategic_map_source import write_blank_levelbuild_source
from .world_authoring import compile_world
from .world_scene import write_point_scene


GAME_UNITS_PER_LBU = 215
NATIVE_RENDER_CASE_SIZE = 655360


def load_scene_template(archive):
    raw = Path(archive).read_bytes()
    header, entries, _ = read_directory(raw)
    matches = [entry for entry in entries if entry.path == 'Items.sav']
    if len(matches) != 1:
        raise ValueError('Scene template archive requires exactly one root Items.sav')
    entry = matches[0]
    start = header.file_offset + entry.offset
    return raw[start:start + entry.size]


def prepare_world_source(source, destination, *, scene_template, scenery_catalog=None):
    """Emit a fresh source bundle; no baking, runtime installation or activation."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('World source destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.world-source-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'bundle'
        staged.mkdir()
        compiled, compile_report = compile_world(source, staged / 'compiled', scenery_catalog=scenery_catalog)
        cases = compiled['render_cases']
        expected_bounds = [0, 0, NATIVE_RENDER_CASE_SIZE * cases['width'],
                           NATIVE_RENDER_CASE_SIZE * cases['height']]
        if compiled['bounds'] != expected_bounds:
            raise ValueError('World bounds do not match native render-case dimensions')
        placements = [{'asset': obj['asset'], 'native_position': obj['position'] + [
            obj['ground_offset_lbu'] * GAME_UNITS_PER_LBU],
            'rotation_degrees': obj['rotation_degrees'], 'scale': obj['scale']}
            for obj in compiled['objects']]
        scene = write_point_scene(scene_template, placements)
        root = staged / 'LevelBuild' / compiled['map_name']
        write_blank_levelbuild_source(root, map_name=compiled['map_name'],
                                     render_cases_x=cases['width'], render_cases_y=cases['height'])
        for name in ('HeightMap.png', 'Div_map.webp'):
            shutil.copyfile(staged / 'compiled' / name, root / name)
        with Image.open(staged / 'compiled/Div_map.webp') as surface:
            for name, size in [('Minimap.webp', (512, 512)), ('Overview.webp', (256, 256)),
                               ('Preview.webp', (1024, 1024))]:
                surface.resize(size, Image.Resampling.LANCZOS).save(root / name, lossless=True)
        for name in ('sdb.png', 'Splat_map.png'):
            Image.new('RGB', (512, 512), (0, 0, 0)).save(root / name)
        decor_sets = ['CommonSet', compiled['scenery_catalog']['decor_set']] if placements else []
        maximum = compiled['heightmap']['max_altitude_lbu']
        (root / 'Map.ndf').write_text(
            f"MapName is '{compiled['map_name']}'\nMapJuncture is Juncture/Strategic\n"
            f'MaxAltitudeInLBU is {maximum!r}\n'
            'WaterHeightInLBU is 23.255813598632812\n'
            f'MapDecorSets is {decor_sets!r}\n'
            f"NbCaseX is {cases['width']}\nNbCaseY is {cases['height']}\n", encoding='utf-8')
        (root / 'Items.sav').write_bytes(scene)
        report = {'format': 'agf-world-source-v1', 'world_id': compiled['id'],
                  'map_name': compiled['map_name'], 'levelbuild': 'LevelBuild/' + compiled['map_name'],
                  'compiled_world_sha256': sha256((staged / 'compiled/world.compiled.json').read_bytes()),
                  'scene_schema_sha256': sha256(scene_template), 'compile_report': compile_report,
                  'game_units_per_lbu': GAME_UNITS_PER_LBU,
                  'height_policy': 'engine_ground_relative', 'native_placements': placements,
                  'surface_policy': 'external_macro_color_with_native_grass_material',
                  'source_inventory': {path.name: sha256(path.read_bytes()) for path in sorted(root.iterdir())},
                  'engine_scene_emitted': True, 'bake_verified': False,
                  'ground_adaptation_verified': False, 'runtime_verified': False}
        (staged / 'world-source.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        staged.rename(destination)
    return report
