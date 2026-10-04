"""Prepare isolated official compiler inputs; no runtime installation or activation."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile
import tempfile

from .modconfig import _parse

from .storage import sha256


def prepare_native_compiler_workspace(game_root, name, *, workspace_parent=None):
    game = Path(game_root).resolve()
    if re.fullmatch(r'WarnoAGF[A-Za-z0-9_]+Build[A-Za-z0-9_]*', name) is None:
        raise ValueError('Use an explicit WarnoAGF compiler workspace name')
    mods = (game / 'Mods').resolve()
    parent = Path(workspace_parent).resolve() if workspace_parent is not None else mods
    if not parent.is_dir():
        raise FileNotFoundError('Compiler workspace parent does not exist: ' + str(parent))
    destination = (parent / name).resolve()
    if destination.parent != parent or destination.exists():
        raise ValueError('Compiler workspace must be a new direct child of its selected parent')
    archive_path = mods / 'ModData/base.zip'
    with zipfile.ZipFile(archive_path) as archive:
        for entry in archive.infolist():
            relative = entry.filename.replace('\\', '/')
            path = (destination / relative).resolve()
            if not path.is_relative_to(destination) or ':' in relative:
                raise ValueError('Official source archive contains an unsafe path')
        destination.mkdir()
        archive.extractall(destination)
    shutil.copyfile(archive_path, destination / 'base.zip')
    result = subprocess.run([sys.executable, '-B', str(mods / 'Utils/Scripts/CreateAssetDefinitionFiles.py'), name],
                            cwd=destination, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError('Official source declarations failed: ' + result.stdout + result.stderr)
    report = {'format': 'agf-native-compiler-workspace/v1', 'workspace': str(destination),
              'workspace_parent': str(parent),
              'game_root': str(game), 'base_zip_sha256': sha256(archive_path.read_bytes()),
              'generation_run': False, 'runtime_installation_run': False}
    (destination / 'agf-compiler-workspace.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def freeze_native_compiler_output(workspace, destination):
    workspace, destination = Path(workspace).resolve(), Path(destination).resolve()
    if destination.exists() or not (workspace / 'agf-compiler-workspace.json').is_file():
        raise ValueError('Expected an owned compiler workspace and a new output directory')
    if not (workspace / 'Gen/ResourceFile/Catalog.cat').is_file() or not (workspace / 'Gen/DeclaredFiles.txt').is_file():
        raise ValueError('Official asset cooking has not completed')
    destination.mkdir(parents=True)
    shutil.copytree(workspace / 'Gen', destination / 'Gen')
    shutil.copyfile(workspace / 'Config.ini', destination / 'Config.ini')
    inventory = {path.relative_to(destination).as_posix(): sha256(path.read_bytes())
                 for path in destination.rglob('*') if path.is_file()}
    report = {'format': 'agf-native-compiler-template/v1', 'source': str(workspace), 'files': inventory,
              'policy': 'Replace compatibility-probe global clusters with source/edited native payloads before packaging'}
    (destination / 'compiler-template.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


def augment_native_compiler_template(base_template, official_config, destination,
                                     clusters=('GFX/Depiction', 'GFX/Division', 'UI/BattleOrder')):
    """Combine existing official ModGen compatibility proofs without running the game."""
    base = Path(base_template).resolve()
    proof = Path(official_config).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    report = json.loads((base / 'compiler-template.json').read_text(encoding='utf-8'))
    if report.get('format') != 'agf-native-compiler-template/v1':
        raise ValueError('Base compiler template has an unsupported format')
    original_config = (base / 'Config.ini').read_bytes()
    generated_config = proof.read_bytes()
    if _parse(original_config)['Properties'].get('ModGenVersion') != _parse(generated_config)['Properties'].get('ModGenVersion'):
        raise ValueError('Official compatibility proof uses another ModGen revision')
    known = _parse(generated_config)['Config']
    if any(cluster not in known for cluster in clusters):
        raise ValueError('Official ModGen config lacks the requested compatibility clusters')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-template-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'template'
        staged.mkdir()
        for relative, digest in report['files'].items():
            raw = (base / relative).read_bytes()
            if sha256(raw) != digest:
                raise ValueError('Base official compiler output changed: ' + relative)
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        proof_file = staged / 'compatibility-proofs' / 'official-Config.ini'
        proof_file.parent.mkdir(parents=True, exist_ok=True)
        proof_file.write_bytes(generated_config)
        extended = dict(report)
        existing = dict(report.get('compatibility_proofs', {}))
        for cluster in clusters:
            existing[cluster] = {'file': proof_file.relative_to(staged).as_posix(),
                                 'sha256': sha256(generated_config)}
        extended['compatibility_proofs'] = existing
        extended['source_provenance'] = {'primary': str(base),
            'additional_official_config': str(proof), 'modgen_revision':
                _parse(generated_config)['Properties'].get('ModGenVersion'),
            'game_executable_launched': False}
        (staged / 'compiler-template.json').write_text(json.dumps(extended, indent=2) + '\n', encoding='utf-8')
        staged.rename(destination)
    return {'template': str(destination), 'compatibility_proofs': existing,
            'game_executable_launched': False}
