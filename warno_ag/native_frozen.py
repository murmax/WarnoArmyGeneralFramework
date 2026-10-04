"""Private frozen-deployment script adapters for pinned stock source graphs.

The lifecycle is transplanted from the game's working Bruderkrieg countdown
shell. Only new, isolated spawn tags are targeted. This is a machine adapter;
it does not assert interactive WARNO acceptance.
"""
import copy
import hashlib
import json
import struct
import uuid
from pathlib import Path

from .cndf import decode
from .game_resources import GameResources
from .native_graph import NativeGraphEditor
from .storage import sha256


HIGHWAY_SCRIPT_SHA256 = 'a23d75ec8bdde4ca396d6db5b850f8b895d179a02727b3643a9230093658464e'
BRUDERKRIEG_SCRIPT_SHA256 = '3892070a2757f3e4b1457e32e3554374bd8e6bb2954e90c300b8624099d3d223'
SPAWN_NAMESPACE = uuid.UUID('b6969afb-aea9-5f58-ae04-26d6f6f73b70')
INITIAL_READINESS_SOURCES = frozenset({
    'CampagneStrat_Highway', 'CampagneStrat_Hanovre', 'CampagneStrat_Baor',
})

SOURCE_ADAPTERS = {
    'CampagneStrat_Highway': {
        'sha256': HIGHWAY_SCRIPT_SHA256,
        'intro': '$/GDScript/intro/Script/Launch_Main_Script_Sequence',
        'content': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'turn': '$/GDScript/VARIABLES/Tour',
        'nato': '$/GDScript/RootDescriptor/NATO', 'pact': '$/GDScript/RootDescriptor/PACT',
        'intro_count': 2, 'insert_before': 1},
    'CampagneStrat_FuldaGap': {
        'sha256': '64f071bab8cf7ff877ef936e4e6a36654f60cda44008a9ebf6ed331dbb4cb79c',
        'intro': '$/GDScript/intro/script/Launch',
        'content': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'turn': '$/GDScript/intro/script/Variables/Tour_actuel',
        'nato': '$/GDScript/RootDescriptor/nato', 'pact': '$/GDScript/RootDescriptor/pact',
        'intro_count': 3, 'insert_before': 2},
    'CampagneStrat_Hanovre': {
        'sha256': 'c58e22d1b93e19dccad0c59227eec370594f9b95d88046dd9a28b025dd9396b8',
        'intro': '$/GDScript/intro/script/Launch',
        'content': '$/GDScript/partie_1/Script/Launch_main_script',
        'turn': '$/GDScript/intro/script/Variables/Tour_actuel',
        'nato': '$/GDScript/RootDescriptor/nato', 'pact': '$/GDScript/RootDescriptor/pact',
        'intro_count': 1, 'insert_before': 0},
    'CampagneStrat_Luneburg': {
        'sha256': '9406997355b250d497aba0265c8a3e4c120b04e7cb7ac9f709223c4664e495af',
        'intro': '$/GDScript/intro/script/Launch',
        'content': '$/GDScript/partie_1/Script/Launch_main_script',
        'turn': '$/GDScript/intro/script/Variables/Tour_actuel',
        'nato': '$/GDScript/RootDescriptor/nato', 'pact': '$/GDScript/RootDescriptor/pact',
        'intro_count': 6, 'insert_before': 5},
    'CampagneStrat_Airborne': {
        'sha256': '9162e80687c2ed9b901f1bbc964c2e8e03cf4f30e93a50c037b8c8cc5ac68104',
        'intro': '$/GDScript/intro/script/Launch_Main_Script_Sequence',
        'content': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'turn': '$/GDScript/intro/script/Variables/Game_Logic/Current_Turn',
        'nato': '$/GDScript/RootDescriptor/NATO', 'pact': '$/GDScript/RootDescriptor/PACT',
        'intro_count': 6, 'insert_before': 5},
    'CampagneStrat_Baor': {
        'sha256': 'f58c2dea42f1a78aec4dda051acd7e372bede1b18d685f2c27e80a7914c2e894',
        'intro': '$/GDScript/intro/script/Launch_Main_Script_Sequence',
        'content': '$/GDScript/partie_1/Script/Launch_Main_Script_Sequence',
        'turn': '$/GDScript/intro/script/Variables/Current_Turn',
        'nato': '$/GDScript/RootDescriptor/NATO', 'pact': '$/GDScript/RootDescriptor/PACT',
        'intro_count': 4, 'insert_before': 3},
    'CampagneStrat_Bruderkrieg': {
        'sha256': BRUDERKRIEG_SCRIPT_SHA256,
        'intro': '$/GDScript/intro/script/Launch_Common_Script_Sequence',
        'content': '$/GDScript/partie_OTAN/Script/Launch_Main_Script_Sequence',
        'turn': '$/GDScript/intro/script/Variables/Tour_Actuel',
        'nato': '$/GDScript/RootDescriptor/nato', 'pact': '$/GDScript/RootDescriptor/pact',
        'intro_count': 11, 'insert_before': 10},
    'CampagneStrat_ClosingTheTrap': {
        'sha256': 'ec8e8db24ec58b6cf7942fcfe08669a8ed43815970578a8356abaa9b33e29d90',
        'intro': '$/GDScript/intro/Main_Script_Sequence',
        'content_id': 207,
        'turn': '$/GDScript/intro/Variables/Nb_Tour_Actuel',
        'nato': '$/GDScript/RootDescriptor/NATO', 'pact': '$/GDScript/RootDescriptor/PACT',
        'intro_count': 7, 'insert_before': 6},
    'CampagneStrat_HoldingAttack': {
        'sha256': '9d0e6e18956528a9043701d515eef1b244f681267ad38feb564397705c0649f8',
        'intro': '$/GDScript/intro/Main_Script_Sequence',
        'content_id': 189,
        'turn': '$/GDScript/intro/Variables/Nb_Tour_Actuel',
        'nato': '$/GDScript/RootDescriptor/NATO', 'pact': '$/GDScript/RootDescriptor/PACT',
        'intro_count': 11, 'insert_before': 10},
}


def frozen_source_spec(scenario, digest):
    spec = SOURCE_ADAPTERS.get(scenario)
    return spec if spec is not None and spec['sha256'] == digest else None


def native_spawn_identity(scenario, placement_id):
    key = scenario + ':placement:' + placement_id
    return {'name': 'AGFSpawn_' + hashlib.sha256(key.encode()).hexdigest()[:16],
            'guid': uuid.uuid5(SPAWN_NAMESPACE, key).hex}


def add_native_frozen(script_raw, source_script_raw, compiled):
    requested_by_id = {}
    for deployment in (compiled.get('frozen_deployments', [])
                       + compiled.get('action_point_deployments', [])
                       + compiled.get('initial_readiness_deployments', [])):
        prior = requested_by_id.get(deployment['id'])
        if prior is not None and prior != deployment:
            raise ValueError('Private native readiness declarations disagree for one placement')
        requested_by_id[deployment['id']] = deployment
    requested = list(requested_by_id.values())
    if not requested:
        return {'script': script_raw, 'label_text': {}, 'report': []}
    spec = frozen_source_spec(compiled['original_scenario'], sha256(source_script_raw))
    if spec is None:
        raise ValueError('Native frozen adapter has no verified source lifecycle for this scenario revision')
    camp_by_side = compiled.get('camp_by_side')
    if (not isinstance(camp_by_side, dict) or set(camp_by_side) != {'nato', 'pact'}
            or set(camp_by_side.values()) != {0, 1}):
        raise ValueError('Native frozen adapter requires verified source coalition camp indices')
    manifest = json.loads((Path(compiled['snapshot']) / 'native-source.json').read_text(encoding='utf-8'))
    game = GameResources(manifest['game_root'])
    donor_raw = game.scenario('CampagneStrat_Bruderkrieg', 'Definition').read(
        'NDF/Scenarios/GDScript/CampagneStrat_Bruderkrieg.ndfbin')
    if sha256(donor_raw) != BRUDERKRIEG_SCRIPT_SHA256:
        raise ValueError('Pinned native frozen donor script changed')
    donor = NativeGraphEditor(donor_raw)
    editor = NativeGraphEditor(script_raw)
    intro = editor.named(spec['intro'])
    content = editor.objects[spec['content_id']] if 'content_id' in spec else editor.named(spec['content'])
    if intro['class'] != 'TGDDescriptorSequential' or content['class'] != 'TGDDescriptorSimultaneous':
        raise ValueError('Pinned native lifecycle root changed')
    launch_actions = copy.deepcopy(editor.property(intro, 'SubActions')['value'])
    content_actions = copy.deepcopy(editor.property(content, 'SubActions')['value'])
    if (len(launch_actions['items']) != spec['intro_count'] or len(content_actions['items']) < 2
            or editor.objects[launch_actions['items'][spec['insert_before']]['object_id']]['class']
               != 'TGDDescriptorSimultaneous'):
        raise ValueError('Pinned native startup ordering changed')

    def append_import(path):
        existing = next((index for index, value in editor.imports.items() if value == path), None)
        if existing is not None:
            return existing
        index = max(editor.imports, default=-1) + 1
        editor.imports[index] = path
        return index

    labels, reports, setups, timelines = {}, [], [], []
    used_tags = set()
    for deployment in requested:
        spawn = native_spawn_identity(compiled['identity']['scenario'], deployment['id'])
        key = (deployment['side'], spawn['name'])
        if key in used_tags:
            raise ValueError('Frozen native spawn identity is duplicated')
        used_tags.add(key)
        camp_index = camp_by_side[deployment['side']]
        tag_path = '$/GDScript/GdItems/Camp_' + str(camp_index) + '/' + spawn['name']
        existing_tags = [index for index, path in editor.exports.items() if path == tag_path]
        if len(existing_tags) > 1:
            raise ValueError('Frozen native spawn tag is ambiguous')
        if existing_tags:
            tag = editor.objects[existing_tags[0]]
            words = struct.unpack('>4i', bytes.fromhex(spawn['guid']))
            values = [editor.property(tag, 'GUID' + str(number)) for number in range(1, 5)]
            if (tag['class'] != 'TGDTagUnitGroup' or any(value is None for value in values)
                    or [value['value'].get('value') for value in values] != list(words)):
                raise ValueError('Frozen native spawn tag conflicts with private AI pawn')
        else:
            tag = editor.add('TGDTagUnitGroup', export=tag_path)
            for number, word in enumerate(struct.unpack('>4i', bytes.fromhex(spawn['guid'])), 1):
                editor.set_scalar(tag, 'GUID' + str(number), word, kind='int32')
        group = editor.add('TGDVariableUnitGroup')
        own_camp = editor.named(spec[deployment['side']])
        other_camp = editor.named(spec['pact' if deployment['side'] == 'nato' else 'nato'])
        turn = editor.named(spec['turn'])
        if (own_camp['class'] != 'TGDVariableCamp' or other_camp['class'] != 'TGDVariableCamp'
                or turn['class'] != 'TGDVariableInteger'):
            raise ValueError('Pinned native side or turn binding changed')
        fixed = {309: group['id'], 365: tag['id'], 284: own_camp['id'],
                 283: other_camp['id'], 381: turn['id']}
        mapping = {}

        def transplant(old_id):
            if old_id in fixed:
                return fixed[old_id]
            if old_id in mapping:
                return mapping[old_id]
            old = donor.objects[old_id]
            created = editor.add(old['class'])
            mapping[old_id] = created['id']
            for prop in old['properties']:
                wire = copy.deepcopy(prop['value'])
                if old_id == 471 and prop['property_name'] == 'SubActions':
                    if len(wire['items']) != 4:
                        raise ValueError('Pinned frozen countdown root changed')
                    wire.update(items=wire['items'][:2], length=2)

                def remap(value):
                    if isinstance(value, dict):
                        kind = value.get('type')
                        if kind == 'obj_ref' and value.get('object_id') != 0xffffffff:
                            new_id = transplant(value['object_id'])
                            value.update(object_id=new_id, class_id=editor.objects[new_id]['class_id'])
                        elif kind == 'trans_ref':
                            path = value.get('value')
                            if not isinstance(path, str):
                                raise ValueError('Frozen donor has an unresolved native import')
                            value['index'] = append_import(path)
                        elif kind in {'strg_ref', 'file_strg_ref'}:
                            value['index'] = editor.string(value['value'])
                        for child in value.values():
                            remap(child)
                    elif isinstance(value, list):
                        for child in value:
                            remap(child)
                remap(wire)
                editor.set_value(created, prop['property_name'], wire)
            return created['id']

        collector_id = transplant(325)
        frozen_mode = deployment['frozenTurns'] > 0
        action_id = transplant(296 if frozen_mode else 529)
        if (editor.objects[collector_id]['class'] != 'TGDDescriptorAddUnitGroupListToUnitGroup'
                or editor.objects[action_id]['class'] != 'TGDDescriptorChangePawnActionPoint'):
            raise ValueError('Pinned native readiness setup classes changed')
        setup_refs = [editor.reference(collector_id), editor.reference(action_id)]
        fatigue = deployment.get('fatigue', 0)
        losses = deployment.get('initialLossBudget', 0)
        spread = deployment.get('initialLossRandomRange', 0)
        readiness_report = {}
        if fatigue or losses:
            if compiled['original_scenario'] not in INITIAL_READINESS_SOURCES:
                raise ValueError('Native source lacks a pinned initial fatigue/casualty adapter')
            if not {'TGDDescriptorSetFatigueToPawn', 'TGDDescriptorAddCasualtiesToPawn'} <= set(editor.graph['classes']):
                raise ValueError('Native source lacks initial readiness action classes')
        if losses:
            casualty = editor.add('TGDDescriptorAddCasualtiesToPawn')
            editor.set_scalar(casualty, 'Casualties', losses, kind='int32')
            editor.set_scalar(casualty, 'RandomRange', spread, kind='int32')
            editor.set_scalar(casualty, 'TypeCasualties', 1, kind='int32')
            editor.set_value(casualty, 'Group', editor.reference(tag['id']))
            setup_refs.append(editor.reference(casualty['id']))
            readiness_report.update(casualty_action=casualty['id'], casualties=losses,
                                    random_range=spread)
        if fatigue:
            tired = editor.add('TGDDescriptorSetFatigueToPawn')
            editor.set_scalar(tired, 'Fatigue', fatigue, kind='int32')
            editor.set_value(tired, 'Group', editor.reference(tag['id']))
            setup_refs.append(editor.reference(tired['id']))
            readiness_report.update(fatigue_action=tired['id'], fatigue=fatigue)
        setup = editor.add('TGDDescriptorSequential')
        editor.set_value(setup, 'SubActions', editor.sequence(setup_refs))
        editor.set_scalar(setup, 'NbExecutions', 1, kind='uint32')
        setups.append(editor.reference(setup['id']))
        report = {'deployment_id': deployment['id'], 'side': deployment['side'],
                  'mode': 'frozen' if frozen_mode else 'initial_ap',
                  'turns': deployment['frozenTurns'], 'camp_index': camp_index,
                  'spawn_tag': tag_path, 'spawn_guid': spawn['guid'],
                  'group_object': group['id'], 'setup_object': setup['id'],
                  'clear_action': action_id, 'intro_path': spec['intro'],
                  'content_path': spec.get('content'), 'content_object': content['id'],
                  'donor_sha256': BRUDERKRIEG_SCRIPT_SHA256,
                  'cloned_objects': len(mapping), 'runtime_verified': False}
        report.update(readiness_report)
        if frozen_mode:
            timeline_id = transplant(471)
            if editor.objects[timeline_id]['class'] != 'TGDDescriptorSequential':
                raise ValueError('Pinned frozen countdown class changed')
            timelines.append(editor.reference(timeline_id))
            turns = deployment['frozenTurns']
            editor.set_scalar(editor.objects[mapping[746]], 'Value', turns, kind='int32')
            editor.set_scalar(editor.objects[mapping[871]], 'Value', turns, kind='int32')
            editor.set_scalar(editor.objects[mapping[529]], 'ActionPointNumber',
                              float(deployment['actionPoints']), kind='float32')
            countdown_key = hashlib.sha256((compiled['identity']['scenario'] + ':frozen:'
                + deployment['id'] + ':countdown').encode()).digest()[:8].hex()
            empty_key = hashlib.sha256((compiled['identity']['scenario'] + ':frozen:'
                + deployment['id'] + ':empty').encode()).digest()[:8].hex()
            label = editor.objects[mapping[617]]
            editor.set_scalar(label, 'FoldedText', countdown_key, kind='loc_hash')
            editor.set_scalar(label, 'Text', empty_key, kind='loc_hash')
            labels[countdown_key] = {'ru': 'Готовность через %1 ход(-ов)', 'en': 'Available in %1 turn(s)'}
            labels[empty_key] = {'ru': '', 'en': ''}
            report.update(label_object=label['id'], effect_object=mapping[619],
                          counter_object=mapping[746], compare_object=mapping[871],
                          countdown_label_key=countdown_key, empty_label_key=empty_key,
                          countdown=timeline_id, restore_action_points=deployment['actionPoints'])
        else:
            editor.set_scalar(editor.objects[action_id], 'ActionPointNumber',
                              float(deployment['actionPoints']), kind='float32')
            report['initial_action_points'] = deployment['actionPoints']
        reports.append(report)
    insert_at = spec['insert_before']
    launch_actions['items'] = (launch_actions['items'][:insert_at] + setups
                               + launch_actions['items'][insert_at:])
    launch_actions['length'] = len(launch_actions['items'])
    editor.set_value(intro, 'SubActions', launch_actions)
    content_actions['items'].extend(timelines)
    content_actions['length'] = len(content_actions['items'])
    editor.set_value(content, 'SubActions', content_actions)
    output = editor.save()
    _, before = decode(script_raw)
    _, after = decode(output)
    if (len(after['objects']) <= len(before['objects'])
            or any(old['properties'] != new['properties'] for old, new in zip(before['objects'], after['objects'])
                   if old['id'] not in {intro['id'], content['id']})
            or any(after['imports'].get(index) != path for index, path in before['imports'].items())
            or any(after['exports'].get(index) != path for index, path in before['exports'].items())):
        raise ValueError('Native frozen adapter changed an unrelated source graph node')
    verify_native_frozen(output, None, reports)
    return {'script': output, 'label_text': labels, 'report': reports}


def verify_native_frozen(script_raw, level_raw, reports):
    _, graph = decode(script_raw)
    objects = graph['objects']

    def prop(obj, name):
        found = [item['value'] for item in obj['properties'] if item['property_name'] == name]
        if len(found) != 1:
            raise ValueError('Frozen native graph has a missing or ambiguous ' + name)
        return found[0]

    def refs(value):
        return [item['object_id'] for item in value['items']]

    intro_path = reports[0].get('intro_path', SOURCE_ADAPTERS['CampagneStrat_Highway']['intro'])
    content_path = reports[0].get('content_path', SOURCE_ADAPTERS['CampagneStrat_Highway']['content'])
    content_object = reports[0].get('content_object')
    if any(row.get('intro_path', intro_path) != intro_path
           or row.get('content_path', content_path) != content_path
           or row.get('content_object', content_object) != content_object for row in reports):
        raise ValueError('Frozen native reports disagree on lifecycle roots')
    intro = objects[next(i for i, path in graph['exports'].items() if path == intro_path)]
    if content_path is None:
        if type(content_object) is not int or not 0 <= content_object < len(objects):
            raise ValueError('Frozen native content object is missing')
        content = objects[content_object]
    else:
        content = objects[next(i for i, path in graph['exports'].items() if path == content_path)]
        if content_object is not None and content['id'] != content_object:
            raise ValueError('Frozen native content path differs from its object')
    launch_ids = refs(prop(intro, 'SubActions'))
    content_ids = refs(prop(content, 'SubActions'))
    level_spawns = {}
    if level_raw is not None:
        _, level = decode(level_raw)
        for obj in level['objects']:
            if obj['class'] != 'TGameDesignAddOn_Spawn':
                continue
            values = {item['property_name']: item['value'] for item in obj['properties']}
            level_spawns[values['Name']['value']] = values
    for row in reports:
        camp_index = row.get('camp_index')
        if camp_index is None:
            camp_index = int(row['spawn_tag'].split('/Camp_', 1)[1].split('/', 1)[0])
        tag_id = next((i for i, path in graph['exports'].items() if path == row['spawn_tag']), None)
        if tag_id is None or objects[tag_id]['class'] != 'TGDTagUnitGroup':
            raise ValueError('Frozen spawn has no native GDScript unit tag')
        words = struct.unpack('>4i', bytes.fromhex(row['spawn_guid']))
        if [prop(objects[tag_id], 'GUID' + str(i))['value'] for i in range(1, 5)] != list(words):
            raise ValueError('Frozen spawn tag GUID differs from its map registration')
        if level_raw is not None:
            name = row['spawn_tag'].rsplit('/', 1)[-1]
            values = level_spawns.get(name)
            if values is None or values['GUID']['value_hex'] != row['spawn_guid']:
                raise ValueError('Frozen native map spawn lacks its matching GUID')
            if (values['Ranking']['value'] != 'Camp_' + str(camp_index)
                    or values.get('Camp', {}).get('value', camp_index) != camp_index):
                raise ValueError('Frozen native map spawn coalition camp differs from its source mapping')
        group = row['group_object']
        if objects[group]['class'] != 'TGDVariableUnitGroup':
            raise ValueError('Frozen native unit group changed class')
        setup = objects[row['setup_object']]
        if setup['class'] != 'TGDDescriptorSequential' or row['setup_object'] not in launch_ids:
            raise ValueError('Frozen setup is absent from native startup')
        setup_actions = refs(prop(setup, 'SubActions'))
        expected_tail = [row['clear_action']]
        if 'casualty_action' in row:
            expected_tail.append(row['casualty_action'])
        if 'fatigue_action' in row:
            expected_tail.append(row['fatigue_action'])
        if setup_actions[1:] != expected_tail or len(setup_actions) != len(expected_tail) + 1:
            raise ValueError('Frozen group setup and AP clear changed order')
        collector, clear = (objects[index] for index in setup_actions[:2])
        if (collector['class'] != 'TGDDescriptorAddUnitGroupListToUnitGroup'
                or prop(collector, 'GroupDestination')['object_id'] != group
                or refs(prop(collector, 'ListGroupSource')) != [tag_id]
                or clear['class'] != 'TGDDescriptorChangePawnActionPoint'
                or prop(clear, 'UnitsGroup')['object_id'] != group):
            raise ValueError('Native readiness startup no longer targets only the selected pawn')
        if 'casualty_action' in row:
            casualty = objects[row['casualty_action']]
            if (casualty['class'] != 'TGDDescriptorAddCasualtiesToPawn'
                    or prop(casualty, 'Group')['object_id'] != tag_id
                    or prop(casualty, 'Casualties')['value'] != row['casualties']
                    or prop(casualty, 'RandomRange')['value'] != row['random_range']
                    or prop(casualty, 'TypeCasualties')['value'] != 1):
                raise ValueError('Native initial casualties differ from their private map pawn')
        if 'fatigue_action' in row:
            tired = objects[row['fatigue_action']]
            if (tired['class'] != 'TGDDescriptorSetFatigueToPawn'
                    or prop(tired, 'Group')['object_id'] != tag_id
                    or prop(tired, 'Fatigue')['value'] != row['fatigue']):
                raise ValueError('Native initial fatigue differs from its private map pawn')
        if row.get('mode') == 'initial_ap':
            if (prop(clear, 'ActionPointNumber')['value'] != row['initial_action_points']
                    or any(item.get('object_id') == row['clear_action']
                           for item in prop(content, 'SubActions')['items'])):
                raise ValueError('Native initial AP setup differs from its declared value')
            continue
        if any(item['property_name'] == 'ActionPointNumber' for item in clear['properties']):
            raise ValueError('Frozen native startup no longer clears only the selected pawn AP')
        timeline = objects[row['countdown']]
        if timeline['class'] != 'TGDDescriptorSequential' or row['countdown'] not in content_ids:
            raise ValueError('Frozen countdown is absent from native campaign content')
        root_actions = refs(prop(timeline, 'SubActions'))
        if len(root_actions) != 2:
            raise ValueError('Frozen countdown includes an unexpected stock notification')
        competition, restore = (objects[index] for index in root_actions)
        if (competition['class'] != 'TGDDescriptorCompetition'
                or restore['class'] != 'TGDDescriptorChangePawnActionPoint'
                or prop(restore, 'UnitsGroup')['object_id'] != group
                or prop(restore, 'ActionPointNumber')['value'] != row['restore_action_points']):
            raise ValueError('Frozen native AP restoration is not bound to its pawn')
        competition_actions = refs(prop(competition, 'SubActions'))
        if len(competition_actions) != 4:
            raise ValueError('Frozen native countdown competition changed shape')
        wait, label, decrement, effect = (objects[index] for index in competition_actions)
        if (wait['class'] != 'TGDDescriptorWaitCondition'
                or label['id'] != row['label_object']
                or label['class'] != 'TGDDescriptorDrawLabelOnPosition'
                or prop(label, 'Group')['object_id'] != group
                or prop(label, 'FoldedText')['value_hex'] != row['countdown_label_key']
                or prop(label, 'Text')['value_hex'] != row['empty_label_key']
                or refs(prop(label, 'ListVariablesForFoldedText')) != [row['counter_object']]
                or prop(objects[row['counter_object']], 'Value')['value'] != row['turns']):
            raise ValueError('Frozen native countdown label or counter changed')
        condition = objects[prop(wait, 'Condition')['object_id']]
        branches = [objects[index] for index in refs(prop(condition, 'SousConditions'))]
        if (condition['class'] != 'TGDConditionAnd' or len(branches) != 2
                or not any(obj['class'] == 'TGDConditionVariable'
                    and prop(obj, 'Operator')['object_id'] == row['compare_object'] for obj in branches)
                or prop(objects[row['compare_object']], 'Value')['value'] != row['turns']):
            raise ValueError('Frozen native release turn changed')
        if (decrement['class'] != 'TGDDescriptorSequential'
                or effect['id'] != row['effect_object']
                or effect['class'] != 'TGDDescriptorSetEffect'
                or prop(effect, 'Effet')['value'] != '$/GFX/EffectCapacity/UnitEffect_ArmyGen_No_regen_PA'
                or refs(prop(effect, 'UnitGroup')) != [group]):
            raise ValueError('Frozen native AP regeneration suppressor changed')
    proof = {'frozen_deployments': sum(row.get('mode', 'frozen') == 'frozen' for row in reports),
             'verified_lifecycle': True, 'runtime_verified': False}
    if any(row.get('mode') == 'initial_ap' for row in reports):
        proof['initial_ap_deployments'] = sum(row.get('mode') == 'initial_ap' for row in reports)
    if any('fatigue_action' in row or 'casualty_action' in row for row in reports):
        proof['readiness_deployments'] = sum('fatigue_action' in row or 'casualty_action' in row
                                             for row in reports)
    return proof
