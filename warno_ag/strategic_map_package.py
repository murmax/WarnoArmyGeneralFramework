"""Map-package operations that do not edit tactical-map geometry."""

import shutil
from pathlib import Path

from .archives import read_directory, repack
from .cndf import decode, empty_objects
from .strategic_grid_binary import DEFAULT_TERRAIN, TERRAIN_CODES, read_grid, write_grid, write_uniform_grid


GRID_PATH = 'Output\\StrategicGridData.ndfbin'
STICKERS_PATH = 'Output\\StaticStickersFxs.ndfbin'
BUILDINGS_PATH = 'Output\\BuildingsBoxList.ndfbin'
BAKED_CANVAS_RESOURCES = frozenset({
    'BuildingsBoxList.ndfbin', 'HeightFieldWithDisplacement.tgv',
    'mapbuildings.ndfbin', 'Output.sdb', 'save.lbh',
    'StaticStickersFxs.ndfbin', 'StrategicGridData.ndfbin',
    'WaterMeshes_v2.ndfbin',
})
RUNTIME_TEXTURES = frozenset({
    'Div_map.tgv', 'HeightMap.tgv', 'Minimap.tgv', 'Overview.tgv',
    'Preview.tgv', 'Splat_map.tgv', 'WaterFlow.tgv',
})
MAP_DEFINITION_KINDS = ('MapConstante', 'MapDefinition', 'MapLoader', 'MapTextures')

NATIVE_ACTION_POINT_STEP = 13000


def native_raster_dimensions(contract):
    left, bottom, right, top = contract['bounds']
    if left != 0 or bottom != 0:
        raise ValueError('Native strategic map bounds must start at zero')
    return (int(right // NATIVE_ACTION_POINT_STEP) + 1,
            int(top // NATIVE_ACTION_POINT_STEP) + 1)


def authored_native_tiles(contract, strategic_grid=None):
    """Project authored cells onto native tiles by their world-space centers.

    The native raster dimensions and its 13000-unit step never change to match
    the logical authoring grid. Outside that grid the map default remains intact.
    """
    width, height = native_raster_dimensions(contract)
    if contract['default_terrain'] not in TERRAIN_CODES:
        raise ValueError('Unsupported native default terrain')
    tiles = [TERRAIN_CODES[contract['default_terrain']]] * (width * height)
    if strategic_grid is None:
        return tiles
    from .strategic_grid import StrategicGrid
    grid = StrategicGrid.from_config(strategic_grid)
    left, bottom, right, top = grid.bounds
    limits = contract.get('playable_bounds', contract['bounds'])
    if not limits[0] <= left < right <= limits[2] or not limits[1] <= bottom < top <= limits[3]:
        raise ValueError('Authored strategic cells extend outside playable bounds')
    if any(cell.terrain not in TERRAIN_CODES for cell in grid.cells):
        raise ValueError('Authored strategic cells contain unsupported native terrain')
    # Stock strategic grids use low bit 0 for the connected road network; the
    # terrain enum occupies bits 2..4. Low bit 1 has separate stock semantics
    # and is deliberately left unset for authored maps.
    cells = {(cell.row, cell.column): TERRAIN_CODES[cell.terrain] | int(cell.road)
             for cell in grid.cells}
    for row in range(height):
        y = (row + .5) * NATIVE_ACTION_POINT_STEP
        if not bottom <= y < top:
            continue
        grid_row = min(grid.height - 1, int((y - bottom) / (top - bottom) * grid.height))
        for column in range(width):
            x = (column + .5) * NATIVE_ACTION_POINT_STEP
            if left <= x < right:
                grid_column = min(grid.width - 1, int((x - left) / (right - left) * grid.width))
                tiles[row * width + column] = cells[grid_row, grid_column]
    return tiles


def strategic_map_registration_names(contract):
    return tuple(contract['map_name'] + '_' + suffix + '.dat'
                 for suffix in ('Definition', 'Details', 'Assets'))


def _validate_map_registration(root, contract):
    names = strategic_map_registration_names(contract)
    directory = root / 'Maps'
    if not directory.is_dir() or {path.name for path in directory.iterdir()} != set(names):
        raise ValueError('Strategic map registration archive inventory mismatch')
    definition, details, assets = [_archive_payloads((directory / name).read_bytes())
                                  for name in names]
    map_name = contract['map_name']
    expected = {f'NDF/Maps/{kind}/{map_name}.{suffix}'
                for kind in MAP_DEFINITION_KINDS for suffix in ('ndfbin', 'tag')}
    if set(definition) != expected:
        raise ValueError('Strategic map registration resource mismatch')
    _, graph = decode(definition[f'NDF/Maps/MapDefinition/{map_name}.ndfbin'])
    roots = [obj for obj in graph['objects']
             if obj['class'] == 'TMapLoadInfo' and obj['is_top_object']]
    if len(roots) != 1:
        raise ValueError('Strategic map registration lacks one TMapLoadInfo')
    properties = {prop['property_name']: prop['value'].get('value')
                  for prop in roots[0]['properties']}
    left, bottom, right, top = contract['bounds']
    if properties.get('Name') != map_name or properties.get('Size') != [right-left, top-bottom]:
        raise ValueError('Strategic map registration identity or size mismatch')
    _, loader = decode(definition[f'NDF/Maps/MapLoader/{map_name}.ndfbin'])
    required = {f'Maps/{map_name}_Details.dat',
                *(f'MapsDatapacks:/{name}' for name in strategic_map_runtime_names(contract))}
    if not required <= set(loader['strings']):
        raise ValueError('Strategic map loader archive references mismatch')
    if not {'Map.ndf', 'GraphicSettings.ndf', 'HeightMap.png'} <= set(details):
        raise ValueError('Strategic map details source is incomplete')
    expected_assets = {'PC/Texture/' + map_name + '/' + name for name in RUNTIME_TEXTURES}
    if set(assets) != expected_assets:
        raise ValueError('Strategic map asset archive inventory mismatch')
    for relative, payload in assets.items():
        if (root / 'Gen' / relative).read_bytes() != payload:
            raise ValueError('Strategic map packed texture differs from cooked texture')
    return {'archives': list(names), 'name': properties['Name'], 'size': properties['Size'],
            'definition_resources': len(definition), 'details_resources': len(details),
            'asset_resources': len(assets)}


def _archive_payloads(raw):
    header, entries, _ = read_directory(raw)
    if header.version != 3:
        raise ValueError('Strategic map archive must use EDAT v3')
    return {entry.path: raw[header.file_offset + entry.offset:
                            header.file_offset + entry.offset + entry.size]
            for entry in entries}


def strategic_map_runtime_names(contract):
    map_name = contract['map_name']
    return (map_name + '.dat', map_name + '_Shooting.dat', map_name + '_Stickers.dat')


def validate_strategic_map_runtime(root, contract, *, world_assets=None, strategic_grid=None):
    """Validate the complete runtime surface mounted by a campaign mod."""
    root = Path(root).resolve()
    names = strategic_map_runtime_names(contract)
    data_root = root / 'DatasMap'
    if not data_root.is_dir() or {path.name for path in data_root.iterdir() if path.is_file()} != set(names):
        raise ValueError('Strategic map runtime archive inventory mismatch')
    archives = {name: (data_root / name).read_bytes() for name in names}
    main = _archive_payloads(archives[names[0]])
    expected_main = {'Output/' + name for name in BAKED_CANVAS_RESOURCES}
    if set(main) != expected_main:
        raise ValueError('Strategic map main archive resource mismatch')
    grid = read_grid(main['Output/StrategicGridData.ndfbin'])
    if (grid['width'], grid['height']) != native_raster_dimensions(contract):
        raise ValueError('Strategic map native raster dimensions mismatch')
    if grid['tiles'] != authored_native_tiles(contract, strategic_grid):
        raise ValueError('Strategic map runtime terrain mismatch')
    expected_grid = grid
    for name in ('StaticStickersFxs.ndfbin', 'mapbuildings.ndfbin'):
        _, graph = decode(main['Output/' + name])
        if graph['objects']:
            raise ValueError('Strategic map runtime contains inherited objects: ' + name)
    _, water = decode(main['Output/WaterMeshes_v2.ndfbin'])
    if (len(water['objects']) != 1 or water['objects'][0]['class'] != 'TWaterMeshPack'
            or water['objects'][0]['properties']):
        raise ValueError('Strategic map runtime contains water geometry')
    shooting = _archive_payloads(archives[names[1]])
    if not shooting or not any(path.startswith('Output/ShootingHighDef/') for path in shooting):
        raise ValueError('Strategic map runtime lacks shooting resources')
    stickers = _archive_payloads(archives[names[2]])
    if set(stickers) != {'Output/StaticStickers_v02.stickers'}:
        raise ValueError('Strategic map sticker archive mismatch')
    texture_root = root / 'Gen/PC/Texture' / contract['map_name']
    if (not texture_root.is_dir()
            or {path.name for path in texture_root.iterdir() if path.is_file()} != RUNTIME_TEXTURES):
        raise ValueError('Strategic map runtime texture inventory mismatch')
    if any(not (texture_root / name).read_bytes() for name in RUNTIME_TEXTURES):
        raise ValueError('Strategic map runtime contains an empty texture')
    declared = (root / 'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines()
    expected_declared = {'ZZ:/DatasMap/' + name for name in names}
    expected_declared.update('ZZ:/Maps/' + name for name in strategic_map_registration_names(contract))
    if not expected_declared <= set(declared):
        raise ValueError('Strategic map runtime archives are not declared to the loader')
    from .world_assets import validate_world_runtime
    registration = _validate_map_registration(root, contract)
    details = _archive_payloads((root / 'Maps' / (contract['map_name'] + '_Details.dat')).read_bytes())
    world_report = validate_world_runtime(main, details, contract, world_assets)
    return {'map_name': contract['map_name'], 'archives': list(names),
            'archive_entries': {name: len(_archive_payloads(raw)) for name, raw in archives.items()},
            'textures': sorted(RUNTIME_TEXTURES), 'grid': expected_grid,
            'registration': registration,
            **({'world': world_report} if world_report is not None else {})}


def publish_strategic_map_runtime(root, contract, *, datas_map=None, texture_root=None, maps=None, world_assets=None, strategic_grid=None):
    """Copy one validated locally baked surface into a candidate tree."""
    root = Path(root).resolve()
    maps = Path(maps).resolve() if maps is not None else (
        Path.home() / 'Saved Games/EugenSystems/WARNO/Datapacks/Maps')
    datas_map = Path(datas_map).resolve() if datas_map is not None else (
        Path.home() / 'Saved Games/EugenSystems/WARNO/DatasMap')
    from .game_paths import game_root
    texture_root = Path(texture_root).resolve() if texture_root is not None else (
        game_root() / 'Gen/PC/Texture' / contract['map_name'])
    names = strategic_map_runtime_names(contract)
    registration_names = strategic_map_registration_names(contract)
    if any(not (maps / name).is_file() for name in registration_names):
        raise ValueError('Locally packed strategic map registration archives are missing')
    if any(not (datas_map / name).is_file() for name in names):
        raise ValueError('Locally packed strategic map archives are missing')
    if (not texture_root.is_dir()
            or {path.name for path in texture_root.iterdir() if path.is_file() and path.suffix == '.tgv'}
               != RUNTIME_TEXTURES):
        raise ValueError('Locally cooked strategic map textures are missing')
    destination_data = root / 'DatasMap'
    destination_data.mkdir(parents=True, exist_ok=True)
    if any(destination_data.iterdir()):
        raise ValueError('Candidate DatasMap directory is not empty')
    for name in names:
        source = datas_map / name
        target = destination_data / name
        if (name == contract['map_name'] + '.dat' and
                {path.replace('\\', '/') for path in (GRID_PATH, STICKERS_PATH, BUILDINGS_PATH)} <= {path.replace('\\', '/') for path in _archive_payloads(source.read_bytes())}):
            width, height = native_raster_dimensions(contract)
            build_blank_strategic_package(source, target, width=width, height=height,
                                          terrain=contract['default_terrain'], clear_static_fx=False,
                                          tiles=authored_native_tiles(contract, strategic_grid))
        else:
            shutil.copyfile(source, target)
    destination_textures = root / 'Gen/PC/Texture' / contract['map_name']
    if destination_textures.exists():
        raise ValueError('Candidate already contains strategic map textures')
    destination_textures.mkdir(parents=True)
    for name in RUNTIME_TEXTURES:
        shutil.copyfile(texture_root / name, destination_textures / name)
    destination_maps = root / 'Maps'
    destination_maps.mkdir(parents=True, exist_ok=True)
    if any(destination_maps.iterdir()):
        raise ValueError('Candidate Maps directory is not empty')
    for name in registration_names:
        shutil.copyfile(maps / name, destination_maps / name)
    declared_path = root / 'Gen/DeclaredFiles.txt'
    declared = declared_path.read_text(encoding='utf-8').splitlines()
    expected_declared = {'ZZ:/DatasMap/' + name for name in names}
    expected_declared.update('ZZ:/Maps/' + name for name in registration_names)
    if not expected_declared <= set(declared):
        declared.extend(sorted(expected_declared - set(declared)))
        declared_path.write_text('\n'.join(declared) + '\n', encoding='utf-8')
    return validate_strategic_map_runtime(root, contract, world_assets=world_assets, strategic_grid=strategic_grid)


def finalize_blank_baked_output(root, *, width=8, height=8, terrain=DEFAULT_TERRAIN):
    """Validate a newly baked empty surface and replace its generated strategic grid."""
    output = Path(root).resolve() / 'Output'
    if not output.is_dir():
        raise ValueError('Baked strategic map lacks Output directory')
    present = {path.name for path in output.iterdir() if path.is_file()}
    missing = BAKED_CANVAS_RESOURCES - present
    if missing:
        raise ValueError(f'Baked strategic map lacks required resources: {sorted(missing)}')
    for name in ('StaticStickersFxs.ndfbin', 'mapbuildings.ndfbin'):
        _, graph = decode((output / name).read_bytes(), str(output / name))
        if graph['objects']:
            raise ValueError(f'Blank strategic map contains objects in {name}')
    _, water = decode((output / 'WaterMeshes_v2.ndfbin').read_bytes())
    if (len(water['objects']) != 1 or water['objects'][0]['class'] != 'TWaterMeshPack'
            or water['objects'][0]['properties']):
        raise ValueError('Blank strategic map contains water geometry')
    for name, magic in (('save.lbh', b'LBH0'), ('Output.sdb', b'SDB\r\n')):
        if not (output / name).read_bytes().startswith(magic):
            raise ValueError(f'Invalid baked resource: {name}')
    height_field = (output / 'HeightFieldWithDisplacement.tgv').read_bytes()
    if len(height_field) < 32 or height_field[:4] != b'\x03\0\0\0':
        raise ValueError('Invalid baked height field')
    grid_path = output / 'StrategicGridData.ndfbin'
    original = grid_path.read_bytes()
    baked_grid = read_grid(original)
    if width is None or height is None:
        raise ValueError('Canvas strategic grid dimensions must be explicit')
    grid_path.write_bytes(write_uniform_grid(original, width, height, terrain))
    grid = read_grid(grid_path.read_bytes())
    expected = {'width': width, 'height': height,
                'tiles': [4] * (width * height)}
    if terrain != DEFAULT_TERRAIN:
        from .strategic_grid_binary import TERRAIN_CODES
        expected['tiles'] = [TERRAIN_CODES[terrain]] * (width * height)
    if grid != expected:
        raise ValueError('Final strategic grid readback mismatch')
    return {'output': str(output), 'grid': grid,
            'resources': sorted(BAKED_CANVAS_RESOURCES)}


def build_blank_strategic_package(source, destination, *, width=101, height=101, terrain=DEFAULT_TERRAIN, clear_static_fx=True, tiles=None):
    """Create a strategic package with explicit tiles (uniform by default)."""
    source = Path(source)
    raw = source.read_bytes()
    header, entries, _ = read_directory(raw)
    payloads = {}
    for entry in entries:
        start = header.file_offset + entry.offset
        payloads[entry.path] = raw[start:start + entry.size]
    keys = {path.replace('\\', '/'): path for path in payloads}
    required = {path.replace('\\', '/') for path in (GRID_PATH, STICKERS_PATH, BUILDINGS_PATH)}
    if not required <= set(keys):
        raise ValueError('Strategic package lacks required grid/sticker resources')
    grid_key = keys[GRID_PATH.replace('\\', '/')]
    stickers_key = keys[STICKERS_PATH.replace('\\', '/') ]
    payloads[grid_key] = (write_uniform_grid(payloads[grid_key], width, height, terrain) if tiles is None
                         else write_grid(payloads[grid_key], width, height, tiles))
    if clear_static_fx:
        sticker_doc, sticker_graph = decode(payloads[stickers_key])
        if sticker_graph['classes'] != ['TLevelBuildStaticFX']:
            raise ValueError('Unexpected strategic static-FX schema')
        payloads[stickers_key] = empty_objects(sticker_doc)
    result = repack(raw, payloads)
    out = Path(destination)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result)
    return result
