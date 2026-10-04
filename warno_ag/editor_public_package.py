"""Build an authored public campaign with a fresh official ModGen workspace."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .authoring import compile_campaign
from .battleground_policy import validate_authored_battleground_policy
from .bruderkrieg import package_authored_campaign
from .deployment import default_mod_parent
from .event_images import BANK_PATH, merge_event_texture_bank
from .modgen import prepare_modgen_project
from .native_toolchain import prepare_native_compiler_workspace, freeze_native_compiler_output
from .storage import safe_child, sha256
from .toolchain_lock import compiler_workspace_lock


def _progress(percent, message):
    print(f'AGF_EDITOR_PROGRESS\t{percent}\t{message}', file=sys.stderr, flush=True)


def _observed_phase(workspace, output, name, command):
    runner = Path(__file__).resolve().parents[1] / 'scripts/run_observed_build.py'
    phase = output / name
    result = subprocess.run([sys.executable, '-B', str(runner), '--cwd', str(workspace),
                             '--output', str(phase), '--timeout', '600', '--', *map(str, command)],
                            capture_output=True, text=True, check=False)
    report_path = phase / 'process.json'
    if not report_path.is_file():
        raise RuntimeError(f'{name}: observed process report missing: {result.stderr}')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if (result.returncode or report['state'] != 'exited' or report['exit_code'] != 0
            or report['captured_dialogs']):
        raise RuntimeError(f'{name}: official build failed; inspect {phase}')
    return report


def _stage_event_images(workspace, staged):
    staged = Path(staged).resolve()
    manifest = json.loads((staged / 'event-images.compiled.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'agf-event-images-compiled-v1':
        raise ValueError('Expected a compiled event-image recipe')
    bank = workspace / BANK_PATH
    original = bank.read_text(encoding='utf-8-sig')
    fragment = (staged / 'event-texture-bank.ndf').read_text(encoding='utf-8')
    for record in manifest['images']:
        source = safe_child(staged, record['asset'])
        target = safe_child(workspace, record['asset'])
        if (not source.is_file() or target.exists()
                or sha256(source.read_bytes()) != record['asset_sha256']):
            raise ValueError('Private event artwork is absent or collides with stock: ' + record['asset'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    bank.write_text(merge_event_texture_bank(original, fragment), encoding='utf-8')


def package_public_editor_campaign(source, profile, game_root, destination, *,
                                   world_source=None, event_images=None,
                                   workspace_parent=None):
    """Compile, generate, cook and verify a new bundle; never installs or activates it."""
    game = Path(game_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    for relative in ('Mods/ModData/base.zip', 'WARNO.exe', 'Tools/AssetCooker.exe'):
        if not (game / relative).is_file():
            raise FileNotFoundError('Official WARNO compiler input is missing: ' + str(game / relative))
    compiled, _ = compile_campaign(source, profile)
    validate_authored_battleground_policy(compiled)
    name = 'WarnoAGFEditorBuild' + uuid.uuid4().hex[:12].upper()
    destination.mkdir(parents=True)
    compiler_parent = Path(workspace_parent).resolve() if workspace_parent is not None else game / 'Mods'
    workspace = compiler_parent / name
    report = {'format': 'agf-editor-public-package/v1', 'source': str(Path(source).resolve()),
              'game_root': str(game), 'compiler_workspace': str(workspace),
              'steps': {}, 'runtime_verified': False, 'installed': False}
    try:
        map_runtime = None
        if world_source is not None:
            from .public_world import bake_public_world
            _progress(1, 'Checking authored world source and official bake')
            report['steps']['world_bake'] = bake_public_world(
                world_source, compiled, game, destination / 'world-bake', progress=_progress)
            map_runtime = report['steps']['world_bake']['payload']
        with compiler_workspace_lock(game, destination):
            _progress(23 if map_runtime else 2, 'Creating isolated official compiler workspace')
            report['steps']['workspace'] = prepare_native_compiler_workspace(
                game, name, workspace_parent=compiler_parent)
            _progress(27 if map_runtime else 13, 'Generating campaign battalions and localisation')
            report['steps']['sources'] = prepare_modgen_project(workspace, workspace, source, profile)
            if event_images is not None:
                _progress(31 if map_runtime else 20, 'Adding event portraits to the private texture bank')
                _stage_event_images(workspace, event_images)
            _progress(35 if map_runtime else 24, 'Running official ModGen generation')
            report['steps']['generation'] = _observed_phase(workspace, destination, 'generation',
                [game / 'WARNO.exe', '-headless', '-c', '-', '-generatemod', name,
                 '-rootdata', '.', 'CommonData:Clusters/Bootstrap/ClusterBootstrapGeneration.ndf'])
            _progress(60 if map_runtime else 55, 'Cooking official game assets')
            report['steps']['cooking'] = _observed_phase(workspace, destination, 'cooking',
                [game / 'Tools/AssetCooker.exe', '-e', 'ProgDir:/CoreCatalog.cat',
                 '-g', './Gen/', '--common-data', './CommonData/', '--game-data', './GameData/'])
            config = default_mod_parent() / name / 'Config.ini'
            if not config.is_file():
                raise FileNotFoundError('Official ModGen Config.ini was not generated: ' + str(config))
            if (workspace / 'Config.ini').exists():
                raise FileExistsError('Fresh compiler workspace unexpectedly already has Config.ini')
            shutil.copyfile(config, workspace / 'Config.ini')
            _progress(75 if map_runtime else 66, 'Freezing official compiler output')
            report['steps']['output'] = freeze_native_compiler_output(workspace, destination / 'official-output')
            _progress(82 if map_runtime else 72, 'Assembling and verifying independent campaign bundle')
            report['package'] = package_authored_campaign(source, profile,
                destination / 'official-output', destination / 'package',
                world_source=world_source, event_images=event_images, map_runtime=map_runtime)
            from .full_campaign import verify_full_bundle
            manifest, files = verify_full_bundle(
                report['package']['bundle'], report['package']['config'])
            report['steps']['verification'] = {'bundle_id': manifest['bundle_id'],
                                               'file_count': len(files)}
        _progress(100, 'Complete bundle verified')
        return report
    finally:
        (destination / 'editor-package-report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
