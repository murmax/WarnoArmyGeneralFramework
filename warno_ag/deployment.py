"""Explicit local trial deployment. No activation, EXE launch or deletion of mods."""
from contextlib import contextmanager
import csv
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from .archives import repack
from .trial import (ARCHIVE, DISPLAY_NAME, MOD_NAME, fingerprint, framework_fingerprint, json_bytes,
                    registration_contract, relative_name, _tour_max)
from .storage import sha256


RECEIPT = '.ag-framework-receipt.json'
LEGACY_ARCHIVE = 'Scenarios/CampagneStrat_AGFrameworkMVP_Definition.dat'
MANIFEST_FIELDS = {'schema', 'adapter', 'mod_name', 'framework_sha256', 'game_files',
                   'files', 'payload', 'contract', 'package_prepared', 'runtime_verified',
                   'ready', 'status', 'activation', 'limitations', 'bundle_id'}


def plain_path(path):
    """Reject symlinks and Windows junctions, including any existing ancestor."""
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        try:
            status = part.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(status.st_mode)
                or getattr(status, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError(f'Redirected filesystem path: {part}')
    return path


def read_tree(root):
    root = plain_path(root)
    if not root.is_dir():
        raise ValueError('Expected a complete directory')
    files, directories = {}, set()
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = plain_path(Path(current)/name)
            relative = relative_name(path.relative_to(root).as_posix())
            if path.is_dir():
                directories.add(relative)
            elif path.is_file():
                files[relative] = path.read_bytes()
            else:
                raise ValueError('Non-regular file in trial directory')
    expected_dirs = {p.as_posix() for name in files for p in Path(name).parents if p != Path('.')}
    if directories != expected_dirs:
        raise ValueError('Unexpected empty directory in trial tree')
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError('Case-insensitive trial path collision')
    return files


def _manifest_id(manifest):
    return sha256(json_bytes({k: v for k, v in manifest.items() if k != 'bundle_id'}))


def verify_bundle(bundle):
    files = read_tree(bundle)
    manifest = json.loads(files.pop('bundle.json'))
    if (not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
            or type(manifest.get('schema')) is not int or manifest.get('schema') != 1
            or manifest.get('adapter') not in {'registration-only-v1', 'definition-mvp-v1'}
            or manifest.get('mod_name') != MOD_NAME
            or manifest.get('runtime_verified') is not False or manifest.get('ready') is not False
            or manifest.get('package_prepared') is not True
            or manifest.get('status') != 'experimental-runtime-candidate'
            or manifest.get('activation') != 'manual-mod-center'
            or manifest.get('bundle_id') != _manifest_id(manifest)):
        raise ValueError('Invalid or modified trial manifest')
    prefix = f'payload/{MOD_NAME}/'
    payload_names = {'Config.ini', ARCHIVE}
    expected_names = {prefix+n for n in payload_names} | {'module.json', 'build-report.json', 'TESTING.md'}
    if set(files) != expected_names or {n: sha256(b) for n, b in files.items()} != manifest['files']:
        raise ValueError('Trial bundle file inventory or checksum mismatch')
    payload = {n: files[prefix+n] for n in payload_names}
    if {n: sha256(b) for n, b in payload.items()} != manifest['payload']:
        raise ValueError('Trial payload checksum mismatch')
    repack(payload[ARCHIVE], {})
    contract = registration_contract(payload[ARCHIVE])
    if manifest['adapter'] == 'definition-mvp-v1':
        contract = {**contract, 'tour_max': _tour_max(payload[ARCHIVE])}
    if contract != manifest['contract']:
        raise ValueError('Trial contract mismatch')
    return manifest, payload


def default_mod_parent():
    return Path.home()/'Saved Games'/'EugenSystems'/'WARNO'/'mod'


def active_mods(mod_parent):
    path = plain_path(Path(mod_parent)/'Config.ini')
    if not path.exists():
        return []
    # Preserve the config verbatim; parsing here only supports preflight checks.
    data = path.read_bytes()
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    lines = data.decode(encoding).splitlines()
    found, section = [], ''
    for line in lines:
        line = line.split(';', 1)[0].strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1].casefold()
        elif section == 'config' and '=' in line:
            name, value = line.split('=', 1)
            if name.strip().casefold() == 'activatedmods':
                found.append([v.strip() for v in value.split('|') if v.strip()])
    if len(found) != 1:
        raise ValueError('Ambiguous or missing ActivatedMods in existing Config.ini')
    return found[0]


def ensure_game_stopped():
    if os.name != 'nt':
        raise ValueError('Local deployment currently supports Windows only')
    result = subprocess.run(['tasklist.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    # Image names are ASCII even with a localized tasklist; match every row.
    rows = list(csv.reader(io.StringIO(result.stdout.decode('utf-8', errors='replace'))))
    if not rows or any(len(row) != 5 for row in rows):
        raise ValueError('Cannot verify the process list; deployment refused')
    if any(row and row[0].casefold() == 'warno.exe' for row in rows):
        raise ValueError('Close WARNO before installing or rolling back a trial')


def _target(mod_parent):
    root = plain_path(mod_parent)
    if root == Path(root.anchor) or root.name.casefold() != 'mod':
        raise ValueError('Target parent must be a dedicated mod directory')
    return root, plain_path(root/MOD_NAME)


def plan_trial(bundle, game_root, mod_parent=None):
    manifest, payload = verify_bundle(bundle)
    if manifest['framework_sha256'] != framework_fingerprint():
        raise ValueError('Framework changed since build; rebuild the trial package')
    game_root = plain_path(game_root)
    game_files = manifest['game_files']
    required = {'WARNO.exe', 'Data/PC/201602/Scenarios/CampagneStrat_Bruderkrieg_Definition.dat',
                'Data/PC/169425/Scenarios/CampagneStrat_Bruderkrieg_Details.dat'}
    if set(game_files) != required:
        raise ValueError('Unexpected trial game dependency set')
    for name, digest in game_files.items():
        if fingerprint(plain_path(game_root/relative_name(name))) != digest:
            raise ValueError(f'Game fingerprint mismatch: {name}')
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    if root.is_relative_to(game_root) or game_root.is_relative_to(root):
        raise ValueError('Installation must be outside the game directory')
    if target.exists():
        raise FileExistsError(f'Refusing to replace existing mod: {target}')
    active = active_mods(root)
    if DISPLAY_NAME.casefold() in {n.casefold() for n in active}:
        raise ValueError('Trial is already activated; disable it before installation')
    return {'bundle_id': manifest['bundle_id'], 'destination': str(target),
            'files': manifest['payload'], 'bytes': sum(map(len, payload.values())),
            'active_mods': active, 'activation': 'manual-mod-center',
            'runtime_verified': False, 'writes_performed': False}


@contextmanager
def _transaction(root):
    # Staging and retired mods live OUTSIDE the game's mod discovery directory.
    state = plain_path(root.parent/'ag-framework-transactions')
    state.mkdir(parents=True, exist_ok=True)
    lock = state/'deployment.lock'
    lock.mkdir(exist_ok=False)
    try:
        yield state
    finally:
        lock.rmdir()  # Only our empty lock, never a recursive removal.


def _write_files(root, files):
    for name, data in files.items():
        path = plain_path(root/relative_name(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def _atomic_replace(path, data, state, prefix):
    path, state = plain_path(path), plain_path(state)
    handle, temporary = tempfile.mkstemp(prefix=prefix, dir=state)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(plain_path(temporary), path)
    except Exception:
        temporary = Path(temporary)
        if temporary.exists() and not list(temporary.parent.glob(temporary.name)) == []:
            # A failed, owned temporary file is retained for diagnosis.
            pass
        raise


def _set_activated(data, names):
    encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    lines = data.decode(encoding).splitlines(keepends=True)
    section, matches, output = '', 0, []
    for line in lines:
        content = line.rstrip('\r\n')
        ending = line[len(content):]
        stripped = content.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1].casefold()
        if section == 'config' and '=' in content:
            key = content.split('=', 1)[0].strip().casefold()
            if key == 'activatedmods':
                matches += 1
                comment = ';' + content.split(';', 1)[1] if ';' in content else ''
                content = f"ActivatedMods = {'|'.join(names)}"
                if comment: content += ' ' + comment
        output.append(content + ending)
    if matches != 1:
        raise ValueError('Ambiguous or missing ActivatedMods in existing Config.ini')
    return ''.join(output).encode(encoding)


def _managed_activation_equivalent(before, current, display_name=DISPLAY_NAME, allow_empty=False):
    """Allow only WARNO's known trailing-pipe canonicalization of our activation.

    Every non-ActivatedMods byte-content line must remain identical (apart from
    line-ending style), and the parsed activation must still be exclusively ours.
    """
    def parsed(data):
        encoding = 'utf-16' if data.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        lines, section, marked, activated = [], '', 0, []
        for raw in data.decode(encoding).splitlines():
            stripped = raw.strip()
            if stripped.startswith('[') and stripped.endswith(']'):
                section = stripped[1:-1].casefold()
            if section == 'config' and '=' in raw and raw.split('=', 1)[0].strip().casefold() == 'activatedmods':
                marked += 1
                value = raw.split('=', 1)[1].split(';', 1)[0]
                activated = [v.strip() for v in value.split('|') if v.strip()]
                lines.append('<managed-activation>')
            else:
                lines.append(raw)
        return encoding, lines, marked, activated
    old_encoding, old_lines, old_marked, _ = parsed(before)
    new_encoding, new_lines, new_marked, active = parsed(current)
    expected = ([display_name.casefold()], []) if allow_empty else ([display_name.casefold()],)
    return (old_encoding == new_encoding and old_marked == new_marked == 1
            and old_lines == new_lines
            and [value.casefold() for value in active] in expected)


def install_trial(bundle, game_root, mod_parent=None):
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    ensure_game_stopped()
    with _transaction(root) as state:
        plan = plan_trial(bundle, game_root, root)
        manifest, payload = verify_bundle(bundle)
        if manifest['bundle_id'] != plan['bundle_id']:
            raise ValueError('Bundle changed during preflight')
        stage = Path(tempfile.mkdtemp(prefix='install-', dir=state))
        staged_mod = stage/MOD_NAME
        receipt = {'schema': 1, 'adapter': 'registration-only-v1', 'mod_name': MOD_NAME,
                   'bundle_id': manifest['bundle_id'], 'destination': str(target),
                   'payload': manifest['payload'], 'activation_modified': False,
                   'activation_mode': None, 'config_before_sha256': None,
                   'config_after_sha256': None, 'config_backup': None}
        files = {**payload, RECEIPT: json_bytes(receipt)}
        _write_files(staged_mod, files)
        if read_tree(staged_mod) != files:
            raise ValueError(f'Staged copy verification failed; retained at {stage}')
        # Recheck mutable prerequisites immediately before publishing the directory.
        if plan_trial(bundle, game_root, root) != plan:
            raise ValueError('Installation preflight changed; staged copy retained')
        ensure_game_stopped()
        root.mkdir(parents=True, exist_ok=True)
        plain_path(target)
        if target.exists():
            raise FileExistsError('Destination appeared during staging')
        staged_mod.rename(target)  # Windows rename refuses to overwrite a directory.
        if read_tree(target) != files:
            raise ValueError(f'Installed copy changed; inspect receipt at {target}')
        stage.rmdir()  # The published child was moved; remove our now-empty staging root.
        return {**plan, 'writes_performed': True, 'installed': True,
                'receipt': str(target/RECEIPT), 'activation_modified': False}


def _owned_install(target):
    files = read_tree(target)
    receipt_bytes = files.pop(RECEIPT, None)
    if receipt_bytes is None:
        raise ValueError('No framework ownership receipt; installation is unverified')
    try:
        receipt = json.loads(receipt_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid framework ownership receipt') from exc
    base = {'schema', 'adapter', 'mod_name', 'bundle_id', 'destination',
            'payload', 'activation_modified'}
    activation = {'activation_mode', 'config_before_sha256', 'config_after_sha256',
                  'config_backup'}
    if set(receipt) == base:
        receipt.update({key:None for key in activation})
    if (set(receipt) != base|activation or receipt['schema'] != 1
            or receipt['adapter'] != 'registration-only-v1'
            or receipt['mod_name'] != MOD_NAME or receipt['destination'] != str(target)
            or set(receipt['payload']) not in ({'Config.ini', ARCHIVE},
                                               {'Config.ini', LEGACY_ARCHIVE})
            or {n: sha256(b) for n, b in files.items()} != receipt['payload']):
        raise ValueError('Installed files or ownership receipt changed')
    details = [receipt[k] for k in ('activation_mode', 'config_before_sha256',
                                    'config_after_sha256', 'config_backup')]
    if ((receipt['activation_modified'] is False and details != [None]*4)
            or (receipt['activation_modified'] is True and
                (receipt['activation_mode'] != 'exclusive' or
                 any(not isinstance(v, str) or not v for v in details[1:])))):
        raise ValueError('Installed activation receipt is inconsistent')
    return files, receipt, receipt_bytes


def status_trial(mod_parent=None):
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    active = DISPLAY_NAME.casefold() in {n.casefold() for n in active_mods(root)}
    if not target.exists():
        return {'destination': str(target), 'installed': False, 'active': active,
                'owned': False, 'integrity_verified': False}
    _, receipt, _ = _owned_install(target)
    return {'destination': str(target), 'installed': True, 'active': active,
            'owned': True, 'integrity_verified': True,
            'bundle_id': receipt['bundle_id'], 'payload': receipt['payload'],
            'activation_modified': receipt['activation_modified'],
            'activation_managed': receipt['activation_modified']}


def activate_trial(mod_parent=None):
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    ensure_game_stopped()
    with _transaction(root) as state:
        _, receipt, _ = _owned_install(target)
        config = plain_path(root/'Config.ini')
        if not config.is_file():
            raise ValueError('Shared mod Config.ini is missing')
        before = config.read_bytes()
        after = _set_activated(before, [DISPLAY_NAME])
        if receipt['activation_modified']:
            backup = plain_path(receipt['config_backup'])
            if fingerprint(backup) != receipt['config_before_sha256']:
                raise ValueError('Activation backup changed')
            current = sha256(before)
            if current == receipt['config_before_sha256']:
                _atomic_replace(config, after, state, 'activate-config-')
            elif current != receipt['config_after_sha256']:
                raise ValueError('Shared mod Config.ini changed during managed activation')
            return {**status_trial(root), 'config_backup': str(backup)}
        backups = plain_path(state/'activation-backups')
        backups.mkdir(parents=True, exist_ok=True)
        backup = plain_path(backups/(receipt['bundle_id']+'-'+sha256(before)[:16]+'.ini'))
        if backup.exists():
            if backup.read_bytes() != before: raise ValueError('Activation backup collision')
        else:
            with backup.open('xb') as stream:
                stream.write(before); stream.flush(); os.fsync(stream.fileno())
        receipt.update({'activation_modified': True, 'activation_mode': 'exclusive',
                        'config_before_sha256': sha256(before),
                        'config_after_sha256': sha256(after), 'config_backup': str(backup)})
        _atomic_replace(target/RECEIPT, json_bytes(receipt), state, 'activate-receipt-')
        _atomic_replace(config, after, state, 'activate-config-')
        return {**status_trial(root), 'config_backup': str(backup)}


def deactivate_trial(mod_parent=None):
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    ensure_game_stopped()
    with _transaction(root) as state:
        _, receipt, _ = _owned_install(target)
        if not receipt['activation_modified']:
            if DISPLAY_NAME.casefold() in {n.casefold() for n in active_mods(root)}:
                raise ValueError('Active trial was not activated by this receipt; cannot restore config')
            return status_trial(root)
        backup = plain_path(receipt['config_backup'])
        if fingerprint(backup) != receipt['config_before_sha256']:
            raise ValueError('Activation backup changed')
        config = plain_path(root/'Config.ini')
        current = config.read_bytes()
        digest = sha256(current)
        if digest == receipt['config_after_sha256']:
            _atomic_replace(config, backup.read_bytes(), state, 'deactivate-config-')
        elif _managed_activation_equivalent(backup.read_bytes(), current):
            # WARNO itself writes `Name|` for one active mod. Its textual
            # canonicalization is accepted only after the strict comparison
            # above; any other config edit remains a hard stop.
            _atomic_replace(config, backup.read_bytes(), state, 'deactivate-config-')
        elif digest != receipt['config_before_sha256']:
            raise ValueError('Shared mod Config.ini changed during managed activation')
        receipt.update({'activation_modified': False, 'activation_mode': None,
                        'config_before_sha256': None, 'config_after_sha256': None,
                        'config_backup': None})
        _atomic_replace(target/RECEIPT, json_bytes(receipt), state, 'deactivate-receipt-')
        return status_trial(root)


def rollback_trial(mod_parent=None):
    root, target = _target(mod_parent if mod_parent is not None else default_mod_parent())
    ensure_game_stopped()
    with _transaction(root) as state:
        files, receipt, receipt_bytes = _owned_install(target)
        if receipt['activation_modified']:
            raise ValueError('Deactivate managed trial before rollback')
        if DISPLAY_NAME.casefold() in {n.casefold() for n in active_mods(root)}:
            raise ValueError('Disable the trial in Mod Center before rollback')
        retired = Path(tempfile.mkdtemp(prefix='retired-', dir=state))/MOD_NAME
        ensure_game_stopped()
        if DISPLAY_NAME.casefold() in {n.casefold() for n in active_mods(root)}:
            raise ValueError('Trial activation changed during rollback')
        # A second inventory check catches changes after the ownership check.
        if read_tree(target) != {**files, RECEIPT: receipt_bytes}:
            raise ValueError('Installed tree changed during rollback preflight')
        plain_path(retired)
        target.rename(retired)
        if read_tree(retired) != {**files, RECEIPT: receipt_bytes}:
            raise ValueError(f'Retired copy changed; inspect {retired}')
        return {'removed_from_mod_directory': str(target), 'retained_at': str(retired),
                'files_deleted': 0, 'activation_modified': False,
                'bundle_id': receipt['bundle_id']}
