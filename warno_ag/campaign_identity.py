"""Explicit runtime identities for independent authored campaigns."""
import re
import uuid
import hashlib
from pathlib import Path

from .archives import clone_v3, read_directory
from .cndf import decode, encode_objects, encode_strings, rebuild_sections
from .modgen_registry import authored_build_name


LEGACY_SCENARIO = 'CampagneStrat_RedLine1989'
LEGACY_GUID = '0a1f0e3c2ac272ea19b1fff29408e223'
NAMESPACE = uuid.UUID('8af2c892-8514-520c-8223-410f0fdb9496')


def campaign_identity(compiled):
    campaign = compiled['campaign']
    identifier = campaign['id']
    if not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]*', identifier) is None:
        raise ValueError('Invalid authored campaign identity')
    if identifier == 'red_line_demo':
        return {'scenario': LEGACY_SCENARIO, 'guid': LEGACY_GUID,
                'mod_name': 'WarnoAGFRedLine1989', 'display_name': 'AG Framework - Red Line 1989'}
    suffix = 'AGF' + hashlib.sha256(identifier.encode('ascii')).hexdigest()[:8]
    local_digest = hashlib.sha256(('agf-local-mod-v1:' + identifier).encode('ascii')).digest()
    local_mod_id = (1 << 52) | (int.from_bytes(local_digest[:8], 'big') & ((1 << 52) - 1))
    return {'scenario': 'CampagneStrat_' + suffix,
            'guid': uuid.uuid5(NAMESPACE, identifier).hex,
            'mod_name': 'WarnoAGF_' + identifier,
            'local_mod_id': local_mod_id,
            'display_name': 'AG Framework - ' + campaign['title']['en']}


def isolate_definition_identity(raw, compiled):
    identity = campaign_identity(compiled)
    if identity['scenario'] == LEGACY_SCENARIO:
        return raw
    header, entries, _ = read_directory(raw)
    replacements = {}
    guid_count = 0
    for entry in entries:
        payload = raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size]
        document, graph = decode(payload)
        sections = {}
        tables = {}
        for table, section in (('strings', 'STRG'), ('translations', 'TRAN')):
            values = [value.replace(LEGACY_SCENARIO, identity['scenario']) for value in graph[table]]
            tables[table] = values
            if values != graph[table]:
                sections[section] = encode_strings(values)
        changed = False
        for obj in graph['objects']:
            for prop in obj['properties']:
                changed = _remap_bootstrap_value(prop['value'], compiled) or changed
            if obj['class'] not in {'TStrategicMapInfo', 'TScenarioLoadInfo'}:
                continue
            if obj['class'] == 'TScenarioLoadInfo' and 'strategic_map' in compiled['adapter']:
                roots = [prop['value'] for prop in obj['properties']
                         if prop['property_name'] == 'RootDatapackName']
                if len(roots) != 1:
                    raise ValueError('ScenarioInfo lacks one strategic map root')
                map_name = compiled['adapter']['strategic_map']['map_name']
                if map_name not in tables['strings']:
                    tables['strings'].append(map_name)
                    sections['STRG'] = encode_strings(tables['strings'])
                roots[0]['index'] = tables['strings'].index(map_name)
                roots[0]['value'] = map_name
                changed = True
            fields = [prop['value'] for prop in obj['properties'] if prop['property_name'] == 'GUID']
            if len(fields) != 1 or fields[0].get('value_hex') != LEGACY_GUID:
                raise ValueError('Authored identity source GUID mismatch')
            fields[0]['value_hex'] = identity['guid']
            guid_count += 1
            changed = True
        if changed:
            sections['OBJE'] = encode_objects(graph['objects'])
        if sections:
            replacements[entry.path] = rebuild_sections(document, sections)
    if guid_count != 2:
        raise ValueError('Authored identity requires map and scenario GUIDs')
    renames = {entry.path: entry.path.replace(LEGACY_SCENARIO, identity['scenario']) for entry in entries}
    return clone_v3(raw, replacements, renames)


def _bootstrap_key(key, compiled):
    from .bruderkrieg import authored_text_key
    return authored_text_key(compiled['campaign']['id'], 'bootstrap', key.hex()) if key[:4] == b'RDLN' else key


def definition_identity_contract(raw, compiled):
    identity = campaign_identity(compiled)
    header, entries, _ = read_directory(raw)
    expected = {f"NDF/Scenarios/{kind}/{identity['scenario']}.{suffix}"
                for kind in ('GDScript', 'MapConfiguration', 'ScenarioInfo', 'ScenarioLoader', 'Trophy')
                for suffix in ('ndfbin', 'tag')}
    if {entry.path for entry in entries} != expected:
        raise ValueError('Authored identity resource set mismatch')
    guid_count = 0
    strings = set()
    for entry in entries:
        _, graph = decode(raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size])
        strings.update(graph['strings'])
        for obj in graph['objects']:
            if obj['class'] in {'TStrategicMapInfo', 'TScenarioLoadInfo'}:
                values = [prop['value'].get('value_hex') for prop in obj['properties'] if prop['property_name'] == 'GUID']
                if values != [identity['guid']]:
                    raise ValueError('Authored identity GUID mismatch')
                guid_count += 1
    required = {f"Scenarios/{identity['scenario']}_Details.dat",
                f"ScenariosData:/Localisation/{identity['scenario']}/TROPHIES.csv",
                f"ScenariosData:/Localisation/{identity['scenario']}/Scripting/Dialog.csv",
                f"ScenariosData:/Localisation/{identity['scenario']}/Scripting/Localization.csv"}
    if guid_count != 2 or not required <= strings:
        raise ValueError('Authored identity loader dependencies mismatch')
    if identity['scenario'] != LEGACY_SCENARIO and any(LEGACY_SCENARIO in value for value in strings):
        raise ValueError('Authored identity retains RedLine resource reference')
    if 'strategic_map' in compiled['adapter']:
        expected_map = compiled['adapter']['strategic_map']['map_name']
        roots = []
        for entry in entries:
            payload = raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size]
            _, graph = decode(payload)
            roots.extend(prop['value'].get('value') for obj in graph['objects']
                         if obj['class'] == 'TScenarioLoadInfo' for prop in obj['properties']
                         if prop['property_name'] == 'RootDatapackName')
        if roots != [expected_map]:
            raise ValueError('Authored definition strategic map root mismatch')
    return identity


def _remap_bootstrap_value(value, compiled):
    changed = False
    if isinstance(value, dict):
        if value.get('type') == 'loc_hash':
            key = bytes.fromhex(value['value_hex'])
            replacement = _bootstrap_key(key, compiled)
            changed = key != replacement
            value['value_hex'] = replacement.hex()
        for nested in value.values():
            changed = _remap_bootstrap_value(nested, compiled) or changed
    elif isinstance(value, list):
        for nested in value:
            changed = _remap_bootstrap_value(nested, compiled) or changed
    return changed


def isolate_candidate_identity(root, compiled):
    from .full_campaign import _pack_trad, _trad_data
    from .modconfig import scenario_config
    root = Path(root).resolve()
    identity = campaign_identity(compiled)
    if identity['scenario'] == LEGACY_SCENARIO:
        return
    registry_folder = root / 'Gen/NDF/Localisation'
    registry_relative = ('Gen/NDF/Localisation/' + authored_build_name(root) + '.ndfbin'
                         if any(registry_folder.glob('*.ndfbin')) else None)
    files = sorted(path for path in root.rglob('*') if path.is_file())
    outputs = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        target = root / relative.replace(LEGACY_SCENARIO, identity['scenario'])
        if target in outputs or (target != path and target.exists()):
            raise ValueError('Authored identity file collision: ' + str(target))
        raw = path.read_bytes()
        if relative == f'Scenarios/{LEGACY_SCENARIO}_Definition.dat':
            raw = isolate_definition_identity(raw, compiled)
        elif path.suffix == '.dic':
            values = _trad_data(raw)
            remapped = {_bootstrap_key(key, compiled): text for key, text in values.items()}
            if len(remapped) != len(values):
                raise ValueError('Authored bootstrap dictionary collision')
            raw = _pack_trad(remapped)
        elif relative == 'Gen/DeclaredFiles.txt':
            raw = raw.decode('utf-8').replace(LEGACY_SCENARIO, identity['scenario']).encode('utf-8')
        elif relative == registry_relative:
            document, graph = decode(raw)
            strings = [value.replace(LEGACY_SCENARIO, identity['scenario'])
                       for value in graph['strings']]
            if strings == graph['strings']:
                raise ValueError('Authored localisation registry lacks legacy scenario sources')
            raw = rebuild_sections(document, {'STRG': encode_strings(strings)})
        elif relative == 'Config.ini':
            raw = scenario_config(raw, identity['display_name'], local_mod_id=identity['local_mod_id'])
        outputs[target] = (path, raw)
    for target, (source, raw) in outputs.items():
        source.write_bytes(raw)
        if target != source:
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    if registry_relative is not None and (root / registry_relative).is_file():
        from .registry_localisation import validate_registry_localisation
        validate_registry_localisation(root)
