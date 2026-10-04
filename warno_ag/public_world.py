"""Bake and verify a new authored strategic map before publishing its campaign."""
import json
from pathlib import Path
import shutil

from .deployment import default_mod_parent
from .native_world import _run_phase, verify_native_world_payload
from .storage import safe_child, sha256
from .strategic_grid_binary import write_grid
from .strategic_map_package import (RUNTIME_TEXTURES, authored_native_tiles,
                                    native_raster_dimensions)
from .toolchain_lock import compiler_workspace_lock
from .world_assets import load_world_asset_recipe


def _inventory(root):
    return {path.name: sha256(path.read_bytes()) for path in root.iterdir() if path.is_file()}


def _payload(local, game, name, destination):
    payload = destination / 'payload'
    for suffix in ('Definition', 'Details', 'Assets'):
        filename = name + '_' + suffix + '.dat'
        target = payload / 'Maps' / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local / 'Datapacks/Maps' / filename, target)
    for suffix in ('', '_Shooting', '_Stickers'):
        filename = name + suffix + '.dat'
        target = payload / 'DatasMap' / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local / 'DatasMap' / filename, target)
    textures = game / 'Gen/PC/Texture' / name
    if not textures.is_dir() or {path.name for path in textures.iterdir()
                                 if path.is_file() and path.suffix == '.tgv'} != RUNTIME_TEXTURES:
        raise ValueError('Official authored-map texture inventory is incomplete or unexpected')
    target = payload / 'Gen/PC/Texture' / name
    target.mkdir(parents=True)
    for texture in sorted(RUNTIME_TEXTURES):
        shutil.copyfile(textures / texture, target / texture)
    return payload


def bake_public_world(prepared, compiled, game_root, destination, *, progress=None):
    """Use the official local toolchain, then bind exact map archives to source.

    Existing packed maps are accepted only when every byte-level/source
    readback matches the prepared world.  No map is installed or activated.
    """
    prepared = Path(prepared).resolve()
    game = Path(game_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    contract = compiled['adapter']['strategic_map']
    recipe = load_world_asset_recipe(prepared, contract)
    source = recipe['source']
    name = contract['map_name']
    expected_inventory = source['source_inventory']
    dimensions = native_raster_dimensions(contract)
    grid = {'width': dimensions[0], 'height': dimensions[1],
            'tiles': authored_native_tiles(contract, compiled['map'].get('strategic_grid'))}
    digest = sha256(json.dumps({'source': expected_inventory, 'grid': grid, 'game': str(game)},
                               sort_keys=True, separators=(',', ':')).encode())
    destination.mkdir(parents=True)
    report = {'format': 'agf-public-world-bake/v1', 'map_name': name,
              'source_digest': digest, 'prepared_source': str(prepared),
              'source_inventory': expected_inventory, 'game_root': str(game),
              'phases': {}, 'bake_verified': False, 'runtime_verified': False}
    try:
        with compiler_workspace_lock(game, destination):
            local = default_mod_parent().parent
            local_source = local / 'LevelBuild' / name
            if local_source.exists():
                if _inventory(local_source) != expected_inventory:
                    raise ValueError('Existing compiler LevelBuild differs from this authored map: ' + str(local_source))
            else:
                local_source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(safe_child(prepared, source['levelbuild']), local_source)
            registration = [local / 'Datapacks/Maps' / (name + '_' + suffix + '.dat')
                            for suffix in ('Definition', 'Details', 'Assets')]
            strategic = [local / 'DatasMap' / (name + suffix + '.dat')
                         for suffix in ('', '_Shooting', '_Stickers')]
            packed = registration + strategic
            if any(path.exists() for path in packed) and not all(path.is_file() for path in packed):
                raise ValueError('Incomplete existing authored-map compiler output; inspect it before retrying')
            reused = all(path.is_file() for path in packed)
            if not reused:
                executable = game / 'WARNO.exe'
                if progress: progress(3, 'Generating new map with official toolchain')
                report['phases']['generation'] = _run_phase(game, destination, 'world-generation',
                    [executable, 'CommonData:Clusters/Bootstrap/ClusterBootstrapGeneration.ndf',
                     '-headless', '-uselocaldata'])
                if progress: progress(8, 'Cooking new map textures')
                report['phases']['cooking'] = _run_phase(game, destination, 'world-cooking',
                    [game / 'Tools/AssetCooker.exe', '-e', 'ProgDir:/CoreCatalog.cat',
                     '-g', '../Gen', '-l', 'EugenSystems/WARNO'])
                if progress: progress(12, 'Baking new strategic map')
                report['phases']['baking'] = _run_phase(game, destination, 'world-baking',
                    [executable, 'CommonData:Clusters/Bootstrap/ClusterBootstrapBaking.ndf',
                     '-uselocaldata', '-mapname', name], timeout=1800)
                grid_path = game / 'Gen/DatasMap' / name / 'Output/StrategicGridData.ndfbin'
                grid_path.write_bytes(write_grid(grid_path.read_bytes(),
                                                 grid['width'], grid['height'], grid['tiles']))
                if progress: progress(17, 'Packing new map archives')
                report['phases']['map_packing'] = _run_phase(game, destination, 'world-map-packing',
                    [game / 'Tools/DataPacker.exe', 'pack',
                     'ProgDir:/DataPacking/datapack_baked_map.ndf', 'ZZ:/DatasMap/MapName.ndf',
                     '-gendir', '../Gen', '-local-data', 'EugenSystems/WARNO',
                     '-outputdir', 'LocalSaveDir:/DatasMap'])
                report['phases']['registration'] = _run_phase(game, destination, 'world-registration',
                    [game / 'Tools/DataPacker.exe', 'pack',
                     'ProgDir:/DataPacking/datapack_local_maps.ndf',
                     '-gendir', '../Gen', '-local-data', 'EugenSystems/WARNO'])
            report['reused_verified_local_bake'] = reused
            payload = _payload(local, game, name, destination)
            expected = {'map_name': name, 'inventory': expected_inventory, 'grid': grid}
            report['verification'] = verify_native_world_payload(payload, expected)
            report['payload'] = str(payload)
            report['files'] = {path.relative_to(payload).as_posix(): sha256(path.read_bytes())
                               for path in payload.rglob('*') if path.is_file()}
            report['bake_verified'] = True
            if progress: progress(22, 'New map bake verified against editor source')
        return report
    finally:
        (destination / 'public-world-bake.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
