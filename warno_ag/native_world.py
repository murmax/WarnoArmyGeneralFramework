"""Preserve stock world source while rebuilding edits under a private map identity."""
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from PIL import Image

from .archives import read_directory, pack_v3
from .cndf import decode
from .deployment import default_mod_parent
from .native_graph import NativeGraphEditor
from .storage import safe_child, sha256
from .strategic_grid_binary import read_grid, write_grid
from .tgv import read_texture


def _scene(raw, compiled):
    before = {row['id']: row for row in compiled['baseline']['world']['sceneObjects']}
    after = {row['id']: row for row in compiled['state']['world']['sceneObjects']}
    if before == after:
        return raw
    editor = NativeGraphEditor(raw)
    bindings = {row['id']: row['objectId'] for row in compiled['entity_bindings'] if row['kind'] == 'scenery'}
    root = next(obj for obj in editor.objects if obj['class'] == 'TSaveDescriptorItemList' and obj['is_top_object'])
    items = editor.property(root, 'Items')['value']['items']
    root_ids = {value.get('object_id') for value in items}
    prototype = next(obj for obj in editor.objects if obj['class'] == 'TSaveDescriptorItemPoint')
    removed = {bindings[identifier] for identifier in set(before) - set(after)}
    if not removed <= root_ids:
        raise ValueError('Pattern-local scenery must be edited through its map instance')
    items = [value for value in items if value.get('object_id') not in removed]
    for identifier, current in after.items():
        previous = before.get(identifier)
        if current == previous:
            continue
        if previous is None:
            obj_id, _ = editor.clone(prototype['id'])
            obj = editor.objects[obj_id]
            items.append(editor.reference(obj_id))
        else:
            if bindings[identifier] not in root_ids:
                raise ValueError('Pattern-local scenery must be edited through its map instance')
            obj = editor.objects[bindings[identifier]]
        position = current['position']
        editor.set_scalar(obj, 'AxeT', [position['x'], position['y'], current['groundOffsetLbu'] * 215])
        if previous is None or any(current[key] != previous[key] for key in ('scale', 'rotationDegrees')):
            scale = current['scale']
            angle = math.radians(current['rotationDegrees'])
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError('Invalid native scene scale')
            c, s = math.cos(angle) * scale, math.sin(angle) * scale
            editor.set_scalar(obj, 'AxeX', [c, s, 0.0])
            editor.set_scalar(obj, 'AxeY', [-s, c, 0.0])
            editor.set_scalar(obj, 'AxeZ', [0.0, 0.0, scale])
        if previous is None or current['asset'] != previous['asset']:
            editor.set_scalar(obj, 'SceneryDescriptor', current['asset'])
    editor.set_value(root, 'Items', editor.sequence(items))
    return editor.save()


def native_world_digest(compiled):
    root = Path(compiled['source_root']); state = compiled['state']; terrain = state['world']['terrain']
    return sha256(json.dumps({'project': state['id'], 'world': state['world'], 'grid': state['grid'],
                              'height': sha256(safe_child(root, terrain['heightmapPath']).read_bytes()),
                              'surface': sha256(safe_child(root, terrain['surfacePath']).read_bytes())},
                             sort_keys=True, separators=(',', ':')).encode())


def resolve_native_world(compiled, prepared=None):
    digest = native_world_digest(compiled)
    root = Path(prepared).resolve() if prepared else Path(__file__).resolve().parents[1] / 'artifacts/native-world-builds' / digest[:16]
    report_path = root / 'native-world-build.json'
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report['source_digest'] != digest:
            raise ValueError('Prepared native world belongs to different editor inputs')
        payload = Path(report['payload'])
        if {path.relative_to(payload).as_posix(): sha256(path.read_bytes()) for path in payload.rglob('*') if path.is_file()} != report['files']:
            raise ValueError('Prepared native world files changed')
        verify_native_world_payload(payload, report)
        return report
    if root.exists():
        raise ValueError('Native world build is incomplete; inspect its running process evidence before resuming: ' + str(root))
    return build_native_world(compiled, root)


def prepare_native_world(compiled, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    snapshot = Path(compiled['snapshot'])
    manifest = json.loads((snapshot / 'native-source.json').read_text(encoding='utf-8'))
    projection = json.loads((snapshot / manifest['projection_file']).read_text(encoding='utf-8'))
    source_root = Path(compiled['source_root'])
    state = compiled['state']
    terrain = state['world']['terrain']
    height_path = safe_child(source_root, terrain['heightmapPath'])
    surface_path = safe_child(source_root, terrain['surfacePath'])
    digest = native_world_digest(compiled)
    map_name = 'AGFNativeMap_' + digest[:16]
    old_name = projection['map']['name']
    root = destination / 'LevelBuild' / map_name
    root.mkdir(parents=True)
    for entry in manifest['resources']:
        if entry['scope'] != 'map_details':
            continue
        raw = safe_child(snapshot, entry['file']).read_bytes()
        if sha256(raw) != entry['sha256']:
            raise ValueError('Captured native world source changed')
        target = safe_child(root, entry['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    shutil.copyfile(height_path, root / 'HeightMap.png')
    with Image.open(surface_path) as image:
        if image.convert('RGBA').getchannel('A').getextrema() != (255, 255):
            raise ValueError('Native map surface must be opaque')
        image.convert('RGB').save(root / 'Div_map.webp', lossless=True)
    map_source = (root / 'Map.ndf').read_text(encoding='utf-8-sig')
    map_source, count = re.subn(r"(?m)^(\s*MapName\s+is\s*)'[^']*'", lambda match: match[1] + "'" + map_name + "'", map_source)
    if count != 1:
        raise ValueError('Native map source identity is ambiguous')
    altitude = terrain['maxAltitudeLbu']
    if type(altitude) not in (int, float) or not 0 < altitude * 215 < 5000:
        raise ValueError('Native height ceiling must remain below the strategic overlay')
    map_source, count = re.subn(r'(?m)^(\s*MaxAltitudeInLBU\s+is\s*)[-+0-9.eE]+', lambda match: match[1] + repr(altitude), map_source)
    if count != 1:
        raise ValueError('Native map altitude source is ambiguous')
    (root / 'Map.ndf').write_text(map_source, encoding='utf-8')
    (root / 'Items.sav').write_bytes(_scene((root / 'Items.sav').read_bytes(), compiled))
    before_bounds = compiled['baseline']['world']['nativeField']['bounds']
    if state['world']['nativeField']['bounds'] != before_bounds:
        raise ValueError('Native map resizing requires an explicit render-case conversion')
    report = {'format': 'agf-native-world-source/v1', 'map_name': map_name, 'source_map': old_name,
              'source_digest': digest, 'levelbuild': str(root), 'game_root': manifest['game_root'],
              'grid': state['grid'], 'inventory': {path.name: sha256(path.read_bytes()) for path in root.iterdir() if path.is_file()},
              'bake_verified': False, 'runtime_verified': False}
    (destination / 'native-world-source.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def _run_phase(game, output, name, command, timeout=600):
    runner = Path(__file__).resolve().parents[1] / 'scripts/run_observed_build.py'
    phase = output / name
    print('Native world: ' + name, file=sys.stderr, flush=True)
    result = subprocess.run([sys.executable, '-B', str(runner), '--cwd', str(game / 'Tools'), '--output', str(phase),
                             '--timeout', str(timeout), '--', *map(str, command)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Native world ' + name + ' failed; inspect ' + str(phase) + '\n' + result.stdout + result.stderr)
    record = json.loads((phase / 'process.json').read_text(encoding='utf-8'))
    if record['state'] != 'exited' or record['exit_code'] != 0 or record['captured_dialogs']:
        raise RuntimeError('Native world build is not complete: ' + str(phase))
    return record


def build_native_world(compiled, destination):
    from .toolchain_lock import compiler_workspace_lock
    manifest = json.loads((Path(compiled['snapshot']) / 'native-source.json').read_text(encoding='utf-8'))
    with compiler_workspace_lock(manifest['game_root'], destination):
        return _build_native_world_locked(compiled, destination)


def _build_native_world_locked(compiled, destination):
    destination = Path(destination).resolve()
    source = prepare_native_world(compiled, destination)
    game = Path(source['game_root'])
    local = default_mod_parent().parent
    local_source = local / 'LevelBuild' / source['map_name']
    if local_source.exists():
        actual = {path.name: sha256(path.read_bytes()) for path in local_source.iterdir() if path.is_file()}
        if actual != source['inventory']:
            raise ValueError('Existing native compiler source differs; never overwrite it')
    else:
        shutil.copytree(source['levelbuild'], local_source)
    executable = game / 'WARNO.exe'
    phases = {}
    phases['generation'] = _run_phase(game, destination, 'generation',
        [executable, 'CommonData:Clusters/Bootstrap/ClusterBootstrapGeneration.ndf', '-headless', '-uselocaldata'])
    phases['cooking'] = _run_phase(game, destination, 'cooking',
        [game / 'Tools/AssetCooker.exe', '-e', 'ProgDir:/CoreCatalog.cat', '-g', '../Gen', '-l', 'EugenSystems/WARNO'])
    phases['baking'] = _run_phase(game, destination, 'baking',
        [executable, 'CommonData:Clusters/Bootstrap/ClusterBootstrapBaking.ndf', '-uselocaldata', '-mapname', source['map_name']],
        timeout=1800)
    grid_path = game / 'Gen/DatasMap' / source['map_name'] / 'Output/StrategicGridData.ndfbin'
    grid = source['grid']
    grid_path.write_bytes(write_grid(grid_path.read_bytes(), grid['width'], grid['height'], grid['tiles']))
    phases['map_packing'] = _run_phase(game, destination, 'map-packing',
        [game / 'Tools/DataPacker.exe', 'pack', 'ProgDir:/DataPacking/datapack_baked_map.ndf', 'ZZ:/DatasMap/MapName.ndf',
         '-gendir', '../Gen', '-local-data', 'EugenSystems/WARNO', '-outputdir', 'LocalSaveDir:/DatasMap'])
    phases['registration'] = _run_phase(game, destination, 'registration',
        [game / 'Tools/DataPacker.exe', 'pack', 'ProgDir:/DataPacking/datapack_local_maps.ndf',
         '-gendir', '../Gen', '-local-data', 'EugenSystems/WARNO'])
    payload = destination / 'payload'
    for directory in ('Maps', 'DatasMap'):
        (payload / directory).mkdir(parents=True)
    for suffix in ('Definition', 'Details', 'Assets'):
        name = source['map_name'] + '_' + suffix + '.dat'
        shutil.copyfile(local / 'Datapacks/Maps' / name, payload / 'Maps' / name)
    for suffix in ('', '_Shooting', '_Stickers'):
        name = source['map_name'] + suffix + '.dat'
        shutil.copyfile(local / 'DatasMap' / name, payload / 'DatasMap' / name)
    textures = game / 'Gen/PC/Texture' / source['map_name']
    shutil.copytree(textures, payload / 'Gen/PC/Texture' / source['map_name'])
    validation = verify_native_world_payload(payload, source)
    report = {**source, 'payload': str(payload), 'phases': phases, 'verification': validation, 'bake_verified': True,
              'files': {path.relative_to(payload).as_posix(): sha256(path.read_bytes()) for path in payload.rglob('*') if path.is_file()}}
    (destination / 'native-world-build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def verify_native_world_payload(root, source):
    root = Path(root)
    def unpack(path):
        raw = path.read_bytes(); header, entries, _ = read_directory(raw)
        return {entry.path.replace('\\', '/'): raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size] for entry in entries}
    name = source['map_name']
    main = unpack(root / 'DatasMap' / (name + '.dat'))
    details = unpack(root / 'Maps' / (name + '_Details.dat'))
    assets = unpack(root / 'Maps' / (name + '_Assets.dat'))
    definitions = unpack(root / 'Maps' / (name + '_Definition.dat'))
    _, map_info = decode(definitions['NDF/Maps/MapDefinition/' + name + '.ndfbin'])
    names = [prop['value'].get('value') for obj in map_info['objects'] if obj['class'] == 'TMapLoadInfo'
             for prop in obj['properties'] if prop['property_name'] == 'Name']
    if names != [name]:
        raise ValueError('Rebuilt map registration has the wrong identity')
    if {key: sha256(raw) for key, raw in details.items()} != source['inventory']:
        raise ValueError('Packed native world source differs from the edited inputs')
    grid = read_grid(main['Output/StrategicGridData.ndfbin'])
    if grid != {key: source['grid'][key] for key in ('width', 'height', 'tiles')}:
        raise ValueError('Packed native cell terrain differs from editor data')
    cooked, _ = read_texture(assets['PC/Texture/' + name + '/HeightMap.tgv'])
    import io
    with Image.open(io.BytesIO(details['HeightMap.png'])) as original:
        if cooked.size != original.size or cooked.convert('I').tobytes() != original.convert('I').tobytes():
            raise ValueError('Cooked native height pixels differ from the edited raster')
    baked, _ = read_texture(main['Output/HeightFieldWithDisplacement.tgv'])
    if baked.size[0] < 2 or baked.size[1] < 2:
        raise ValueError('Baked native heightfield is empty')
    cooked_surface, _ = read_texture(assets['PC/Texture/' + name + '/Div_map.tgv'])
    with Image.open(io.BytesIO(details['Div_map.webp'])) as original:
        expected = original.convert('RGB')
        actual = cooked_surface.convert('RGB')
        if expected.size != actual.size:
            raise ValueError('Cooked native surface dimensions changed')
        from PIL import ImageChops, ImageStat
        difference = ImageStat.Stat(ImageChops.difference(expected, actual))
        mean_error = max(difference.mean)
        # Stock macro surfaces use BC1. Error is measured against source pixels,
        # rather than pretending this lossy native texture is byte-identical.
        if mean_error > 8:
            raise ValueError('Cooked native surface differs excessively from editor artwork')
    return {'source_files': len(details), 'grid_cells': len(grid['tiles']), 'height_pixel_exact': True,
            'surface_mean_channel_error': mean_error,
            'baked_height_size': list(baked.size), 'baked_height_extrema': list(baked.getextrema()), 'runtime_verified': False}
