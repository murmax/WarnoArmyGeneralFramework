"""Bind a declared world-source recipe to a campaign's complete map resources."""
import json
from pathlib import Path
import re

from .storage import safe_child, sha256
from .world_scene_readback import read_point_lbh, verify_point_lbh
from .world_source import GAME_UNITS_PER_LBU, NATIVE_RENDER_CASE_SIZE
from .strategic_map_source import REQUIRED_TEXTURES


def validate_world_recipe(record, contract):
    if not isinstance(record, dict) or set(record) != {'format', 'source', 'world'}:
        raise ValueError('World asset recipe fields mismatch')
    if record['format'] != 'agf-world-assets-v1':
        raise ValueError('Unsupported world asset recipe')
    source, world = record['source'], record['world']
    if not isinstance(source, dict) or not isinstance(world, dict):
        raise ValueError('World asset recipe requires source and world mappings')
    if (source.get('format') != 'agf-world-source-v1' or world.get('format') != 'agf-world-compiled-v1'
            or source.get('map_name') != contract['map_name'] or world.get('map_name') != contract['map_name']
            or source.get('world_id') != world.get('id') or world.get('bounds') != contract['bounds']
            or world.get('render_cases') != contract['render_cases']):
        raise ValueError('World source identity or geometry differs from campaign map')
    inventory = source.get('source_inventory')
    required = set(REQUIRED_TEXTURES) | {'Map.ndf', 'GraphicSettings.ndf', 'Items.sav'}
    if (not isinstance(inventory, dict) or set(inventory) != required
            or any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None
                   for value in inventory.values())
            or not isinstance(world.get('generated_images'), dict)
            or set(world['generated_images']) != {'HeightMap.png', 'Div_map.webp'}
            or world.get('raster_axes') != 'columns_x_rows_y'):
        raise ValueError('World source inventory or raster contract mismatch')
    cases = contract['render_cases']
    if contract['bounds'] != [0, 0, cases['width'] * NATIVE_RENDER_CASE_SIZE,
                              cases['height'] * NATIVE_RENDER_CASE_SIZE]:
        raise ValueError('World map render-case dimensions mismatch')
    if (source.get('height_policy') != 'engine_ground_relative'
            or source.get('game_units_per_lbu') != GAME_UNITS_PER_LBU
            or source.get('surface_policy') != 'external_macro_color_with_native_grass_material'):
        raise ValueError('Unsupported world placement or surface policy')
    expected = [{'asset': obj['asset'], 'native_position': obj['position'] + [
        obj['ground_offset_lbu'] * GAME_UNITS_PER_LBU], 'rotation_degrees': obj['rotation_degrees'],
        'scale': obj['scale']} for obj in world['objects']]
    if source.get('native_placements') != expected:
        raise ValueError('World native placement recipe differs from authored objects')
    for name, expected_hash in world['generated_images'].items():
        if source['source_inventory'].get(name) != expected_hash:
            raise ValueError('World generated image differs from source inventory')
    return expected


def load_world_asset_recipe(bundle, contract):
    bundle = Path(bundle).resolve()
    source = json.loads((bundle / 'world-source.json').read_text(encoding='utf-8'))
    raw = (bundle / 'compiled/world.compiled.json').read_bytes()
    if sha256(raw) != source.get('compiled_world_sha256'):
        raise ValueError('Compiled world metadata hash mismatch')
    record = {'format': 'agf-world-assets-v1', 'source': source, 'world': json.loads(raw)}
    validate_world_recipe(record, contract)
    if source['levelbuild'] != 'LevelBuild/' + contract['map_name']:
        raise ValueError('World LevelBuild source path mismatch')
    root = safe_child(bundle, source['levelbuild'])
    if {path.name for path in root.iterdir()} != set(source['source_inventory']):
        raise ValueError('World LevelBuild source inventory mismatch')
    for name, expected_hash in source['source_inventory'].items():
        path = safe_child(root, name)
        if not path.is_file() or sha256(path.read_bytes()) != expected_hash:
            raise ValueError('World LevelBuild source hash mismatch: ' + name)
    return record


def validate_world_runtime(main, details, contract, record=None):
    if record is None:
        scene = read_point_lbh(main['Output/save.lbh'])
        if scene['points'] or scene['symbols']:
            raise ValueError('Blank strategic map contains undeclared scenery')
        return None
    placements = validate_world_recipe(record, contract)
    inventory = record['source']['source_inventory']
    if set(details) != set(inventory):
        raise ValueError('Packed world source inventory differs from declared recipe')
    for name, expected_hash in inventory.items():
        if sha256(details[name]) != expected_hash:
            raise ValueError('Packed world source hash mismatch: ' + name)
    report = verify_point_lbh(main['Output/save.lbh'], placements)
    report['source_resources_verified'] = len(inventory)
    return report
