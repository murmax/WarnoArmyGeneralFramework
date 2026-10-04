"""Build an experimental registration mod without running WARNO's mod compiler."""
import json
from pathlib import Path
import re

from .archives import read_directory
from .campaign import compose_modules
from .cndf import decode
from .modules import assemble_module
from .storage import sha256


ROOT = Path(__file__).resolve().parents[1]
MOD_NAME = 'WarnoAGFRegistrationMVP'
DISPLAY_NAME = 'AG Framework - Registration MVP'
SCENARIO = 'CampagneStrat_AGFramework'
ARCHIVE = f'Scenarios/{SCENARIO}_Definition.dat'


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def relative_name(value):
    # Windows rejects/aliases additional names that PurePath alone accepts.
    if not isinstance(value, str) or not value or '\\' in value:
        raise ValueError('Expected a portable relative path')
    for part in value.split('/'):
        if (not re.fullmatch(r'[A-Za-z0-9_@.-]+', part) or part in ('.', '..')
                or part.endswith(('.', ' '))
                or part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                    *('COM'+str(i) for i in range(10)), *('LPT'+str(i) for i in range(10))}):
            raise ValueError('Unsafe relative path')
    return value


def fingerprint(path):
    import hashlib
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def framework_fingerprint():
    return sha256(json_bytes({p.relative_to(ROOT).as_posix(): fingerprint(p)
                            for p in sorted((ROOT/'warno_ag').rglob('*.py'))}))


def registration_contract(raw):
    header, entries, _ = read_directory(raw)
    kinds = ('GDScript', 'MapConfiguration', 'ScenarioInfo', 'ScenarioLoader', 'Trophy')
    expected = {f'NDF/Scenarios/{kind}/{SCENARIO}.{ext}'
                for kind in kinds for ext in ('ndfbin', 'tag')}
    if {e.path for e in entries} != expected:
        raise ValueError('Unexpected registration resource set')
    graphs = {e.path: decode(raw[header.file_offset+e.offset:
                               header.file_offset+e.offset+e.size])[1] for e in entries}
    def graph(kind):
        return graphs[f'NDF/Scenarios/{kind}/{SCENARIO}.ndfbin']
    def properties(kind, cls):
        objects = [o for o in graph(kind)['objects'] if o['class'] == cls]
        if len(objects) != 1:
            raise ValueError('Missing or ambiguous registration owner')
        return {p['property_name']: p['value'] for p in objects[0]['properties']}
    info = properties('ScenarioInfo', 'TScenarioLoadInfo')
    map_info = properties('MapConfiguration', 'TStrategicMapInfo')
    guid = '0a1f0e3c2ac272ea19b1fff29408e223'
    if (info['GUID']['value_hex'] != guid or map_info['GUID']['value_hex'] != guid
            or info['Name']['value'] != SCENARIO or info['Path']['value'] != SCENARIO
            or map_info['OrderToChainMission']['value'] != 120):
        raise ValueError('Registration identity mismatch')
    if set(graph('ScenarioInfo')['exports'].values()) != {f'$/ScenarioInfo/{SCENARIO}'}:
        raise ValueError('ScenarioInfo export mismatch')
    if set(graph('ScenarioLoader')['exports'].values()) != {
            f'$/ClusterMap/{SCENARIO}'+suffix for suffix in ('', '/Load', '/MapDico', '/MapDialogDico')}:
        raise ValueError('ScenarioLoader export mismatch')
    mount = properties('ScenarioLoader', 'TClusterMountAdditionalDatapack')
    details = 'Scenarios/CampagneStrat_Bruderkrieg_Details.dat'
    if mount['DatapackFileName']['value'] != details:
        raise ValueError('Unexpected shared Details dependency')
    trophies = [p['value']['value'] for o in graph('Trophy')['objects'] for p in o['properties']
                if p['property_name'] in ('Id', 'ObjectiveId')]
    if trophies != [9250, 9250, 9251, 9251]:
        raise ValueError('Unexpected trophy identities')
    for kind in kinds:
        tag = graphs[f'NDF/Scenarios/{kind}/{SCENARIO}.tag']
        if f'Scenarios/{kind}/{SCENARIO}' not in tag['strings']:
            raise ValueError('Tag file-list mismatch')
    return {'scenario': SCENARIO, 'guid': guid, 'order': 120, 'shared_details': details,
            'shared_title': 'Bruderkrieg', 'resource_count': len(entries)}


def _tour_max(raw):
    header, entries, _ = read_directory(raw)
    entry, = [e for e in entries if e.path == f'NDF/Scenarios/GDScript/{SCENARIO}.ndfbin']
    graph = decode(raw[header.file_offset+entry.offset:header.file_offset+entry.offset+entry.size])[1]
    index, = [index for index, name in graph['exports'].items()
              if name == '$/GDScript/intro/script/Variables/TourMax']
    obj = graph['objects'][index]
    if obj['class'] != 'TGDVariableInteger':
        raise ValueError('TourMax export class changed')
    value, = [p['value']['value'] for p in obj['properties'] if p['property_name'] == 'Value']
    if type(value) is not int:
        raise ValueError('TourMax value type changed')
    return value


def assemble_trial(profile_path):
    profile_path = Path(profile_path).resolve()
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    allowed = {'schema', 'module', 'overlays', 'game_root', 'game_files', 'instructions'}
    required = {'schema', 'module', 'game_root', 'game_files', 'instructions'}
    if (not isinstance(profile, dict) or not required <= set(profile) <= allowed
            or type(profile['schema']) is not int or profile['schema'] != 1):
        raise ValueError('Invalid trial profile')
    module_path = profile_path.parent / relative_name(profile['module'])
    module = json.loads(module_path.read_text(encoding='utf-8'))
    overlays = profile.get('overlays', [])
    if (not isinstance(overlays, list) or not overlays or any(
            not isinstance(name, str) for name in overlays) or len(set(overlays)) != len(overlays)):
        if overlays != []:
            raise ValueError('Invalid trial overlays')
    if overlays:
        overlay_modules = [json.loads((profile_path.parent/relative_name(name)).read_text(encoding='utf-8'))
                           for name in overlays]
        module = compose_modules([module, *overlay_modules], 'definition-mvp')
    game_root = Path(profile['game_root']).resolve()
    game_files = profile['game_files']
    if not isinstance(game_files, dict) or 'WARNO.exe' not in game_files:
        raise ValueError('Trial needs pinned game files')
    for name, digest in game_files.items():
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid game fingerprint')
        if fingerprint(game_root / relative_name(name)) != digest:
            raise ValueError(f'Game fingerprint mismatch: {name}')
    source = Path(module['source_pack']).resolve()
    source_name = source.relative_to(game_root).as_posix()
    if game_files.get(source_name) != module['source_sha256']:
        raise ValueError('Module source is not pinned by the trial profile')
    if 'Data/PC/169425/Scenarios/CampagneStrat_Bruderkrieg_Details.dat' not in game_files:
        raise ValueError('Shared Details dependency is not pinned')
    if (module.get('output_name') != ARCHIVE.split('/')[-1]
            or any(r['backend'] not in ({'campaign-identity', 'native'} if overlays else
                                        {'campaign-identity'}) for r in module['resources'])):
        raise ValueError('This adapter supports registration-only identity changes')
    output, report = assemble_module(module)
    contract = registration_contract(output)
    # Registration-only must preserve every byte of the gameplay graph.
    def gdscript(raw):
        h, es, _ = read_directory(raw)
        e, = [e for e in es if '/GDScript/' in e.path and e.path.endswith('.ndfbin')]
        return raw[h.file_offset+e.offset:h.file_offset+e.offset+e.size]
    if not overlays and gdscript(source.read_bytes()) != gdscript(output):
        raise ValueError('Registration-only changed the gameplay graph')
    if overlays:
        # This initial gameplay trial intentionally exposes one observable,
        # type-checked variable. No opaque general "modified" claim is made.
        if overlays != ['modules/turn-limit.json'] or _tour_max(output) != 3:
            raise ValueError('Unsupported or incorrectly assembled gameplay trial')
        contract = {**contract, 'tour_max': 3}
    config = (f'[Properties]\nName = {DISPLAY_NAME}\n'
              f'Description = {"Turn-limit MVP clone" if overlays else "Experimental registration-only Bruderkrieg clone"}; runtime not verified.\n'
              'PreviewImagePath = \nVersion = 1\nTagList = Gameplay,Scenarios\n'
              'CosmeticOnly = 0\nDeckFormatVersion = 1\n').encode('utf-8')
    payload = {'Config.ini': config, ARCHIVE: output}
    files = {f'payload/{MOD_NAME}/{name}': value for name, value in payload.items()}
    files.update({'module.json': json_bytes(module), 'build-report.json': json_bytes(report),
                  'TESTING.md': (profile_path.parent/relative_name(profile['instructions'])).read_bytes()})
    manifest = {'schema': 1, 'adapter': 'definition-mvp-v1' if overlays else 'registration-only-v1', 'mod_name': MOD_NAME,
                'framework_sha256': framework_fingerprint(), 'game_files': game_files,
                'files': {name: sha256(data) for name, data in files.items()},
                'payload': {name: sha256(data) for name, data in payload.items()},
                'contract': contract, 'package_prepared': True,
                'runtime_verified': False, 'ready': False,
                'status': 'experimental-runtime-candidate',
                'activation': 'manual-mod-center',
                'limitations': ['Current engine discovery and load precedence are unverified',
                    'Original map, Details, localisation and media are shared',
                    'Only EXE, source Definition and shared Details are fingerprinted; not the whole game',
                    'Requires local base game; do not redistribute game-derived payloads']}
    manifest['bundle_id'] = sha256(json_bytes(manifest))
    return files, manifest


def write_trial(profile_path):
    from .deployment import plain_path, verify_bundle
    files, manifest = assemble_trial(profile_path)
    root = plain_path(ROOT/'artifacts'/'trials')
    target = root / ('registration-only-'+manifest['bundle_id'][:16])
    target.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        path = target/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
    with (target/'bundle.json').open('xb') as stream:
        stream.write(json_bytes(manifest))
    verify_bundle(target)
    return target
