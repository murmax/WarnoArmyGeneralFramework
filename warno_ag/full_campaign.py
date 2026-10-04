"""Offline acceptance contract for the complete Red Line Army General client."""
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile

from .archives import read_directory, repack
from .cndf import decode
from .marshal26 import loads
from .scriptgraph import decode_script
from .storage import sha256, safe_child
from .transforms import patch_script
from .xyz import XYZ
from . import deployment as deploy
from .trial import framework_fingerprint, json_bytes


SCENARIO = 'CampagneStrat_RedLine1989'
PARTS = ('Definition', 'Details', 'GameData', 'Assets')
TITLE_HASH = bytes.fromhex('ffb96ac6b4063f54')
SUBTITLE_HASH = bytes.fromhex('1f0ab9d25a71cc44')
BRIEF_HASH = bytes.fromhex('2f0ab9d25a71cc44')
OBJECTIVES_HASH = bytes.fromhex('3f0ab9d25a71cc44')
MOD_NAME = 'WarnoAGFRedLine1989'
DISPLAY_NAME = 'AG Framework - Red Line 1989'
BUILD_NAME = 'WarnoAGFRedLineBuild'
RECEIPT = '.ag-framework-full-receipt.json'


def _final_modgen_config(raw):
    text = raw.decode('ascii')
    old = f'Name = {BUILD_NAME}'
    if text.count(old) != 1 or 'ModGenVersion = 201602' not in text:
        raise ValueError('Input is not the expected current ModGen output config')
    if 'GFX/Pawn=0efca67d988866bcc3fbb01e73ab4168' not in text:
        raise ValueError('Current GFX/Pawn compatibility fingerprint changed')
    return text.replace(old, f'Name = {DISPLAY_NAME}').encode('ascii')


def _publish_generated_localisation(root):
    base = root/'Gen/AllPlatforms/Localisation'
    for language in ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US'):
        for relative in (Path(SCENARIO)/'TROPHIES.dic',
                         Path(SCENARIO)/'Scripting'/'Dialog.dic',
                         Path(SCENARIO)/'Scripting'/'Localization.dic'):
            source = base/language/relative
            if not source.is_file():
                raise ValueError(f'Missing source localisation dictionary: {source}')
            for generated_root in (base/'Localisation',
                                   root/'Gen/Localisation/Localisation'):
                target = generated_root/relative.parent/f'{relative.stem}-{language}.dic'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    for language in ('RU', 'US'):
        source = base/language/'Localisation/Core/MAPS.dic'
        if not source.is_file():
            raise ValueError(f'Missing source MAPS dictionary: {source}')
        for generated_root in (base/'Localisation', root/'Gen/Localisation/Localisation'):
            target = generated_root/f'Core/MAPS-{language}.dic'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())


def _payload(raw, suffix):
    header, entries, _ = read_directory(raw)
    found = [entry for entry in entries if entry.path.replace('\\', '/').endswith(suffix)]
    if len(found) != 1:
        raise ValueError(f'Missing or ambiguous campaign resource: {suffix}')
    entry = found[0]
    return raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size]


def _property(obj, name):
    found = [p['value'] for p in obj['properties'] if p['property_name'] == name]
    if len(found) != 1:
        raise ValueError(f'Missing or ambiguous {obj["class"]}.{name}')
    return found[0]


def _trad_data(raw):
    if not isinstance(raw, bytes):
        raise ValueError('TRAD dictionary must be bytes')
    if len(raw) < 8 or raw[:4] != b'TRAD':
        raise ValueError('Invalid TRAD dictionary')
    count = struct.unpack_from('<I', raw, 4)[0]
    if 8 + count * 16 > len(raw):
        raise ValueError('Truncated TRAD table')
    result = {}
    for index in range(count):
        offset = 8 + index * 16
        key = raw[offset:offset + 8]
        text_offset, length = struct.unpack_from('<II', raw, offset + 8)
        end = text_offset + length * 2
        if end > len(raw) or key in result:
            raise ValueError('Invalid or duplicate TRAD entry')
        result[key] = raw[text_offset:end].decode('utf-16le')
    return result


def _pack_trad(entries):
    """Build a deterministic TRAD dictionary from eight-byte keys and text."""
    if not isinstance(entries, dict) or not entries:
        raise ValueError('TRAD entries must be a non-empty dictionary')
    rows = []
    # Eugen dictionaries are ordered by the numeric little-endian uint64 hash;
    # the engine performs ordered lookup rather than scanning the whole table.
    for key, text in sorted(entries.items(), key=lambda item:int.from_bytes(item[0], 'little')):
        if not isinstance(key, bytes) or len(key) != 8:
            raise ValueError('TRAD key must be exactly eight bytes')
        if not isinstance(text, str):
            raise ValueError('TRAD text must be a string')
        encoded = text.encode('utf-16le')
        rows.append((key, encoded, len(encoded) // 2))
    text_offset = 8 + len(rows) * 16
    table = bytearray()
    payload = bytearray()
    for key, encoded, length in rows:
        table.extend(key)
        table.extend(struct.pack('<II', text_offset + len(payload), length))
        payload.extend(encoded)
    result = b'TRAD' + struct.pack('<I', len(rows)) + bytes(table) + bytes(payload)
    if _trad_data(result) != entries:
        raise ValueError('TRAD deterministic build failed round-trip validation')
    return result


def _trad(path):
    return _trad_data(Path(path).read_bytes())


def _gamedata_contract(root, config):
    pawn = root/'Gen/NDF/GFX/Pawn.ndfbin'
    _, graph = decode(pawn.read_bytes())
    exports = set(graph['exports'].values())
    classes = {row['class_name'] for row in config['campaign']['spawn_keep']}
    classes |= {'$/GFX/Pawn/Descriptor_Unit_nk_US_Disabled',
                '$/GFX/Pawn/Descriptor_Unit_nk_SOV_Disabled'}
    missing = classes - exports
    if missing:
        raise ValueError(f'Missing compiled strategic unit descriptors: {sorted(missing)}')
    return len(classes)


def _scenario_contract(definition, config):
    raw = definition.read_bytes()
    repack(raw, {})
    scenario_raw = _payload(raw, f'/ScenarioDB/{SCENARIO}.ndfbin')
    _, graph = decode(scenario_raw)
    addons, positions = {}, {}
    for obj in graph['objects']:
        if obj['class'] == 'TGameDesignAddOn_Spawn':
            addons[_property(obj, 'Name')['value']] = (obj['id'], _property(obj, 'ClassName')['value'])
    for obj in graph['objects']:
        if obj['class'] == 'TGameDesignItem':
            addon, position = _property(obj, 'AddOn'), _property(obj, 'Position')
            if addon.get('type') == 'obj_ref':
                positions[addon['object_id']] = position['value']
    expected = {row['name']: row for row in config['campaign']['spawn_keep']}
    if not expected or len(addons) < len(expected):
        raise ValueError('Unexpected strategic spawn inventory')
    red_tanks = red_aa = 0
    for name, row in expected.items():
        if name not in addons:
            raise ValueError(f'Missing configured spawn: {name}')
        object_id, class_name = addons[name]
        if class_name != row['class_name'] or positions.get(object_id) != [row['x'], row['y']]:
            raise ValueError(f'Spawn contract mismatch: {name}')
        if '_RDA_' in name or '_SOV_' in name:
            is_aa = 'SAM' in class_name or 'AAR' in class_name
            red_aa += int(is_aa)
            red_tanks += int(not is_aa and ('PzR' in class_name or 'Tk' in class_name
                                            or 'Tank' in class_name))
    if (red_tanks, red_aa) != (2, 2):
        raise ValueError('Red battalions are not exactly two tank and two air-defence')
    disabled = config['campaign']['disabled_spawn_classes']
    for name, (object_id, class_name) in addons.items():
        if name in expected:
            continue
        side = 'sov' if any(token in name for token in ('_RDA_', '_SOV_', '_PACT_')) else 'us'
        if class_name != disabled[side]:
            raise ValueError(f'Non-candidate spawn is not a disabled placeholder: {name}')
    return {'spawn_count': len(addons), 'active_spawn_count': len(expected),
            'red_tank_count': red_tanks, 'red_air_defence_count': red_aa}


def _legacy_xyz_resources(assets):
    raw = Path(assets).read_bytes()
    header, entries, _ = read_directory(raw)
    result = []
    for entry in entries:
        name = entry.path.replace('\\', '/')
        if (name.endswith(f'/Map/Scenario/{SCENARIO}/Scripting/effetmap.xyz')
                and ('/F0/' in name or '/F1/' in name)):
            payload = raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size]
            result.append((entry.path, payload))
    if len(result) != 2:
        raise ValueError('Legacy campaign must contain exactly F0/F1 effetmap.xyz scripts')
    return result


def _named_script_object(graph, editor_name, object_id=None):
    found = [obj for obj in graph['objects'].values()
             if obj['properties'].get('EditorName', {}).get('value') == editor_name]
    if not found and object_id in graph['objects']:
        found = [graph['objects'][object_id]]
    if len(found) != 1:
        raise ValueError(f'Missing or ambiguous legacy script object: {editor_name}')
    return found[0]


def _script_contract(root):
    loose = root/f'Gen/NDF/Scenarios/GDScript/{SCENARIO}.ndfbin'
    scripts = _legacy_xyz_resources(root/f'Scenarios/{SCENARIO}_Assets.dat')
    if loose.exists():
        raise ValueError('Candidate has two campaign script providers (legacy XYZ and loose GDScript)')
    paths = None
    selectors = None
    for name, raw in scripts:
        graph = decode_script(loads(XYZ.read(raw).payload))
        tour = _named_script_object(graph, '~/intro/script/Variables/TourMax',
                                    selectors and selectors['tour'])
        unlock = _named_script_object(
            graph, '~/partie_OTAN/Script/Variables/OTAN/arrivee_13ebrig',
            selectors and selectors['unlock'])
        production = _named_script_object(
            graph, '~/partie_OTAN/Script/Renforts/OTAN/add_pawn_to_renfort_13_pzgren_brig',
            selectors and selectors['production'])
        if selectors is None:
            selectors = {'tour': tour['id'], 'unlock': unlock['id'],
                         'production': production['id']}
        if tour['kwargs']['Value']['value'] != 8 or unlock['kwargs']['Value']['value'] != 2:
            raise ValueError('Legacy turn/reinforcement contract mismatch')
        current = [item['path'] for item in production['kwargs']['Pawns']['items']]
        if len(current) != 6 or len(set(current)) != 6:
            raise ValueError('Legacy reinforcement battalion inventory mismatch')
        if paths is not None and current != paths:
            raise ValueError('F0/F1 reinforcement graphs disagree')
        paths = current
    return {'script_provider': 'Assets.dat/effetmap.xyz', 'turn_limit': 8,
            'reinforcement_unlock_turn': 2, 'reinforcement_battalion_count': 6,
            'reinforcements': paths}


def repair_legacy_candidate(source, destination, config_path):
    """Convert the failed mixed-generation candidate to one legacy script graph."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f'Refusing to replace candidate: {destination}')
    loose = source/f'Gen/NDF/Scenarios/GDScript/{SCENARIO}.ndfbin'
    if not loose.is_file():
        raise ValueError('Source is not the known mixed-provider candidate')
    shutil.copytree(source, destination)
    (destination/'Config.ini').write_bytes((source/'Config.ini').read_bytes())
    _publish_generated_localisation(destination)
    for suffix in ('ndfbin', 'tag'):
        path = destination/f'Gen/NDF/Scenarios/GDScript/{SCENARIO}.{suffix}'
        if path.exists():
            path.unlink()
    gdscript = destination/'Gen/NDF/Scenarios/GDScript'
    while gdscript != destination/'Gen' and gdscript.exists() and not any(gdscript.iterdir()):
        parent = gdscript.parent
        gdscript.rmdir()
        gdscript = parent
    for name in ('current-definition-overlay.dat', 'current-definition-overlay-report.json'):
        path = destination/name
        if path.exists():
            path.unlink()
    assets = destination/f'Scenarios/{SCENARIO}_Assets.dat'
    assets_raw = assets.read_bytes()
    replacements = {}
    selectors = None
    for name, raw in _legacy_xyz_resources(assets):
        graph = decode_script(loads(XYZ.read(raw).payload))
        tour = _named_script_object(graph, '~/intro/script/Variables/TourMax',
                                    selectors and selectors['tour'])
        unlock = _named_script_object(graph, '~/partie_OTAN/Script/Variables/OTAN/arrivee_13ebrig',
                                      selectors and selectors['unlock'])
        if selectors is None:
            selectors = {'tour': tour['id'], 'unlock': unlock['id']}
            selector_key = 'editor_name'
            tour_selector = '~/intro/script/Variables/TourMax'
            unlock_selector = '~/partie_OTAN/Script/Variables/OTAN/arrivee_13ebrig'
        else:
            selector_key = 'object_id'
            tour_selector, unlock_selector = selectors['tour'], selectors['unlock']
        spec = {'source_sha256': sha256(raw), 'operations': [
            {selector_key: tour_selector,
             'constructor': tour['constructor'], 'argument': 'Value',
             'expected': 12, 'value': 8},
            {selector_key: unlock_selector,
             'constructor': unlock['constructor'], 'argument': 'Value',
             'expected': 9, 'value': 2},
        ]}
        replacements[name] = patch_script(raw, spec)[0]
    changed = repack(assets_raw, replacements)
    if changed == assets_raw:
        raise ValueError('Legacy Assets archive was not changed')
    assets.write_bytes(changed)
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    scenario = _scenario_contract(destination/f'Scenarios/{SCENARIO}_Definition.dat', config)
    script = _script_contract(destination)
    return {**scenario, **script}


def assemble_modgen_candidate(modgen_output, scenario_candidate, destination, config_path):
    modgen_output, scenario_candidate, destination = map(
        lambda p: Path(p).resolve(), (modgen_output, scenario_candidate, destination))
    if destination.exists():
        raise FileExistsError(f'Refusing to replace candidate: {destination}')
    shutil.copytree(modgen_output, destination)
    (destination/'Config.ini').write_bytes(
        _final_modgen_config((modgen_output/'Config.ini').read_bytes()))
    for folder in ('Scenarios', 'ScenariosData'):
        source = scenario_candidate/folder
        target = destination/folder
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    # Source-language dictionaries are inputs; publish the runtime language-suffixed form.
    source_loc = scenario_candidate/'Gen/AllPlatforms/Localisation'
    target_loc = destination/'Gen/AllPlatforms/Localisation'
    for language in ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US'):
        source = source_loc/language/SCENARIO
        target = target_loc/language/SCENARIO
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
    for language in ('RU', 'US'):
        source = source_loc/language/'Localisation/Core/MAPS.dic'
        target = target_loc/language/'Localisation/Core/MAPS.dic'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _publish_generated_localisation(destination)
    return validate_full_campaign(destination, config_path)


def validate_full_campaign(root, config_path):
    root, config_path = Path(root).resolve(), Path(config_path).resolve()
    supplied = json.loads(config_path.read_text(encoding='utf-8'))
    if supplied.get('format') == 'native-campaign-v1':
        from .native_package import validate_native_candidate
        return validate_native_candidate(root, supplied)
    if supplied.get('format') == 'authored-campaign-v1':
        from .bruderkrieg import validate_authored_candidate
        contract = validate_authored_candidate(root, supplied)
        # Official ModGen creates empty Maps/DatasMap/DecorsSets directories.
        # A release consists of files; the immutable payload writer recreates
        # only their parent directories, just as for current native candidates.
        files = {path.relative_to(root).as_posix(): path.read_bytes()
                 for path in sorted(root.rglob('*')) if path.is_file()}
        return {'scenario': _runtime_identity(config_path)['scenario'], 'format': 'authored-campaign-v1', **contract,
                'file_count': len(files),
                'files': {name: sha256(data) for name, data in files.items()}}
    scenario_dir = root/'Scenarios'
    current_names = {f'{SCENARIO}_Definition.dat', f'{SCENARIO}_Details.dat'}
    if scenario_dir.is_dir() and {p.name for p in scenario_dir.glob('*.dat')} == current_names:
        # New candidates have one current native script provider and the current
        # Details archive. Keep legacy validation only for retained failed-build
        # regression fixtures.
        from .current_campaign import validate_current_candidate
        return validate_current_candidate(root, config_path)
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config['campaign']['new_id'] != SCENARIO:
        raise ValueError('Full-campaign identity mismatch')
    config_raw = (root/'Config.ini').read_bytes()
    if (f'Name = {DISPLAY_NAME}'.encode() not in config_raw
            or b'ModGenVersion = 201602' not in config_raw
            or b'GFX/Pawn=0efca67d988866bcc3fbb01e73ab4168' not in config_raw):
        raise ValueError('Mod Config.ini is not a current compiled ModGen config')
    required = [root/'Config.ini'] + [root/f'Scenarios/{SCENARIO}_{part}.dat' for part in PARTS]
    required += [root/f'Gen/AllPlatforms/Localisation/Localisation/Core/MAPS-{lang}.dic'
                 for lang in ('RU', 'US')]
    required += [root/f'Gen/AllPlatforms/Localisation/Localisation/{SCENARIO}/{name}-{lang}.dic'
                 for lang in ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')
                 for name in ('TROPHIES', 'Scripting/Dialog', 'Scripting/Localization')]
    if any(not path.is_file() for path in required):
        raise ValueError('Full campaign is missing a required file')
    for part in PARTS:
        repack((root/f'Scenarios/{SCENARIO}_{part}.dat').read_bytes(), {})
    scenario = _scenario_contract(root/f'Scenarios/{SCENARIO}_Definition.dat', config)
    script = _script_contract(root)
    descriptors = _gamedata_contract(root, config)
    ru = _trad(required[5])
    us = _trad(required[6])
    expected_ru = {
        TITLE_HASH: 'Красный рубеж — 1989',
        SUBTITLE_HASH: 'Новая испытательная кампания «Генерала армий»',
        BRIEF_HASH: config['campaign']['localisation']['ru']['brief'],
        OBJECTIVES_HASH: config['campaign']['localisation']['ru']['objectives_text'],
    }
    if any(ru.get(key) != value for key, value in expected_ru.items()):
        raise ValueError('Russian campaign localisation contract mismatch')
    if us.get(TITLE_HASH) != 'Red Line 1989':
        raise ValueError('Fallback campaign localisation contract mismatch')
    videos = list((root/f'ScenariosData/{SCENARIO}/Scripting/Videos').glob('*.webm'))
    if len(videos) != 7:
        raise ValueError('Campaign video fallback inventory mismatch')
    files = sorted(path for path in root.rglob('*') if path.is_file()
                   and path.name not in ('current-definition-overlay.dat', 'current-definition-overlay-report.json'))
    return {'scenario': SCENARIO, **scenario, **script,
            'strategic_descriptor_count': descriptors, 'video_count': len(videos),
            'file_count': len(files),
            'files': {path.relative_to(root).as_posix(): sha256(path.read_bytes()) for path in files}}


def _runtime_identity(config_path=None):
    if config_path is not None:
        compiled = json.loads(Path(config_path).read_text(encoding='utf-8'))
        if compiled.get('format') == 'native-campaign-v1':
            return compiled['identity']
        if compiled.get('format') == 'authored-campaign-v1':
            from .campaign_identity import campaign_identity
            return campaign_identity(compiled)
    return {'scenario': SCENARIO, 'mod_name': MOD_NAME, 'display_name': DISPLAY_NAME}


def _activation_tokens(identity):
    tokens = [identity['display_name']]
    local_id = identity.get('local_mod_id')
    if local_id is not None:
        if type(local_id) is not int or not 0 < local_id < (1 << 63):
            raise ValueError('Invalid local activation identity')
        tokens.append(str(local_id))
    return tokens


def _full_active(root, identity):
    active = {name.casefold() for name in deploy.active_mods(root)}
    return any(token.casefold() in active for token in _activation_tokens(identity))


def _full_activation_equivalent(before, current, identity):
    return any(deploy._managed_activation_equivalent(before, current, token, allow_empty=True)
               for token in _activation_tokens(identity))


def write_full_bundle(candidate, config_path):
    identity = _runtime_identity(config_path)
    candidate = Path(candidate).resolve()
    contract = validate_full_campaign(candidate, config_path)
    files = {name: (candidate/name).read_bytes() for name in contract['files']}
    manifest = {'schema': 1, 'adapter': 'full-campaign-v1', 'mod_name': identity['mod_name'],
                'display_name': identity['display_name'], 'framework_sha256': framework_fingerprint(),
                'config_sha256': sha256(Path(config_path).resolve().read_bytes()),
                'contract': {key: value for key, value in contract.items() if key != 'files'},
                'payload': {name: sha256(data) for name, data in files.items()}}
    manifest['bundle_id'] = sha256(json_bytes(manifest))
    target = Path(__file__).resolve().parents[1]/'artifacts'/'full-trials'/manifest['bundle_id'][:16]
    if target.exists():
        existing, _ = verify_full_bundle(target, config_path)
        if existing != manifest:
            raise ValueError('Deterministic full bundle directory collision')
        return target
    target.mkdir(parents=True, exist_ok=False)
    payload = target/'payload'/identity['mod_name']
    for name, data in files.items():
        path = safe_child(payload, name); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    (target/'bundle.json').write_bytes(json_bytes(manifest))
    verify_full_bundle(target, config_path)
    return target


def verify_full_bundle(bundle, config_path):
    identity = _runtime_identity(config_path)
    bundle = deploy.plain_path(bundle)
    manifest_path = bundle/'bundle.json'
    if not manifest_path.is_file():
        raise ValueError('Full bundle manifest is missing')
    manifest = json.loads(manifest_path.read_bytes())
    fields = {'schema', 'adapter', 'mod_name', 'display_name', 'framework_sha256',
              'config_sha256', 'contract', 'payload', 'bundle_id'}
    if (not isinstance(manifest, dict) or set(manifest) != fields or manifest['schema'] != 1
            or manifest['adapter'] != 'full-campaign-v1' or manifest['mod_name'] != identity['mod_name']
            or manifest['display_name'] != identity['display_name']
            or manifest['bundle_id'] != sha256(json_bytes({k:v for k,v in manifest.items() if k!='bundle_id'}))
            or manifest['config_sha256'] != sha256(Path(config_path).resolve().read_bytes())):
        raise ValueError('Invalid full bundle manifest')
    payload_root = deploy.plain_path(bundle/'payload'/identity['mod_name'])
    files = deploy.read_tree(payload_root)
    if {name: sha256(data) for name, data in files.items()} != manifest['payload']:
        raise ValueError('Full bundle inventory or checksum mismatch')
    contract = validate_full_campaign(payload_root, config_path)
    if {key:value for key,value in contract.items() if key!='files'} != manifest['contract']:
        raise ValueError('Full bundle semantic contract mismatch')
    return manifest, files


def _target(mod_parent=None, config_path=None):
    identity = _runtime_identity(config_path)
    root = deploy.plain_path(mod_parent if mod_parent is not None else deploy.default_mod_parent())
    if root == Path(root.anchor) or root.name.casefold() != 'mod':
        raise ValueError('Target parent must be a dedicated mod directory')
    return root, deploy.plain_path(root/identity['mod_name'])


def status_full(config_path, mod_parent=None):
    identity = _runtime_identity(config_path)
    root, target = _target(mod_parent, config_path)
    if not target.is_dir():
        return {'installed': False, 'active': False, 'owned': False,
                'integrity_verified': False, 'activation_managed': False}
    try:
        _, receipt, _ = _owned(target)
        bundle = Path(__file__).resolve().parents[1]/'artifacts'/'full-trials'/receipt['bundle_id'][:16]
        manifest, _ = verify_full_bundle(bundle, config_path)
        active = _full_active(root, identity)
        return {'installed': True, 'active': active, 'owned': True,
                'integrity_verified': manifest['bundle_id'] == receipt['bundle_id'],
                'activation_managed': receipt['activation_modified'],
                'bundle_id': receipt['bundle_id']}
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {'installed': True, 'active': False, 'owned': False,
                'integrity_verified': False, 'activation_managed': False}


def plan_full_install(bundle, config_path, mod_parent=None):
    identity = _runtime_identity(config_path)
    manifest, files = verify_full_bundle(bundle, config_path)
    if manifest['framework_sha256'] != framework_fingerprint():
        raise ValueError('Framework changed since the full bundle was built')
    root, target = _target(mod_parent, config_path)
    if target.exists():
        raise FileExistsError(f'Refusing to replace existing mod: {target}')
    if _full_active(root, identity):
        raise ValueError('Full campaign is already active')
    return {'bundle_id': manifest['bundle_id'], 'destination': str(target),
            'file_count': len(files), 'bytes': sum(map(len, files.values())),
            'writes_performed': False}


def _owned(target):
    files = deploy.read_tree(target)
    raw = files.pop(RECEIPT, None)
    if raw is None:
        raise ValueError('Full campaign ownership receipt is missing')
    receipt = json.loads(raw)
    expected = {'schema','adapter','mod_name','bundle_id','destination','payload',
                'activation_modified','config_before_sha256','config_after_sha256','config_backup'}
    if (set(receipt) != expected or receipt['schema'] != 1 or receipt['adapter'] != 'full-campaign-v1'
            or receipt['mod_name'] != target.name or receipt['destination'] != str(target)
            or {name:sha256(data) for name,data in files.items()} != receipt['payload']):
        raise ValueError('Full campaign installation changed')
    return files, receipt, raw


def install_full(bundle, config_path, mod_parent=None):
    identity = _runtime_identity(config_path)
    deploy.ensure_game_stopped()
    root, target = _target(mod_parent, config_path)
    with deploy._transaction(root) as state:
        plan = plan_full_install(bundle, config_path, root)
        manifest, files = verify_full_bundle(bundle, config_path)
        stage = Path(tempfile.mkdtemp(prefix='full-install-', dir=state)); staged = stage/identity['mod_name']
        receipt = {'schema':1,'adapter':'full-campaign-v1','mod_name':identity['mod_name'],
                   'bundle_id':manifest['bundle_id'],'destination':str(target),
                   'payload':manifest['payload'],'activation_modified':False,
                   'config_before_sha256':None,'config_after_sha256':None,'config_backup':None}
        deploy._write_files(staged, {**files, RECEIPT:json_bytes(receipt)})
        if deploy.read_tree(staged) != {**files, RECEIPT:json_bytes(receipt)}:
            raise ValueError('Full campaign staged copy verification failed')
        if plan_full_install(bundle, config_path, root) != plan:
            raise ValueError('Full campaign preflight changed during staging')
        deploy.ensure_game_stopped(); root.mkdir(parents=True, exist_ok=True); staged.rename(target)
        if deploy.read_tree(target) != {**files, RECEIPT:json_bytes(receipt)}:
            raise ValueError('Full campaign installed copy verification failed')
        stage.rmdir()
        return {**plan, 'writes_performed':True, 'installed':True, 'receipt':str(target/RECEIPT)}


def activate_full(mod_parent=None, config_path=None):
    identity = _runtime_identity(config_path)
    deploy.ensure_game_stopped(); root,target=_target(mod_parent, config_path)
    with deploy._transaction(root) as state:
        _,receipt,_=_owned(target); config=deploy.plain_path(root/'Config.ini'); before=config.read_bytes()
        if receipt['activation_modified']:
            raise ValueError('Full campaign activation is already managed')
        after=deploy._set_activated(before,[identity['display_name']]); backups=state/'activation-backups';backups.mkdir(exist_ok=True)
        backup=deploy.plain_path(backups/(receipt['bundle_id']+'-'+sha256(before)[:16]+'-full.ini'))
        if backup.exists() and backup.read_bytes()!=before: raise ValueError('Activation backup collision')
        if not backup.exists(): backup.write_bytes(before)
        receipt.update({'activation_modified':True,'config_before_sha256':sha256(before),
                        'config_after_sha256':sha256(after),'config_backup':str(backup)})
        deploy._atomic_replace(target/RECEIPT,json_bytes(receipt),state,'full-receipt-')
        deploy._atomic_replace(config,after,state,'full-config-')
        return {'installed':True,'active':True,'bundle_id':receipt['bundle_id'],'config_backup':str(backup)}


def deactivate_full(mod_parent=None, config_path=None):
    identity = _runtime_identity(config_path)
    deploy.ensure_game_stopped(); root,target=_target(mod_parent, config_path)
    with deploy._transaction(root) as state:
        _,receipt,_=_owned(target)
        if not receipt['activation_modified']:
            if _full_active(root, identity):
                raise ValueError('Unmanaged full campaign activation')
            return {'installed':True,'active':False,'bundle_id':receipt['bundle_id']}
        backup=deploy.plain_path(receipt['config_backup']); before=backup.read_bytes()
        if sha256(before)!=receipt['config_before_sha256']: raise ValueError('Activation backup changed')
        config=deploy.plain_path(root/'Config.ini')
        # CrashRpt's "Deactivate all mods" option can remove Config.ini while
        # our managed activation receipt and its exact pre-activation backup
        # remain intact.  A missing shared config is therefore a valid
        # externally-deactivated state: restore the verified backup before
        # retiring the owned mod tree.
        current=config.read_bytes() if config.is_file() else None
        if (current is not None and sha256(current)!=receipt['config_after_sha256'] and
                not _full_activation_equivalent(before, current, identity)):
            raise ValueError('Shared mod Config.ini changed during managed activation')
        deploy._atomic_replace(config,before,state,'full-deactivate-')
        receipt.update({'activation_modified':False,'config_before_sha256':None,
                        'config_after_sha256':None,'config_backup':None})
        deploy._atomic_replace(target/RECEIPT,json_bytes(receipt),state,'full-receipt-')
        return {'installed':True,'active':False,'bundle_id':receipt['bundle_id']}


def rollback_full(mod_parent=None, config_path=None):
    identity = _runtime_identity(config_path)
    deploy.ensure_game_stopped(); root,target=_target(mod_parent, config_path)
    with deploy._transaction(root) as state:
        files,receipt,receipt_raw=_owned(target)
        if receipt['activation_modified'] or _full_active(root, identity):
            raise ValueError('Deactivate the full campaign before rollback')
        retired=Path(tempfile.mkdtemp(prefix='full-retired-',dir=state))/identity['mod_name']
        if deploy.read_tree(target)!={**files,RECEIPT:receipt_raw}: raise ValueError('Installed tree changed')
        target.rename(retired)
        if deploy.read_tree(retired)!={**files,RECEIPT:receipt_raw}: raise ValueError('Retired tree changed')
        return {'removed_from_mod_directory':str(target),'retained_at':str(retired),
                'files_deleted':0,'bundle_id':receipt['bundle_id']}


def uninstall_full(config_path, mod_parent=None):
    """Remove the complete owned mod tree from WARNO, retaining it transactionally."""
    identity = _runtime_identity(config_path)
    deploy.ensure_game_stopped()
    root, target = _target(mod_parent, config_path)
    if not target.exists():
        if _full_active(root, identity):
            raise ValueError('Active full campaign has no owned installation')
        return {'installed':False, 'active':False, 'removed':False,
                'files_deleted':0, 'retained_at':None}
    _, receipt, _ = _owned(target)
    deactivated = None
    if receipt['activation_modified']:
        deactivated = deactivate_full(root, config_path)
    elif _full_active(root, identity):
        raise ValueError('Full campaign activation is not managed')
    retired = rollback_full(root, config_path)
    status = status_full(config_path, root)
    if status['installed'] or status['active'] or target.exists():
        raise ValueError('Full uninstall postcondition failed')
    return {'installed':False, 'active':False, 'removed':True,
            'files_deleted':retired['files_deleted'], 'retained_at':retired['retained_at'],
            'bundle_id':retired['bundle_id'], 'deactivated':deactivated}


def install_complete_full(bundle, config_path, mod_parent=None):
    """Install and activate one complete immutable bundle; never overlays a directory."""
    plan = plan_full_install(bundle, config_path, mod_parent)
    installed = install_full(bundle, config_path, mod_parent)
    activated = activate_full(mod_parent, config_path)
    status = status_full(config_path, mod_parent)
    if (not status['installed'] or not status['active'] or not status['owned']
            or not status['integrity_verified'] or status['bundle_id'] != plan['bundle_id']):
        raise ValueError('Full install postcondition failed')
    return {'plan':plan, 'install':installed, 'activate':activated, 'status':status}


def reinstall_full(bundle, config_path, mod_parent=None):
    """Prevalidate, fully uninstall, then install the complete requested bundle."""
    # This must succeed before the current installation is touched.
    manifest, _ = verify_full_bundle(bundle, config_path)
    if manifest['framework_sha256'] != framework_fingerprint():
        raise ValueError('Framework changed since the full bundle was built')
    deploy.ensure_game_stopped()
    root, target = _target(mod_parent, config_path)
    removed = uninstall_full(config_path, root) if target.exists() else None
    installed = install_complete_full(bundle, config_path, root)
    if installed['status']['bundle_id'] != manifest['bundle_id']:
        raise ValueError('Reinstall published an unexpected bundle')
    return {'operation':'full-reinstall', 'uninstall':removed,
            'install':installed, 'bundle_id':manifest['bundle_id']}
