"""Assemble complete native campaign candidates with verified source compatibility."""
import base64
import json
import hashlib
from pathlib import Path
import re
import struct
import tempfile

from .archives import read_directory, repack
from .cndf import decode
from .full_campaign import _pack_trad, _trad_data
from .game_resources import GameResources, _revision
from .modconfig import _parse, scenario_config, validate_scenario_config
from .native_campaign_clone import verify_native_definition_clone
from .native_editor_build import build_native_editor_artifacts
from .native_frozen import verify_native_frozen
from .native_frozen import native_spawn_identity
from .storage import safe_child, sha256


def _dictionary_semantic_hash(values):
    return sha256(json.dumps(sorted((key.hex(), value) for key, value in values.items()),
                             ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _unpack(raw):
    repack(raw, {})
    header, entries, _ = read_directory(raw)
    return {entry.path: raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size] for entry in entries}


def assemble_native_candidate(artifacts, template, destination):
    artifacts, template, destination = (Path(path).resolve() for path in (artifacts, template, destination))
    if destination.exists():
        raise FileExistsError(destination)
    compiled = json.loads((artifacts / 'native-campaign.compiled.json').read_text(encoding='utf-8'))
    build = json.loads((artifacts / 'native-build-report.json').read_text(encoding='utf-8'))
    snapshot = Path(compiled['snapshot'])
    manifest = json.loads((snapshot / 'native-source.json').read_text(encoding='utf-8'))
    sources = {(entry['scope'], entry['path']): entry for entry in manifest['resources']}
    def source(scope, path):
        entry = sources[scope, path]
        raw = safe_child(snapshot, entry['file']).read_bytes()
        if sha256(raw) != entry['sha256']:
            raise ValueError('Native source resource changed before packaging')
        return raw
    template_report = json.loads((template / 'compiler-template.json').read_text(encoding='utf-8'))
    if template_report.get('format') != 'agf-native-compiler-template/v1':
        raise ValueError('Native packaging requires verified official compiler output')
    files = {}
    for name, digest in template_report['files'].items():
        raw = safe_child(template, name).read_bytes()
        if sha256(raw) != digest:
            raise ValueError('Official native compiler output changed: ' + name)
        files[name] = raw
    for name, digest in build['files'].items():
        raw = safe_child(artifacts, name).read_bytes()
        if sha256(raw) != digest:
            raise ValueError('Native build artifact changed: ' + name)
        files[name] = raw
    # Probe objects remain confined to the official compiler workspace.
    for name in list(files):
        if name.startswith('Gen/NDF/') and ('shared_definitions', name.removeprefix('Gen/')) in sources and name not in build['files']:
            files[name] = source('shared_definitions', name.removeprefix('Gen/'))
    identity = compiled['identity']
    config = scenario_config(files['Config.ini'], identity['display_name'], local_mod_id=identity['local_mod_id'])
    compatibility = dict(_parse(config)['Config'])
    proof_used = {}
    needed_clusters = {name.removeprefix('Gen/NDF/').removesuffix('.ndfbin')
                       for name in build['files'] if name.startswith('Gen/NDF/') and name.endswith('.ndfbin')}
    for cluster in sorted(needed_clusters - compatibility.keys()):
        proof = template_report.get('compatibility_proofs', {}).get(cluster)
        if not isinstance(proof, dict) or set(proof) != {'file', 'sha256'}:
            raise ValueError('Official compiler output lacks required compatibility cluster: Gen/NDF/' + cluster + '.ndfbin')
        proof_file = safe_child(template, proof['file'])
        proof_raw = proof_file.read_bytes()
        if sha256(proof_raw) != proof['sha256']:
            raise ValueError('Official compatibility proof changed: ' + cluster)
        from_proof = _parse(proof_raw)
        if from_proof['Properties'].get('ModGenVersion') != _parse(config)['Properties'].get('ModGenVersion'):
            raise ValueError('Official compatibility proof uses another ModGen revision: ' + cluster)
        digest = from_proof['Config'].get(cluster)
        original = source('shared_definitions', 'NDF/' + cluster + '.ndfbin')
        if digest is None or hashlib.md5(original).hexdigest() != digest:
            raise ValueError('Official compatibility proof differs from captured game: ' + cluster)
        config += (cluster + '=' + digest + '\r\n').encode('ascii')
        compatibility[cluster] = digest
        proof_used[cluster] = {'sha256': proof['sha256'], 'md5': digest}
    validate_scenario_config(config, identity['display_name'], local_mod_id=identity['local_mod_id'])
    for cluster, digest in compatibility.items():
        original = source('shared_definitions', 'NDF/' + cluster + '.ndfbin')
        if hashlib.md5(original).hexdigest() != digest:
            raise ValueError('Official compatibility hash differs from captured game: ' + cluster)
    files['Config.ini'] = config
    original_scenario, target = compiled['original_scenario'], identity['scenario']
    game = GameResources(manifest['game_root'])
    declared = set(files.get('Gen/DeclaredFiles.txt', b'').decode('utf-8-sig').splitlines())
    declared.update('ZZ:/' + name.removeprefix('Gen/') for name in build['files'] if name.startswith('Gen/PC/Texture/'))
    source_assets = {}
    for (scope, path), entry in sources.items():
        if scope != 'scenario_assets' or path.endswith('.xyz'):
            continue
        canonical = path.removeprefix('AllPlatforms/')
        previous = source_assets.get(canonical)
        rank = _revision(Path(entry['origin']['archive']), game.data_root)
        if previous is None or rank > previous[0]:
            source_assets[canonical] = (rank, entry)

    def publish_asset(relative, raw):
        files['Gen/' + relative] = raw
        declared.add('ZZ:/' + relative)
        if relative.startswith('Localisation/') and relative.endswith('.dic'):
            files['Gen/AllPlatforms/' + relative] = raw
            match = re.fullmatch(r'Localisation/(.+)-([A-Z]+)\.dic', relative)
            if match:
                files['Gen/AllPlatforms/Localisation/' + match[2] + '/' + match[1] + '.dic'] = raw

    for canonical, (_, entry) in source_assets.items():
        publish_asset(canonical.replace(original_scenario, target), source('scenario_assets', entry['path']))
    event_dictionary_proofs = []
    if build.get('private_event_text'):
        prefix = 'Gen/Localisation/' + target + '/Scripting/Dialog-'
        available = set()
        for path in sorted(list(files)):
            if not path.startswith(prefix) or not path.endswith('.dic'):
                continue
            language = path[len(prefix):-4]
            if not re.fullmatch(r'[A-Z]+', language):
                raise ValueError('Unexpected native scenario Dialog dictionary path')
            available.add(language)
            original_raw = files[path]
            values = _trad_data(original_raw)
            original_values = dict(values)
            added = {}
            for key, localized in build['private_event_text'].items():
                raw_key = bytes.fromhex(key)
                if raw_key in values:
                    raise ValueError('Private native event text collides with a source Dialog key')
                text = localized['ru' if language == 'RU' else 'en']
                values[raw_key] = text
                added[key] = text
            publish_asset(path.removeprefix('Gen/'), _pack_trad(values))
            event_dictionary_proofs.append({'path': path,
                'source_semantic_sha256': _dictionary_semantic_hash(original_values),
                'added': added})
        if not {'RU', 'US'} <= available:
            raise ValueError('Source scenario has no Russian and English Dialog dictionaries')
    production_dictionary_proofs = []
    if build.get('private_production_text'):
        prefix = 'Gen/Localisation/' + target + '/Scripting/Localization-'
        available = set()
        for path in sorted(list(files)):
            if not path.startswith(prefix) or not path.endswith('.dic'):
                continue
            language = path[len(prefix):-4]
            if not re.fullmatch(r'[A-Z]+', language):
                raise ValueError('Unexpected native production localization path')
            available.add(language)
            values = _trad_data(files[path])
            original_values = dict(values)
            added = {}
            for key, localized in build['private_production_text'].items():
                raw_key = bytes.fromhex(key)
                if raw_key in values:
                    raise ValueError('Private native production text collides with source localization')
                text = localized['ru' if language == 'RU' else 'en']
                values[raw_key] = text
                added[key] = text
            publish_asset(path.removeprefix('Gen/'), _pack_trad(values))
            production_dictionary_proofs.append({'path': path,
                'source_semantic_sha256': _dictionary_semantic_hash(original_values),
                'added': added})
        if not {'RU', 'US'} <= available:
            raise ValueError('Source scenario has no Russian and English production dictionaries')
    for (scope, path), entry in sources.items():
        if scope != 'scenario_gamedata':
            continue
        renamed = path.replace(original_scenario, target)
        raw = source(scope, path)
        files['GameData/' + renamed] = raw
        prefix = 'Map/Scenario/' + target + '/'
        if renamed.startswith(prefix):
            files['ScenariosData/' + target + '/' + renamed[len(prefix):]] = raw
    dictionaries = {}
    for entry in game.shared().entries:
        path = entry.path.removeprefix('AllPlatforms/')
        if not re.search(r'/Core/(MAPS|UNITS|COMPANIES|PLATOONS|INTERFACE_INGAME)-[A-Z]+\.dic$', path):
            continue
        previous = dictionaries.get(path)
        if previous is None or _revision(entry.archive, game.data_root) > _revision(previous.archive, game.data_root):
            dictionaries[path] = entry
    dictionary_proofs = []
    for path, entry in dictionaries.items():
        before_raw = entry.read()
        before = _trad_data(before_raw)
        after = dict(before)
        additions = {bytes.fromhex(key): value for key, value in build['private_text'].items()}
        language = 'ru' if path.endswith('-RU.dic') else 'en'
        additions.update({bytes.fromhex(key): text[language]
                          for key, text in build.get('private_localized_text', {}).items()})
        if '/Core/MAPS-' in path:
            additions.update({bytes.fromhex(key): text[language]
                              for key, text in build.get('private_label_text', {}).items()})
        if '/Core/INTERFACE_INGAME-' in path:
            additions.update({bytes.fromhex(key): text[language]
                              for key, text in build.get('private_choice_text', {}).items()})
        if build['campaign_title']:
            title = build['campaign_title']
            additions[bytes.fromhex(title['target_key'])] = title['text']['ru' if path.endswith('-RU.dic') else 'en']
        for key, value in additions.items():
            if key in before:
                raise ValueError('Private native localization key collides with game text')
            after[key] = value
        raw = _pack_trad(after)
        decoded = _trad_data(raw)
        if any(decoded.get(key) != value for key, value in before.items()):
            raise ValueError('Native campaign changes original game localization')
        publish_asset(path, raw)
        dictionary_proofs.append({'path': 'Gen/' + path, 'source_sha256': sha256(before_raw),
                                  'source_semantic_sha256': _dictionary_semantic_hash(before),
                                  'added': {key.hex(): value for key, value in additions.items()}})
    if build['campaign_title'] and not any('/Core/MAPS-' in row['path'] for row in dictionary_proofs):
        raise ValueError('Native campaign title has no early MAPS dictionary provider')
    files['Gen/DeclaredFiles.txt'] = ('\n'.join(sorted(declared)) + '\n').encode('utf-8')
    config_record = {'format': 'native-campaign-v1', 'identity': identity, 'source_scenario': original_scenario,
                     'definition_reference': build['definition_reference'], 'definition_clone': build['definition_clone'],
                     'details_resources': build['details_resources'], 'compatibility': compatibility,
                     'compatibility_proofs': proof_used,
                     'frozen_deployments': build.get('frozen_deployments', []),
                     'camp_by_side': compiled.get('camp_by_side'),
                     'added_placements': compiled.get('added_placements', []),
                     'frozen_verification': build.get('frozen_verification'),
                     'playable_polygon_verification': build.get('playable_polygon_verification'),
                     'event_text_edits': compiled.get('event_text_edits', []),
                     'production_position_edits': build.get('production_position_edits', []),
                     'reinforcement_creations': build.get('created_reinforcement_groups', []),
                     'turn_event_creations': build.get('created_turn_events', []),
                     'production_creations': build.get('created_production_groups', []),
                     'production_dictionaries': production_dictionary_proofs,
                     'ai_target_edits': compiled.get('ai_target_edits', []),
                     'ai_order_creations': build.get('created_ai_orders', []),
                     'event_dictionaries': event_dictionary_proofs,
                     'dictionaries': dictionary_proofs, 'state': compiled['state'],
                     'world': build.get('world'),
                     'source_manifest_sha256': compiled['source_manifest_sha256'], 'runtime_verified': False,
                     'files': {name: sha256(raw) for name, raw in files.items()}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-candidate-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'candidate'
        staged.mkdir()
        for name, raw in files.items():
            path = safe_child(staged, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        validate_native_candidate(staged, config_record)
        staged.rename(destination)
    return config_record


def validate_native_candidate(root, config):
    root = Path(root).resolve()
    if config.get('format') != 'native-campaign-v1':
        raise ValueError('Unsupported native campaign package contract')
    identity = config['identity']
    files = {path.relative_to(root).as_posix(): path for path in root.rglob('*') if path.is_file()}
    hashes = {name: sha256(path.read_bytes()) for name, path in files.items()}
    if hashes != config['files']:
        raise ValueError('Native candidate file inventory or hash mismatch')
    parsed = validate_scenario_config((root / 'Config.ini').read_bytes(), identity['display_name'], local_mod_id=identity['local_mod_id'])
    if dict(parsed['Config']) != config['compatibility']:
        raise ValueError('Native candidate compatibility records changed')
    reference = {name: base64.b64decode(raw, validate=True) for name, raw in config['definition_reference'].items()}
    definition_path = root / 'Scenarios' / (identity['scenario'] + '_Definition.dat')
    verified = verify_native_definition_clone(reference, definition_path.read_bytes(), config['definition_clone'])
    details = _unpack((root / 'Scenarios' / (identity['scenario'] + '_Details.dat')).read_bytes())
    if {name: sha256(raw) for name, raw in details.items()} != config['details_resources']:
        raise ValueError('Native candidate map/scenario details changed')
    if config.get('added_placements'):
        mapping = config.get('camp_by_side')
        if not isinstance(mapping, dict) or set(mapping) != {'nato', 'pact'} or set(mapping.values()) != {0, 1}:
            raise ValueError('Native candidate lacks its verified coalition camp mapping')
        _, level = decode(details['out/LevelDesign.ndfbin'])
        spawns = {}
        for obj in level['objects']:
            if obj['class'] == 'TGameDesignAddOn_Spawn':
                props = {row['property_name']: row['value'] for row in obj['properties']}
                spawns.setdefault(props['Name']['value'], []).append(props)
        for deployment in config['added_placements']:
            identity_tag = native_spawn_identity(identity['scenario'], deployment['id'])
            matched = spawns.get(identity_tag['name'], [])
            camp = mapping[deployment['side']]
            if (len(matched) != 1 or matched[0]['Ranking']['value'] != 'Camp_' + str(camp)
                    or matched[0].get('Camp', {}).get('value', camp) != camp
                    or matched[0]['GUID']['value_hex'] != identity_tag['guid']):
                raise ValueError('Native candidate new battalion uses the wrong coalition camp')
    if config.get('playable_polygon_verification') is not None:
        from .native_playable import read_playable_polygons

        proof = config['playable_polygon_verification']
        expected = [[[float(point[key]) for key in ('x', 'y')] for point in polygon]
                    for polygon in config['state']['playable_polygons']]
        for path in ('PlayableZone/Areas.ndfbin', 'out/PlayableZone.ndfbin'):
            if (sha256(details[path]) != proof['after'][path]
                    or read_playable_polygons(details[path]) != expected):
                raise ValueError('Native candidate playable zone differs from edited vertices')
    if config.get('frozen_deployments'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        proof = verify_native_frozen(definition[path], details['out/LevelDesign.ndfbin'],
                                     config['frozen_deployments'])
        if proof != config.get('frozen_verification'):
            raise ValueError('Native candidate frozen lifecycle proof changed')
    if config.get('world') is not None:
        from .native_world import verify_native_world_payload
        verify_native_world_payload(root, config['world'])
        definition = _unpack(definition_path.read_bytes())
        _, info = decode(definition['NDF/Scenarios/ScenarioInfo/' + identity['scenario'] + '.ndfbin'])
        roots = [prop['value'].get('value') for obj in info['objects'] if obj['class'] == 'TScenarioLoadInfo'
                 for prop in obj['properties'] if prop['property_name'] == 'RootDatapackName']
        if roots != [config['world']['map_name']]:
            raise ValueError('Native scenario does not mount the rebuilt private world')
    for name in files:
        if name.startswith('Gen/NDF/') and name.endswith(('.ndfbin', '.tag')):
            decode(files[name].read_bytes())
        if name.endswith('.xyz'):
            raise ValueError('Native candidate contains an alternate Python script provider')
    declared = set((root / 'Gen/DeclaredFiles.txt').read_text(encoding='utf-8-sig').splitlines())
    for dictionary in config['dictionaries']:
        if 'source_semantic_sha256' not in dictionary:
            raise ValueError('Native package predates original-text preservation verification; rebuild the package')
        values = _trad_data((root / dictionary['path']).read_bytes())
        if any(values.get(bytes.fromhex(key)) != text for key, text in dictionary['added'].items()):
            raise ValueError('Native candidate localization binding mismatch')
        original_values = {key: value for key, value in values.items() if key.hex() not in dictionary['added']}
        if _dictionary_semantic_hash(original_values) != dictionary['source_semantic_sha256']:
            raise ValueError('Native candidate changes original game localization')
        if 'ZZ:/' + dictionary['path'].removeprefix('Gen/') not in declared:
            raise ValueError('Native candidate localization is not declared')
    for dictionary in config.get('event_dictionaries', []):
        values = _trad_data((root / dictionary['path']).read_bytes())
        if any(values.get(bytes.fromhex(key)) != text for key, text in dictionary['added'].items()):
            raise ValueError('Native candidate event dialog text differs from its private source')
        original_values = {key: value for key, value in values.items()
                           if key.hex() not in dictionary['added']}
        if _dictionary_semantic_hash(original_values) != dictionary['source_semantic_sha256']:
            raise ValueError('Native candidate changes source event dialog text')
        if 'ZZ:/' + dictionary['path'].removeprefix('Gen/') not in declared:
            raise ValueError('Native candidate event dialog dictionary is not declared')
    for dictionary in config.get('production_dictionaries', []):
        values = _trad_data((root / dictionary['path']).read_bytes())
        if any(values.get(bytes.fromhex(key)) != text for key, text in dictionary['added'].items()):
            raise ValueError('Native candidate private production name differs from its dictionary')
        original_values = {key: value for key, value in values.items()
                           if key.hex() not in dictionary['added']}
        if _dictionary_semantic_hash(original_values) != dictionary['source_semantic_sha256']:
            raise ValueError('Native candidate changes source production localization')
        if 'ZZ:/' + dictionary['path'].removeprefix('Gen/') not in declared:
            raise ValueError('Native candidate production dictionary is not declared')
    if config.get('production_position_edits'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        for edit in config['production_position_edits']:
            group = script['objects'][edit['objectId']]
            positions = [item['value'] for item in group['properties']
                         if item['property_name'] == 'SpawnPositionsSortedByPriority']
            if (group['class'] != 'TGDStrategicReinforcementGroup'
                    or script['exports'].get(group['id']) != edit['export']
                    or len(positions) != 1 or positions[0]['type'] != 'list'
                    or [item.get('object_id') for item in positions[0]['items']]
                        != edit['afterTargetObjectIds']
                    or any(script['objects'][index]['class'] != 'TGDTagPosition'
                           for index in edit['afterTargetObjectIds'])):
                raise ValueError('Native candidate production spawn positions differ from private source')
    if config.get('reinforcement_creations'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        objects = script['objects']
        for creation in config['reinforcement_creations']:
            group = objects[creation['groupObjectId']]
            parent = objects[creation['parentActionObjectId']]
            fields = {item['property_name']: item['value'] for item in group['properties']}
            parent_fields = {item['property_name']: item['value'] for item in parent['properties']}
            expected_groups = creation['parentSourceGroups'] + [
                item['groupObjectId'] for item in config['reinforcement_creations']
                if item['parentActionObjectId'] == parent['id']]
            if (group['class'] != 'TGDStrategicReinforcementGroup'
                    or script['exports'].get(group['id']) != creation['targetExport']
                    or fields['DisplayName']['value_hex'] != creation['displayKey']
                    or fields['ShortDisplayName']['value_hex'] != creation['shortKey']
                    or [item['object_id'] for item in fields['SpawnPositionsSortedByPriority']['items']]
                        != creation.get('resolvedSpawnTargetObjectIds',
                                        creation['spawnTargetObjectIds'])
                    or any(objects[index]['class'] != 'TGDTagPosition'
                           for index in creation.get('resolvedSpawnTargetObjectIds',
                                                     creation['spawnTargetObjectIds']))
                    or parent['class'] != 'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction'
                    or parent_fields['Camp']['object_id'] != creation['campObjectId']
                    or [item['object_id'] for item in parent_fields['ReinforcementGroups']['items']]
                        != expected_groups):
                raise ValueError('Native candidate reinforcement division differs from private source chain')
            if creation.get('spawnMarkerId') is not None:
                from .native_markers import native_marker_identity

                marker = native_marker_identity(identity['scenario'], creation['spawnMarkerId'])
                marker_tag = objects[creation['spawnMarkerObjectId']]
                words = {item['property_name']: item['value'].get('value')
                         for item in marker_tag['properties']}
                actual_guid = (struct.pack('>4i', *(words['GUID' + str(number)]
                    for number in range(1, 5))).hex()
                    if all(type(words.get('GUID' + str(number))) is int
                           for number in range(1, 5)) else None)
                if (marker_tag['class'] != 'TGDTagPosition'
                        or marker['guid'] != creation['spawnMarkerGuid']
                        or script['exports'].get(marker_tag['id'])
                            != '$/GDScript/GdItems/Tags/' + marker['name']
                        or marker_tag['id'] not in creation['resolvedSpawnTargetObjectIds']
                        or actual_guid != marker['guid']):
                    raise ValueError('Native candidate reinforcement marker tag differs from its map GUID')
                _, level = decode(details['out/LevelDesign.ndfbin'])
                addons = [obj for obj in level['objects'] if obj['class'] == 'TGameDesignAddOn_Name'
                          and any(item['property_name'] == 'Name'
                                  and item['value'].get('value') == marker['name']
                                  for item in obj['properties'])]
                if len(addons) != 1 or not any(item['property_name'] == 'GUID'
                    and item['value'].get('value_hex') == marker['guid']
                    for item in addons[0]['properties']):
                    raise ValueError('Native candidate reinforcement point is absent from the new map')
                parents = [obj for obj in level['objects'] if obj['class'] == 'TGameDesignItem'
                           and any(item['property_name'] == 'AddOn'
                                   and item['value'].get('object_id') == addons[0]['id']
                                   for item in obj['properties'])]
                wanted = creation['spawnMarkerPosition']
                if (len(parents) != 1 or not any(item['property_name'] == 'Position'
                    and item['value'].get('value', [])[:2] == [wanted['x'], wanted['y']]
                    for item in parents[0]['properties'])):
                    raise ValueError('Native candidate reinforcement point position changed')
            for locale, language in (('RU', 'ru'), ('US', 'en')):
                dictionary = (root / 'Gen/Localisation' / identity['scenario'] / 'Scripting'
                              / ('Localization-' + locale + '.dic'))
                values = _trad_data(dictionary.read_bytes())
                if any(values.get(bytes.fromhex(key)) != creation['name'][language]
                       for key in (creation['displayKey'], creation['shortKey'])):
                    raise ValueError('Native candidate reinforcement division name differs from its text')
    if config.get('production_creations'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        for creation in config['production_creations']:
            group = script['objects'][creation['groupObjectId']]
            turn = script['objects'][creation['turnObjectId']]
            parent = script['objects'][creation['parentObjectId']]
            fields = {item['property_name']: item['value'] for item in group['properties']}
            parent_actions = next(item['value']['items'] for item in parent['properties']
                                  if item['property_name'] == 'SubActions')
            if (group['class'] != 'TGDDescriptorStrategicAddPossibleProduction'
                    or script['exports'].get(group['id']) != creation['targetExport']
                    or turn['class'] != 'TGDVariableInteger'
                    or script['exports'].get(turn['id']) != creation['turnExport']
                    or next(item['value']['value'] for item in turn['properties']
                            if item['property_name'] == 'Value') != creation['unlockTurn']
                    or fields['DisplayName']['value_hex'] != creation['titleKey']
                    or [item['value'] for item in fields['Pawns']['items']] != creation['pawnExports']
                    or fields['Camp']['object_id'] != creation['campObjectId']
                    or fields['ReinforcementGroup']['object_id'] != creation['reinforcementObjectId']
                    or creation.get('reinforcementGroupId') is not None and
                       creation['reinforcementObjectId'] != next((item['groupObjectId']
                           for item in config.get('reinforcement_creations', [])
                           if item['id'] == creation['reinforcementGroupId']), None)
                    or fields['UnlockAtTurnVariable']['object_id'] != turn['id']
                    or sum(item.get('object_id') == group['id'] for item in parent_actions) != 1):
                raise ValueError('Native candidate production group differs from its private source chain')
    if config.get('event_text_edits'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        for edit in config['event_text_edits']:
            obj = script['objects'][edit['objectId']]
            property_name = edit.get('propertyName', 'LocalizedText')
            keys = [prop['value'].get('value_hex') for prop in obj['properties']
                    if prop['property_name'] == property_name]
            allowed = ({'TGDDescriptorCutsceneTextComponent': {'LocalizedText'},
                        'TGDDescriptorCutsceneDialogWithMultipleChoice':
                            {'TokenBoutonChoix0', 'TokenBoutonChoix1'},
                        'TGDDescriptorCutsceneDialog': {'TokenBoutonChoix0'}})
            if property_name not in allowed.get(obj['class'], set()) or keys != [edit['targetKey']]:
                raise ValueError('Native candidate event text has no matching script binding')
    if config.get('turn_event_creations'):
        from .native_turn_events import TURN_EVENT_ADAPTERS, source_dialog_turns

        adapter = TURN_EVENT_ADAPTERS.get(config['source_scenario'])
        if adapter is None:
            raise ValueError('Native candidate turn event has no pinned source adapter')
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        objects = script['objects']
        def field(obj, name):
            return next(prop['value'] for prop in obj['properties']
                        if prop['property_name'] == name)
        source_counts = {item.get('sourceObjectCount', 2050)
                         for item in config['turn_event_creations']}
        if len(source_counts) != 1 or not 0 < next(iter(source_counts)) <= len(objects):
            raise ValueError('Native candidate turn event source object count changed')
        source_graph = {'objects': objects[:next(iter(source_counts))]}
        authored_slots = [(item['side'], item['turn']) for item in config['turn_event_creations']]
        if len(authored_slots) != len(set(authored_slots)):
            raise ValueError('Native candidate turn events share one side and turn')
        for creation in config['turn_event_creations']:
            mapping = {int(key): value for key, value in creation['objectMap'].items()}
            template = creation['templateObjectId']
            spec = adapter['sides'].get(creation.get('side'))
            if (spec is None
                    or (template, creation['parentObjectId'], creation['compareObjectId'],
                        creation['textObjectId'], creation['campObjectId'])
                        != (spec['template'], spec['parent'], spec['compare'],
                            spec['text'], spec['camp'])
                    or creation.get('synthetic', False) != spec.get('synthetic', False)
                    or creation.get('speaker', spec['speaker']) != spec['speaker']
                    or creation.get('portraitToken') != spec.get('portrait')
                    or len(mapping) != len(spec['subtree'])):
                raise ValueError('Native candidate turn event template mapping changed')
            if creation['turn'] in source_dialog_turns(source_graph,
                    adapter['turn_variable'], spec['camp']):
                raise ValueError('Native candidate turn event conflicts with a source dialog')
            source_ids = spec['subtree']
            if set(mapping) != set(source_ids) or mapping[template] != creation['sequenceObjectId']:
                raise ValueError('Native candidate turn event cloned source subtree changed')
            sequence, wait, condition = (objects[mapping[index]] for index in source_ids[:3])
            variable = objects[mapping[spec['variable']]]
            compare = objects[mapping[spec['compare']]]
            player = objects[mapping[spec['player']]]
            encapsule, play, dialog, narrative = (
                objects[mapping[index]] for index in source_ids[6:10])
            secondary = objects[mapping[source_ids[10]]] if len(source_ids) == 12 else None
            texture = objects[mapping[source_ids[11]]] if len(source_ids) == 12 else None
            parent = objects[creation['parentObjectId']]
            parent_actions = field(parent, 'SubActions')['items']
            original_actions = creation.get('parentSourceActions', spec.get('source_actions'))
            if original_actions is None:
                raise ValueError('Native candidate turn event lacks its source parent action proof')
            expected_parent_actions = original_actions + [item['sequenceObjectId']
                for item in config['turn_event_creations']
                if item['parentObjectId'] == parent['id']] + [item['sequenceObjectId']
                for item in config.get('ai_order_creations', [])
                if item['parentObjectId'] == parent['id']]
            expected_classes = ('TGDDescriptorSequential', 'TGDDescriptorWaitCondition',
                'TGDConditionAnd', 'TGDConditionVariable', 'TGDOperatorIntegerCompare',
                'TGDConditionStrategicIsPlayerTurn', 'TGDDescriptorEncapsuleCutscene',
                'TGDDescriptorCutscenePlayDialogList', 'TGDDescriptorCutsceneDialog',
                'TGDDescriptorCutsceneTextComponent')
            actual_objects = (sequence, wait, condition, variable,
                compare, player, encapsule, play, dialog, narrative)
            if secondary is not None:
                actual_objects += (secondary, texture)
                expected_classes += ('TGDDescriptorCutsceneTextComponent',
                                     'TGDDescriptorCutsceneTextureComponent')
            expected_texts = [narrative['id']] + ([secondary['id']] if secondary else [])
            if (tuple(obj['class'] for obj in actual_objects) != expected_classes
                    or parent['class'] != 'TGDDescriptorSimultaneous'
                    or script['exports'].get(sequence['id']) != creation['sequenceExport']
                    or [item['object_id'] for item in parent_actions] != expected_parent_actions
                    or [item['object_id'] for item in field(sequence, 'SubActions')['items']]
                        != [wait['id'], encapsule['id']]
                    or field(wait, 'Condition')['object_id'] != condition['id']
                    or [item['object_id'] for item in field(condition, 'SousConditions')['items']]
                        != [variable['id'] if name == 'variable' else player['id']
                            for name in spec.get('condition_order', ['variable', 'player'])]
                    or field(variable, 'Operator')['object_id'] != compare['id']
                    or field(variable, 'Variable')['object_id'] != adapter['turn_variable']
                    or field(compare, 'Value')['value'] != creation['turn']
                    or any(prop['property_name'] == 'Variable' for prop in compare['properties'])
                    or field(player, 'Camp')['object_id'] != creation['campObjectId']
                    or [item['object_id'] for item in field(encapsule, 'SubActions')['items']]
                        != [play['id']]
                    or [item['object_id'] for item in field(play, 'DialogList')['items']]
                        != [dialog['id']]
                    or [item['object_id'] for item in field(dialog, 'TextComponentsToFill')['items']]
                        != expected_texts
                    or secondary is not None and (
                        creation.get('secondaryTextObjectId') != spec['secondary_text']
                        or creation.get('textureObjectId') != spec['texture']
                        or field(secondary, 'LocalizedText')['value_hex']
                            != creation.get('secondaryKey')
                        or [item['object_id'] for item in
                            field(dialog, 'TextureComponentsToFill')['items']]
                            != [texture['id']]
                        or field(texture, 'TextureFile')['value'] != spec['portrait'])
                    or secondary is None and creation.get('secondaryKey') is not None
                    or field(dialog, 'VisibleByCamp')['object_id'] != creation['campObjectId']
                    or field(dialog, 'ComponentName')['value'] != spec['speaker']
                    or field(narrative, 'LocalizedText')['value_hex'] != creation['textKey']):
                raise ValueError('Native candidate turn event differs from its private source chain')
            for locale, language in (('RU', 'ru'), ('US', 'en')):
                path = (root / 'Gen/Localisation' / identity['scenario'] / 'Scripting'
                        / ('Dialog-' + locale + '.dic'))
                if (_trad_data(path.read_bytes()).get(bytes.fromhex(creation['textKey']))
                        != creation['text'][language]):
                    raise ValueError('Native candidate turn event translation differs from its private text')
                if secondary is not None and (_trad_data(path.read_bytes()).get(
                        bytes.fromhex(creation['secondaryKey']))
                        != creation['secondaryText'][language]):
                    raise ValueError('Native candidate portrait event second text differs from its dictionary')
    if config.get('ai_target_edits'):
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        for edit in config['ai_target_edits']:
            obj = script['objects'][edit['objectId']]
            fields = [prop['value'] for prop in obj['properties']
                      if prop['property_name'] == edit['propertyName']]
            if len(fields) != 1 or obj['class'] != edit['nativeClass']:
                raise ValueError('Native candidate AI order binding changed')
            wire = fields[0]
            if edit['propertyName'] == 'Positions':
                if wire['type'] != 'list' or len(wire['items']) != 1:
                    raise ValueError('Native candidate AI movement target list changed')
                target = wire['items'][0]
            else:
                target = wire
            if (target['type'] != 'obj_ref' or target['object_id'] != edit['afterTargetObjectId']
                    or script['objects'][target['object_id']]['class'] != 'TGDTagPosition'):
                raise ValueError('Native candidate AI order no longer targets its verified map marker')
    if config.get('ai_order_creations'):
        from .native_ai_creation import source_order_tag_ids

        mapping = config.get('camp_by_side')
        if not isinstance(mapping, dict) or set(mapping) != {'nato', 'pact'} or set(mapping.values()) != {0, 1}:
            raise ValueError('Native candidate AI orders lack verified coalition camp mapping')
        definition = _unpack(definition_path.read_bytes())
        path = 'NDF/Scenarios/GDScript/' + identity['scenario'] + '.ndfbin'
        _, script = decode(definition[path])
        source_counts = {item.get('sourceObjectCount', 2050)
                         for item in config['ai_order_creations']}
        if len(source_counts) != 1 or not 0 < next(iter(source_counts)) <= len(script['objects']):
            raise ValueError('Native candidate AI order source object count changed')
        occupied_pawns = source_order_tag_ids({
            'objects': script['objects'][:next(iter(source_counts))]})
        deployment_ids = [item['deploymentId'] for item in config['ai_order_creations']]
        if len(deployment_ids) != len(set(deployment_ids)):
            raise ValueError('Native candidate has conflicting startup AI orders for one pawn')
        for creation in config['ai_order_creations']:
            objects = script['objects']
            sequence = objects[creation['sequenceObjectId']]
            order = objects[creation['orderObjectId']]
            collector = objects[creation['collectorObjectId']]
            wait = objects[creation['waitObjectId']]
            parent = objects[creation['parentObjectId']]
            group = objects[creation['groupObjectId']]
            tag = objects[creation['sourceTagObjectId']]
            tag_words = {item['property_name']: item['value'].get('value')
                         for item in tag['properties']}
            tag_guid = (struct.pack('>4i', *(tag_words['GUID' + str(number)]
                        for number in range(1, 5))).hex()
                        if all(type(tag_words.get('GUID' + str(number))) is int
                               for number in range(1, 5)) else None)
            spawn = native_spawn_identity(identity['scenario'], creation['deploymentId'])
            added = {item['id']: item for item in config.get('added_placements', [])}
            fields = {item['property_name']: item['value'] for item in order['properties']}
            collector_fields = {item['property_name']: item['value'] for item in collector['properties']}
            sequence_fields = {item['property_name']: item['value'] for item in sequence['properties']}
            parent_actions = next(item['value']['items'] for item in parent['properties']
                                  if item['property_name'] == 'SubActions')
            expected_parent_actions = creation.get('parentSourceActions', [723]) + [
                row['sequenceObjectId'] for row in config.get('turn_event_creations', [])
                if row['parentObjectId'] == parent['id']] + [
                row['sequenceObjectId'] for row in config['ai_order_creations']
                if row['parentObjectId'] == parent['id']]
            target = (fields['Positions']['items'][0] if creation['kind'] == 'attack'
                      else fields['Position'])
            if (sequence['class'] != 'TGDDescriptorSequential'
                    or order['class'] != ('TGDDescriptorStrategicMoveAndAttack'
                                          if creation['kind'] == 'attack'
                                          else 'TGDDescriptorStrategicDefend')
                    or collector['class'] != 'TGDDescriptorAddUnitGroupListToUnitGroup'
                    or wait['class'] != 'TGDDescriptorWaitDuration'
                    or group['class'] != 'TGDVariableUnitGroup'
                    or tag['class'] != 'TGDTagUnitGroup'
                    or '/Camp_' + str(creation['campIndex']) + '/' not in script['exports'].get(tag['id'], '')
                    or not creation.get('newPlacement', False)
                        and creation['sourceTagObjectId'] in occupied_pawns
                    or creation.get('newPlacement', False) and (creation['deploymentId'] not in added
                        or added[creation['deploymentId']]['side']
                            != ('nato' if creation['campIndex'] == mapping['nato'] else 'pact')
                        or creation['spawnTagExport'] != script['exports'].get(tag['id'])
                        or creation['spawnTagExport'].rsplit('/', 1)[-1] != spawn['name']
                        or creation['spawnGuid'] != spawn['guid'] or tag_guid != spawn['guid'])
                    or script['exports'].get(order['id']) != creation['orderExport']
                    or script['exports'].get(sequence['id']) != creation['sequenceExport']
                    or [item['object_id'] for item in sequence_fields['SubActions']['items']]
                        != [wait['id'], collector['id'], order['id']]
                    or collector_fields['GroupDestination']['object_id'] != group['id']
                    or [item['object_id'] for item in collector_fields['ListGroupSource']['items']]
                        != [tag['id']]
                    or fields['Group']['object_id'] != group['id']
                    or creation['kind'] == 'attack' and len(fields['Positions']['items']) != 1
                    or target['object_id'] != creation['targetObjectId']
                    or fields['AttackEnemyInRadius']['value'] != creation['attackRadius']
                    or fields['WaypointReachedRadius']['value'] != creation['waypointRadius']
                    or fields['ExecuteOnlyOnIAActivated']['value'] != creation['aiOnly']
                    or [item.get('object_id') for item in parent_actions] != expected_parent_actions):
                raise ValueError('Native candidate AI order differs from its private source action chain')
    return {'scenario': identity['scenario'], 'format': 'native-campaign-v1', 'file_count': len(files),
            'native_definition': verified, 'files': hashes, 'runtime_verified': False}


def package_native_campaign(source, profile, template, destination, world_output=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    native = destination / 'native'
    build_native_editor_artifacts(source, profile, native, world_output=world_output)
    config = assemble_native_candidate(native, template, destination / 'candidate')
    config_path = destination / 'campaign.compiled.json'
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    from .full_campaign import write_full_bundle
    bundle = write_full_bundle(destination / 'candidate', config_path)
    report = {'format': 'agf-native-campaign-package/v1', 'bundle': str(bundle), 'config': str(config_path),
              'candidate': str(destination / 'candidate'), 'scenario': config['identity']['scenario'], 'runtime_verified': False}
    (destination / 'package-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
