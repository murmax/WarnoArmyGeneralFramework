"""Build verified native scenario artifacts from the editor's explicit edit plan.

These artifacts precede official cooking/packaging. They are not an installable
bundle and carry no runtime claim.
"""
import copy
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import struct
import uuid

from .archives import pack_v3, read_directory
from .cndf import decode
from .native_campaign_clone import clone_native_definition
from .native_campaign_source import verify_native_snapshot
from .native_editor import compile_native_source
from .native_graph import NativeGraphEditor
from .native_frozen import add_native_frozen, native_spawn_identity, verify_native_frozen
from .native_roster_build import build_private_rosters, register_private_battle_orders
from .native_script_fields import validate_script_field, native_capability_inventory
from .storage import sha256


def _value(editor, obj, name, default=None):
    prop = editor.property(obj, name)
    return default if prop is None else prop['value'].get('value', prop['value'].get('value_hex', default))


def _check_property_changes(before_raw, after_raw, allowed, import_replacements=None,
                            allowed_import_additions=None, allowed_new_objects=0,
                            allowed_new_exports=None):
    _, before = decode(before_raw)
    _, after = decode(after_raw)
    expected_imports = {index: (import_replacements or {}).get(path, path) for index, path in before['imports'].items()}
    expected_imports.update({index: (import_replacements or {}).get(path, path)
                             for index, path in (allowed_import_additions or {}).items()})
    expected_exports = {**before['exports'], **(allowed_new_exports or {})}
    if (after['imports'] != expected_imports or after['exports'] != expected_exports
            or after['classes'] != before['classes']):
        raise ValueError('Unexpected native scenario schema or reference change')
    if len(after['objects']) != len(before['objects']) + allowed_new_objects:
        raise ValueError('Native scenario edit changed its object inventory')
    for old, new in zip(before['objects'], after['objects']):
        if (old['id'], old['class'], old['is_top_object']) != (new['id'], new['class'], new['is_top_object']):
            raise ValueError('Native scenario edit changed an object identity')
        old_props = {prop['property_name']: prop['value'] for prop in old['properties']}
        new_props = {prop['property_name']: prop['value'] for prop in new['properties']}
        for name in set(old_props) | set(new_props):
            if old_props.get(name) != new_props.get(name) and (old['id'], name) not in allowed:
                # Changed import leaves refresh their trans_ref value for every
                # consumer; the reference's table index and object structure stay.
                old_value, new_value = copy.deepcopy(old_props.get(name)), copy.deepcopy(new_props.get(name))
                def erase_resolved_import(value):
                    if isinstance(value, dict):
                        if value.get('type') == 'trans_ref':
                            value.pop('value', None)
                        for nested in value.values():
                            erase_resolved_import(nested)
                    elif isinstance(value, list):
                        for nested in value:
                            erase_resolved_import(nested)
                erase_resolved_import(old_value)
                erase_resolved_import(new_value)
                if old_value != new_value:
                    raise ValueError('Unexpected native scenario property change: ' + old['class'] + '.' + name)


def _patch_details(raw, placements, replacements, map_features=()):
    editor = NativeGraphEditor(raw)
    allowed = set()
    for placement in placements:
        name = placement['export']
        addons = [obj for obj in editor.objects if obj['class'] == 'TGameDesignAddOn_Spawn' and _value(editor, obj, 'Name') == name]
        if len(addons) != 1:
            raise ValueError('Native placement source name is missing or ambiguous: ' + name)
        addon = addons[0]
        parents = [obj for obj in editor.objects if obj['class'] in {'TGameDesignItem', 'TSaveDescriptorItemPoint'}
                   and editor.property(obj, 'AddOn') is not None
                   and editor.property(obj, 'AddOn')['value'].get('object_id') == addon['id']]
        if len(parents) != 1:
            raise ValueError('Native placement requires one source point')
        parent = parents[0]
        if placement.get('remove'):
            if parent['class'] == 'TGameDesignItem':
                editor.set_scalar(addon, 'DisableAutoSpawn', True, kind='bool')
                allowed.add((addon['id'], 'DisableAutoSpawn'))
            else:
                editor.set_scalar(addon, 'NbOfUnitToSpawn', 0, kind='int32')
                allowed.add((addon['id'], 'NbOfUnitToSpawn'))
            continue
        field = 'Position' if parent['class'] == 'TGameDesignItem' else 'AxeT'
        values = list(_value(editor, parent, field))
        expected = [placement['before']['x'], placement['before']['y']]
        if values[:2] != expected:
            raise ValueError('Native placement source coordinate precondition mismatch')
        values[:2] = [placement['position']['x'], placement['position']['y']]
        editor.set_scalar(parent, field, values)
        allowed.add((parent['id'], field))
    for feature in map_features:
        if not feature['position'] or not feature['before']:
            raise ValueError('Native map feature position is missing')
        addons = [obj for obj in editor.objects if obj['class'].startswith('TGameDesignAddOn_')
                  and obj['class'] != 'TGameDesignAddOn_Spawn'
                  and _value(editor, obj, 'Name') == feature['export']
                  and _value(editor, obj, 'GUID') == feature['guid']]
        if len(addons) != 1:
            raise ValueError('Native map feature source binding changed')
        addon = addons[0]
        parents = [obj for obj in editor.objects if obj['class'] in {'TGameDesignItem', 'TSaveDescriptorItemPoint'}
                   and (ref := editor.property(obj, 'AddOn')) is not None and ref['value'].get('object_id') == addon['id']]
        if len(parents) != 1:
            raise ValueError('Native map feature requires one source point')
        parent = parents[0]
        field = 'Position' if parent['class'] == 'TGameDesignItem' else 'AxeT'
        values = list(_value(editor, parent, field))
        if values[:2] != [feature['before']['x'], feature['before']['y']]:
            raise ValueError('Native map feature coordinate precondition mismatch')
        if feature['position'] != feature['before']:
            values[:2] = [feature['position']['x'], feature['position']['y']]
            editor.set_scalar(parent, field, values)
            allowed.add((parent['id'], field))
        if 'label_token' in feature:
            if addon['class'] != 'TGameDesignAddOn_LabelOnMap' or _value(editor, addon, 'Token') != feature['label_before']:
                raise ValueError('Native map label token precondition changed')
            editor.set_scalar(addon, 'Token', feature['label_token'])
            allowed.add((addon['id'], 'Token'))
    for obj in editor.objects:
        if obj['class'] == 'TGameDesignAddOn_Spawn':
            original = _value(editor, obj, 'ClassName')
            if original in replacements:
                editor.set_scalar(obj, 'ClassName', replacements[original])
                allowed.add((obj['id'], 'ClassName'))
    result = editor.save()
    _check_property_changes(raw, result, allowed)
    return result


def build_native_editor_artifacts(source, profile, destination, world_output=None):
    compiled = compile_native_source(source, profile)
    world_changes = [change for change in compiled['world_changes']
                     if change['path'][:2] != ['world', 'markers']
                     and change['path'][0] != 'playable_polygons']
    world_build = None
    if world_changes or compiled['heightmap_changed'] or compiled['surface_changed']:
        from .native_world import resolve_native_world
        world_build = resolve_native_world(compiled, world_output)
    snapshot = Path(compiled['snapshot'])
    verify_native_snapshot(snapshot)
    manifest = json.loads((snapshot / 'native-source.json').read_text(encoding='utf-8'))
    entries = {(row['scope'], row['path']): row for row in manifest['resources']}
    def payload(scope, path):
        return (snapshot / entries[scope, path]['file']).read_bytes()
    original = {path: payload(scope, path) for scope, path in entries if scope == 'scenario_definition'}
    edited = dict(original)
    replacements, localized, roster, order = {}, {}, None, None
    if compiled['battalion_edits']:
        roster = build_private_rosters(payload('shared_definitions', 'NDF/GFX/Pawn.ndfbin'),
            payload('shared_definitions', 'NDF/GFX/Deck.ndfbin'), compiled['battalion_edits'],
            compiled['entity_bindings'], compiled['identity']['scenario'],
            payload('shared_definitions', 'NDF/GFX/Depiction.ndfbin'),
            payload('shared_definitions', 'NDF/GFX/Division.ndfbin'))
        replacements, localized = roster['replacements'], roster['localized']
    script_path = f"NDF/Scenarios/GDScript/{compiled['original_scenario']}.ndfbin"
    script = NativeGraphEditor(original[script_path])
    allowed = set()
    for change in compiled['rule_edits']:
        obj = script.named(change['export'])
        if obj['id'] != change['objectId'] or obj['class'] != change['nativeClass'] or _value(script, obj, 'Value', 0) != change['before']:
            raise ValueError('Native rule source precondition changed')
        kind = {'TGDVariableInteger': 'int32', 'TGDVariableFloat': 'float32', 'TGDVariableBoolean': 'bool'}[obj['class']]
        script.set_scalar(obj, 'Value', change['value'], kind=kind)
        allowed.add((obj['id'], 'Value'))
    for change in compiled.get('script_edits', []):
        obj = script.objects[change['objectId']]
        property_name = change['propertyName']
        if (obj['class'] != change['nativeClass'] or script.exports.get(obj['id']) != change['export']
                or _value(script, obj, property_name) != change['before']):
            raise ValueError('Native script scalar edit source precondition changed')
        kind = validate_script_field(obj, property_name, change['after'])['type']
        script.set_scalar(obj, property_name, change['after'], kind=kind)
        allowed.add((obj['id'], property_name))
    new_script_imports = {}
    battalion_exports = {row['id']: row['export'] for row in compiled['entity_bindings']
                         if row['kind'] == 'battalion' and row.get('export')}
    for change in compiled.get('production_edits', []):
        obj = script.objects[change['objectId']]
        prop = script.property(obj, 'Pawns')
        if (obj['class'] != 'TGDDescriptorStrategicAddPossibleProduction'
                or script.exports.get(obj['id']) != change['export'] or prop is None
                or prop['value']['type'] != 'list'
                or [item['value'] for item in prop['value']['items']]
                    != [battalion_exports[identifier] for identifier in change['beforeBattalionIds']]):
            raise ValueError('Native production group source precondition changed')
        template = copy.deepcopy(prop['value']['items'][0])
        if template['type'] != 'trans_ref':
            raise ValueError('Native production group has no pawn import template')
        items = []
        for identifier in change['afterBattalionIds']:
            path = battalion_exports[identifier]
            index = next((key for key, value in script.imports.items() if value == path), None)
            if index is None:
                index = max(script.imports, default=-1) + 1
                script.imports[index] = path
                new_script_imports[index] = path
            item = copy.deepcopy(template)
            item.update(index=index, value=path)
            items.append(item)
        value = copy.deepcopy(prop['value'])
        value.update(items=items, length=len(items))
        script.set_value(obj, 'Pawns', value)
        allowed.add((obj['id'], 'Pawns'))
    for change in compiled.get('production_position_edits', []):
        group = script.objects[change['objectId']]
        prop = script.property(group, 'SpawnPositionsSortedByPriority')
        if (group['class'] != 'TGDStrategicReinforcementGroup'
                or script.exports.get(group['id']) != change['export']
                or prop is None or prop['value']['type'] != 'list'
                or [item.get('object_id') for item in prop['value']['items']]
                    != change['beforeTargetObjectIds']):
            raise ValueError('Native production spawn source precondition changed')
        script.set_value(group, 'SpawnPositionsSortedByPriority', script.sequence([
            script.reference(index) for index in change['afterTargetObjectIds']]))
        allowed.add((group['id'], 'SpawnPositionsSortedByPriority'))
    private_production_text = {}
    created_production_groups = []
    created_reinforcement_groups = []
    new_script_exports = {}
    new_script_objects = 0
    for change in compiled.get('reinforcement_creations', []):
        template = script.objects[change['templateObjectId']]
        parent = script.objects[change['parentActionObjectId']]
        if (template['class'] != 'TGDStrategicReinforcementGroup'
                or script.exports.get(template['id']) != change['templateExport']
                or parent['class'] != 'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction'):
            raise ValueError('Native reinforcement group source template changed')
        parent_camp = script.property(parent, 'Camp')
        references = script.property(parent, 'ReinforcementGroups')
        if (parent_camp is None or parent_camp['value'].get('object_id') != change['campObjectId']
                or references is None or references['value']['type'] != 'list'
                or [item.get('object_id') for item in references['value']['items']]
                    != change['parentSourceGroups']
                       + [item['groupObjectId'] for item in created_reinforcement_groups
                          if item['parentActionObjectId'] == parent['id']]
                or change['parentSourceGroups'].count(template['id']) != 1):
            raise ValueError('Native reinforcement registration source chain changed')
        marker_tag = None
        if change.get('spawnMarkerId') is not None:
            matches = [index for index, path in script.exports.items()
                       if path == change['spawnMarkerExport']]
            if len(matches) > 1:
                raise ValueError('Private reinforcement marker script export is ambiguous')
            if matches:
                marker_tag = script.objects[matches[0]]
            else:
                marker_tag = script.add('TGDTagPosition', export=change['spawnMarkerExport'])
                for number, word in enumerate(struct.unpack('>4i',
                        bytes.fromhex(change['spawnMarkerGuid'])), 1):
                    script.set_scalar(marker_tag, 'GUID' + str(number), word, kind='int32')
                new_script_objects += 1
                new_script_exports[marker_tag['id']] = change['spawnMarkerExport']
            words = [script.property(marker_tag, 'GUID' + str(number))
                     for number in range(1, 5)]
            if (marker_tag['class'] != 'TGDTagPosition' or any(word is None for word in words)
                    or [word['value'].get('value') for word in words]
                        != list(struct.unpack('>4i', bytes.fromhex(change['spawnMarkerGuid'])))):
                raise ValueError('Private reinforcement point conflicts with its map marker GUID')
        resolved_positions = ([marker_tag['id']] if marker_tag is not None
                              else change['spawnTargetObjectIds'])
        new_group = script.add('TGDStrategicReinforcementGroup', export=change['targetExport'])
        for prop in template['properties']:
            name = prop['property_name']
            wire = copy.deepcopy(prop['value'])
            if name in {'DisplayName', 'ShortDisplayName'}:
                wire['value_hex'] = change['displayKey' if name == 'DisplayName' else 'shortKey']
            elif name == 'SpawnPositionsSortedByPriority':
                wire = script.sequence([script.reference(index)
                                        for index in resolved_positions])
            script.set_value(new_group, name, wire)
        updated = copy.deepcopy(references['value'])
        updated['items'].append(script.reference(new_group['id']))
        updated['length'] = len(updated['items'])
        script.set_value(parent, 'ReinforcementGroups', updated)
        allowed.add((parent['id'], 'ReinforcementGroups'))
        new_script_objects += 1
        new_script_exports[new_group['id']] = change['targetExport']
        private_production_text[change['displayKey']] = change['name']
        private_production_text[change['shortKey']] = change['name']
        created_reinforcement_groups.append({**change, 'groupObjectId': new_group['id'],
            'resolvedSpawnTargetObjectIds': resolved_positions,
            'spawnMarkerObjectId': marker_tag['id'] if marker_tag is not None else None})
    for change in compiled.get('production_creations', []):
        template = script.objects[change['templateObjectId']]
        parent = script.objects[change['parentObjectId']]
        if (template['class'] != 'TGDDescriptorStrategicAddPossibleProduction'
                or script.exports.get(template['id']) != change['templateExport']
                or parent['class'] != 'TGDDescriptorSequential'):
            raise ValueError('Native production creation template or action chain changed')
        before_actions = script.property(parent, 'SubActions')
        if (before_actions is None or before_actions['value']['type'] != 'list'
                or sum(item.get('object_id') == template['id']
                       for item in before_actions['value']['items']) != 1):
            raise ValueError('Native production template no longer has a unique startup action')
        turn = script.add('TGDVariableInteger', export=change['turnExport'])
        script.set_scalar(turn, 'Value', change['unlockTurn'], kind='int32')
        group = script.add('TGDDescriptorStrategicAddPossibleProduction',
                           export=change['targetExport'])
        for prop in template['properties']:
            name = prop['property_name']
            value = copy.deepcopy(prop['value'])
            if name == 'Pawns':
                prototype = copy.deepcopy(value['items'][0])
                items = []
                for path in change['pawnExports']:
                    index = next((key for key, existing in script.imports.items() if existing == path), None)
                    if index is None:
                        index = max(script.imports, default=-1) + 1
                        script.imports[index] = path
                        new_script_imports[index] = path
                    item = copy.deepcopy(prototype)
                    item.update(index=index, value=path)
                    items.append(item)
                value.update(items=items, length=len(items))
            elif name == 'DisplayName':
                value['value_hex'] = change['titleKey']
            elif name == 'UnlockAtTurnVariable':
                value.update(object_id=turn['id'], class_id=turn['class_id'])
            elif name == 'ReinforcementGroup' and change.get('reinforcementGroupId') is not None:
                private_group = next((item for item in created_reinforcement_groups
                    if item['id'] == change['reinforcementGroupId']), None)
                if private_group is None:
                    raise ValueError('Native production references a missing private reinforcement division')
                target = script.objects[private_group['groupObjectId']]
                value.update(object_id=target['id'], class_id=target['class_id'])
            script.set_value(group, name, value)
        actions = copy.deepcopy(before_actions['value'])
        actions['items'].append(script.reference(group['id']))
        actions['length'] = len(actions['items'])
        script.set_value(parent, 'SubActions', actions)
        allowed.add((parent['id'], 'SubActions'))
        new_script_exports.update({turn['id']: change['turnExport'],
                                   group['id']: change['targetExport']})
        private_production_text[change['titleKey']] = change['name']
        created_production_groups.append({**change, 'groupObjectId': group['id'],
                                          'reinforcementObjectId':
                                              script.property(group, 'ReinforcementGroup')['value']['object_id'],
                                          'turnObjectId': turn['id']})
        new_script_objects += 2
    private_event_text = {}
    private_choice_text = {}
    for change in compiled.get('event_text_edits', []):
        obj = script.objects[change['objectId']]
        property_name = change.get('propertyName', 'LocalizedText')
        prop = script.property(obj, property_name)
        allowed_text = ({'TGDDescriptorCutsceneTextComponent': {'LocalizedText'},
                         'TGDDescriptorCutsceneDialogWithMultipleChoice':
                             {'TokenBoutonChoix0', 'TokenBoutonChoix1'},
                         'TGDDescriptorCutsceneDialog': {'TokenBoutonChoix0'}})
        if (property_name not in allowed_text.get(obj['class'], set())
                or script.exports.get(obj['id']) != change['export'] or prop is None
                or prop['value']['type'] != 'loc_hash'
                or prop['value']['value_hex'] != change['beforeKey']):
            raise ValueError('Native event text source precondition changed')
        script.set_scalar(obj, property_name, change['targetKey'], kind='loc_hash')
        allowed.add((obj['id'], property_name))
        target = private_event_text if property_name == 'LocalizedText' else private_choice_text
        target[change['targetKey']] = change['text']
    created_turn_events = []
    for change in compiled.get('turn_event_creations', []):
        parent = script.objects[change['parentObjectId']]
        template = script.objects[change['templateObjectId']]
        if (parent['class'] != 'TGDDescriptorSimultaneous'
                or template['class'] != 'TGDDescriptorSequential'):
            raise ValueError('Native turn event source parent changed')
        actions = script.property(parent, 'SubActions')
        if (actions is None or actions['value']['type'] != 'list'
                or [item['object_id'] for item in actions['value']['items']]
                    != change.get('parentSourceActions', [])
                       + [item['sequenceObjectId'] for item in created_turn_events
                          if item['parentObjectId'] == parent['id']]):
            raise ValueError('Native turn event source action chain changed')
        before_count = len(script.objects)
        if change.get('synthetic', False):
            mapping = {}
            for source_id in change['sourceSubtreeIds']:
                donor = script.objects[source_id]
                created = script.add(donor['class'],
                    export=change['sequenceExport'] if source_id == template['id'] else None)
                mapping[source_id] = created['id']
                for prop in donor['properties']:
                    script.set_value(created, prop['property_name'], prop['value'])
            sequence_id = mapping[template['id']]
            (sequence, wait, condition, variable, compare_synth, player_synth,
             encapsule, play, dialog_synth, narrative_synth) = (
                    script.objects[mapping[source_id]]
                    for source_id in change['sourceSubtreeIds'][:10])
            script.set_value(sequence, 'SubActions', script.sequence([
                script.reference(wait['id']), script.reference(encapsule['id'])]))
            script.set_scalar(sequence, 'NbExecutions', 1, kind='uint32')
            script.set_value(wait, 'Condition', script.reference(condition['id']))
            script.set_value(condition, 'SousConditions', script.sequence([
                script.reference(variable['id']), script.reference(player_synth['id'])]))
            script.set_value(variable, 'Operator', script.reference(compare_synth['id']))
            script.set_value(variable, 'Variable',
                             script.reference(change['turnVariableObjectId']))
            script.set_value(encapsule, 'SubActions',
                             script.sequence([script.reference(play['id'])]))
            script.set_value(play, 'DialogList',
                             script.sequence([script.reference(dialog_synth['id'])]))
            text_refs = [script.reference(narrative_synth['id'])]
            if change.get('secondaryKey') is not None:
                secondary_synth = script.objects[mapping[change['secondaryTextObjectId']]]
                texture_synth = script.objects[mapping[change['textureObjectId']]]
                text_refs.append(script.reference(secondary_synth['id']))
                script.set_value(dialog_synth, 'TextureComponentsToFill',
                                 script.sequence([script.reference(texture_synth['id'])]))
                script.set_scalar(texture_synth, 'TextureFile',
                                  change['portraitToken'], kind='strg_ref')
            script.set_value(dialog_synth, 'TextComponentsToFill',
                             script.sequence(text_refs))
        else:
            sequence_id, mapping = script.clone(template['id'],
                keep_classes=('TGDVariableCamp', 'TGDVariableInteger'),
                export=change['sequenceExport'])
        if (len(mapping) != len(change['sourceSubtreeIds'])
                or change['compareObjectId'] not in mapping
                or change['textObjectId'] not in mapping
                or set(mapping) != set(change['sourceSubtreeIds'])):
            raise ValueError('Native turn event template subtree changed')
        compare = script.objects[mapping[change['compareObjectId']]]
        if compare['class'] != 'TGDOperatorIntegerCompare':
            raise ValueError('Native turn event comparison template changed')
        compare['properties'] = [prop for prop in compare['properties']
                                 if prop['property_name'] != 'Variable']
        script.set_scalar(compare, 'Value', change['turn'], kind='int32')
        narrative = script.objects[mapping[change['textObjectId']]]
        if narrative['class'] != 'TGDDescriptorCutsceneTextComponent':
            raise ValueError('Native turn event dialog template changed')
        script.set_scalar(narrative, 'LocalizedText', change['textKey'], kind='loc_hash')
        if change.get('secondaryKey') is not None:
            secondary = script.objects[mapping[change['secondaryTextObjectId']]]
            if secondary['class'] != 'TGDDescriptorCutsceneTextComponent':
                raise ValueError('Native portrait event second text template changed')
            script.set_scalar(secondary, 'LocalizedText',
                              change['secondaryKey'], kind='loc_hash')
        player = script.objects[mapping[change['playerObjectId']]]
        dialog = script.objects[mapping[change['sourceSubtreeIds'][8]]]
        camp = script.objects[change['campObjectId']]
        if (player['class'] != 'TGDConditionStrategicIsPlayerTurn'
                or dialog['class'] != 'TGDDescriptorCutsceneDialog'
                or camp['class'] != 'TGDVariableCamp'):
            raise ValueError('Native turn event side or dialog template changed')
        script.set_value(player, 'Camp', script.reference(camp['id']))
        script.set_value(dialog, 'VisibleByCamp', script.reference(camp['id']))
        script.set_scalar(dialog, 'ComponentName', change['speaker'], kind='strg_ref')
        appended = copy.deepcopy(actions['value'])
        appended['items'].append(script.reference(sequence_id))
        appended['length'] = len(appended['items'])
        script.set_value(parent, 'SubActions', appended)
        allowed.add((parent['id'], 'SubActions'))
        new_script_objects += len(script.objects) - before_count
        new_script_exports[sequence_id] = change['sequenceExport']
        private_event_text[change['textKey']] = change['text']
        if change.get('secondaryKey') is not None:
            private_event_text[change['secondaryKey']] = change['secondaryText']
        created_turn_events.append({**change, 'sequenceObjectId': sequence_id,
            'objectMap': {str(source): target for source, target in mapping.items()}})
    for change in compiled.get('ai_target_edits', []):
        obj = script.objects[change['objectId']]
        name = change['propertyName']
        prop = script.property(obj, name)
        expected_field = {'TGDDescriptorStrategicMoveAndAttack': 'Positions',
                          'TGDDescriptorStrategicDefend': 'Position'}.get(obj['class'])
        if (obj['class'] != change['nativeClass'] or script.exports.get(obj['id']) != change['export']
                or expected_field != name or prop is None
                or script.objects[change['afterTargetObjectId']]['class'] != 'TGDTagPosition'):
            raise ValueError('Native AI order target source precondition changed')
        wire = copy.deepcopy(prop['value'])
        if name == 'Positions':
            if wire['type'] != 'list' or len(wire['items']) != 1:
                raise ValueError('Native AI movement order target list changed')
            target = wire['items'][0]
        else:
            target = wire
        if target['type'] != 'obj_ref' or target['object_id'] != change['beforeTargetObjectId']:
            raise ValueError('Native AI order target no longer points to the captured marker')
        target.update(object_id=change['afterTargetObjectId'],
                      class_id=script.objects[change['afterTargetObjectId']]['class_id'])
        script.set_value(obj, name, wire)
        allowed.add((obj['id'], name))
    created_ai_orders = []
    for change in compiled.get('ai_order_creations', []):
        parent = script.objects[change['parentObjectId']]
        template = script.objects[change['templateObjectId']]
        if change['newPlacement']:
            matches = [identifier for identifier, path in script.exports.items()
                       if path == change['spawnTagExport']]
            if len(matches) > 1:
                raise ValueError('Private AI pawn tag export is duplicated')
            if matches:
                tag = script.objects[matches[0]]
            else:
                tag = script.add('TGDTagUnitGroup', export=change['spawnTagExport'])
                for number, word in enumerate(struct.unpack('>4i', bytes.fromhex(change['spawnGuid'])), 1):
                    script.set_scalar(tag, 'GUID' + str(number), word, kind='int32')
                new_script_objects += 1
                new_script_exports[tag['id']] = change['spawnTagExport']
            guid_words = [script.property(tag, 'GUID' + str(number))['value'].get('value')
                          for number in range(1, 5)]
            if (tag['class'] != 'TGDTagUnitGroup'
                    or guid_words != list(struct.unpack('>4i', bytes.fromhex(change['spawnGuid'])))):
                raise ValueError('Private AI pawn tag differs from its map spawn GUID')
        else:
            tag = script.objects[change['sourceTagObjectId']]
        target = script.objects[change['targetObjectId']]
        if (parent['class'] != 'TGDDescriptorSimultaneous'
                or template['class'] not in {'TGDDescriptorStrategicMoveAndAttack', 'TGDDescriptorStrategicDefend'}
                or tag['class'] != 'TGDTagUnitGroup' or target['class'] != 'TGDTagPosition'):
            raise ValueError('Native AI order creation source shape changed')
        actions = script.property(parent, 'SubActions')
        if (actions is None or actions['value']['type'] != 'list'
                or [item['object_id'] for item in actions['value']['items']]
                    != change.get('parentSourceActions', [723])
                       + [item['sequenceObjectId'] for item in created_turn_events
                          if item['parentObjectId'] == parent['id']]
                       + [item['sequenceObjectId'] for item in created_ai_orders
                          if item['parentObjectId'] == parent['id']]):
            raise ValueError('Native AI order source parallel action chain changed')
        group = script.add('TGDVariableUnitGroup')
        collector = script.add('TGDDescriptorAddUnitGroupListToUnitGroup')
        script.set_value(collector, 'GroupDestination', script.reference(group['id']))
        script.set_value(collector, 'ListGroupSource',
                         script.sequence([script.reference(tag['id'])]))
        wait = script.add('TGDDescriptorWaitDuration')
        script.set_scalar(wait, 'Duree', 1.0, kind='float32')
        new_order = script.add(template['class'], export=change['orderExport'])
        for prop in template['properties']:
            name = prop['property_name']
            wire = copy.deepcopy(prop['value'])
            if name == 'Group':
                wire.update(object_id=group['id'], class_id=group['class_id'])
            elif name == 'Position':
                wire.update(object_id=target['id'], class_id=target['class_id'])
            elif name == 'Positions':
                if wire['type'] != 'list' or not wire['items']:
                    raise ValueError('Native AI attack template target list changed')
                first = wire['items'][0]
                first.update(object_id=target['id'], class_id=target['class_id'])
                wire.update(items=[first], length=1)
            elif name == 'AttackEnemyInRadius':
                wire['value'] = change['attackRadius']
            elif name == 'WaypointReachedRadius':
                wire['value'] = change['waypointRadius']
            elif name == 'ExecuteOnlyOnIAActivated':
                wire['value'] = change['aiOnly']
            script.set_value(new_order, name, wire)
        sequence = script.add('TGDDescriptorSequential', export=change['sequenceExport'])
        script.set_value(sequence, 'SubActions', script.sequence([
            script.reference(wait['id']), script.reference(collector['id']),
            script.reference(new_order['id'])]))
        script.set_scalar(sequence, 'NbExecutions', 1, kind='uint32')
        modified = copy.deepcopy(actions['value'])
        modified['items'].append(script.reference(sequence['id']))
        modified['length'] = len(modified['items'])
        script.set_value(parent, 'SubActions', modified)
        allowed.add((parent['id'], 'SubActions'))
        new_script_objects += 5
        new_script_exports.update({new_order['id']: change['orderExport'],
                                   sequence['id']: change['sequenceExport']})
        created_ai_orders.append({**change, 'sourceTagObjectId': tag['id'],
                                  'groupObjectId': group['id'],
                                  'collectorObjectId': collector['id'],
                                  'waitObjectId': wait['id'],
                                  'orderObjectId': new_order['id'],
                                  'sequenceObjectId': sequence['id']})
    script.imports.update({index: replacements.get(path, path) for index, path in script.imports.items()})
    edited[script_path] = script.save()
    _check_property_changes(original[script_path], edited[script_path], allowed, replacements,
                            new_script_imports, new_script_objects, new_script_exports)
    title_binding = None
    if compiled['state']['title'] != compiled['baseline']['title']:
        path = f"NDF/Scenarios/MapConfiguration/{compiled['original_scenario']}.ndfbin"
        editor = NativeGraphEditor(original[path])
        info = next(obj for obj in editor.objects if obj['class'] == 'TStrategicMapInfo')
        original_key = _value(editor, info, 'Name')
        private_key = hashlib.sha256((compiled['identity']['scenario'] + ':campaign-title').encode()).digest()[:8].hex()
        title_binding = {'source_key': original_key, 'target_key': private_key, 'text': compiled['state']['title']}
        fields_changed = set()
        def remap(value):
            if isinstance(value, dict):
                if value.get('type') == 'loc_hash' and value.get('value_hex') == original_key:
                    value['value_hex'] = private_key
                for item in value.values():
                    remap(item)
            elif isinstance(value, list):
                for item in value:
                    remap(item)
        for obj in editor.objects:
            for prop in obj['properties']:
                old_value = copy.deepcopy(prop['value'])
                remap(prop['value'])
                if prop['value'] != old_value:
                    fields_changed.add((obj['id'], prop['property_name']))
        edited[path] = editor.save()
        _check_property_changes(original[path], edited[path], fields_changed)
    details = {path: payload(scope, path) for scope, path in entries if scope == 'scenario_details'}
    for path in ('Items.sav', 'out/LevelDesign.ndfbin'):
        details[path] = _patch_details(details[path], compiled['placement_edits'], replacements,
                                       compiled.get('map_feature_edits', []))
    if compiled.get('added_placements') or compiled.get('added_map_labels'):
        from .map_registration import append_map_items
        rows = []
        for placement in compiled['added_placements']:
            export = roster['created'].get(placement['battalionId']) if roster else None
            if export is None:
                raise ValueError('New native placement has no private formation descriptor')
            spawn = native_spawn_identity(compiled['identity']['scenario'], placement['id'])
            rows.append({'kind': 'spawn', 'name': spawn['name'],
                         'guid': spawn['guid'],
                         'side': placement['side'], 'unit_export': export.rsplit('/', 1)[-1],
                         'position': [placement['position']['x'], placement['position']['y']]})
        for label in compiled.get('added_map_labels', []):
            rows.append({'kind': 'label', 'name': label['name'], 'guid': label['guid'],
                         'position': label['position'], 'token': label['token'], 'component': label['component']})
        for path in ('Items.sav', 'out/LevelDesign.ndfbin'):
            details[path] = append_map_items(details[path], rows,
                camp_by_side=compiled['camp_by_side'] if compiled['added_placements'] else None)
    markers = compiled['state']['world'].get('markers', [])
    if markers:
        from .native_markers import add_native_markers
        edited[script_path], details, marker_text = add_native_markers(edited[script_path], details, markers, compiled['identity']['scenario'])
        localized.update(marker_text)
    playable_proof = None
    if compiled['state']['playable_polygons'] != compiled['baseline']['playable_polygons']:
        from .native_playable import patch_playable_zones

        patched, playable_proof = patch_playable_zones(details, compiled)
        details.update(patched)
    frozen = add_native_frozen(edited[script_path], original[script_path], compiled)
    edited[script_path] = frozen['script']
    frozen_verification = (verify_native_frozen(edited[script_path], details['out/LevelDesign.ndfbin'],
                                               frozen['report']) if frozen['report'] else None)
    if world_build is not None:
        path = f"NDF/Scenarios/ScenarioInfo/{compiled['original_scenario']}.ndfbin"
        editor = NativeGraphEditor(edited[path])
        info = next(obj for obj in editor.objects if obj['class'] == 'TScenarioLoadInfo')
        editor.set_scalar(info, 'RootDatapackName', world_build['map_name'])
        edited[path] = editor.save()
    definition, clone_report = clone_native_definition(edited, compiled['original_scenario'], compiled['identity']['scenario'])
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-build-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'artifacts'
        scenario_folder = staged / 'Scenarios'
        scenario_folder.mkdir(parents=True)
        scenario = compiled['identity']['scenario']
        (scenario_folder / (scenario + '_Definition.dat')).write_bytes(definition)
        (scenario_folder / (scenario + '_Details.dat')).write_bytes(pack_v3(details))
        if world_build is not None:
            world_payload = Path(world_build['payload'])
            for relative in world_build['files']:
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(world_payload / relative, target)
        if roster is not None:
            gfx = staged / 'Gen/NDF/GFX'
            gfx.mkdir(parents=True)
            (gfx / 'Pawn.ndfbin').write_bytes(roster['pawn'])
            (gfx / 'Deck.ndfbin').write_bytes(roster['deck'])
            if roster['depiction'] is not None:
                (gfx / 'Depiction.ndfbin').write_bytes(roster['depiction'])
            if roster['division'] is not None:
                (gfx / 'Division.ndfbin').write_bytes(roster['division'])
            ui = staged / 'Gen/NDF/UI'
            ui.mkdir(parents=True)
            order = register_private_battle_orders(
                payload('shared_definitions', 'NDF/UI/Components.ndfbin'),
                payload('shared_definitions', 'NDF/UI/BattleOrder.ndfbin'),
                payload('shared_definitions', 'NDF/GFX/Pawn.ndfbin'),
                roster['deck_identifiers'], compiled['entity_bindings'])
            (ui / 'Components.ndfbin').write_bytes(order['components'])
            if order['battle_order'] is not None:
                (ui / 'BattleOrder.ndfbin').write_bytes(order['battle_order'])
        label_text = {row['label_key']: row['label_text'] for row in compiled.get('map_feature_edits', []) if 'label_key' in row}
        label_text.update({row['label_key']: row['label_text'] for row in compiled.get('added_map_labels', [])})
        label_text.update(frozen['label_text'])
        _, source_script_graph = decode(original[script_path])
        source_capabilities = native_capability_inventory(source_script_graph,
            compiled['original_scenario'], sha256(original[script_path]))
        report = {'format': 'agf-native-editor-build/v1', 'identity': compiled['identity'],
                  'changes': compiled['changes'], 'definition_clone': clone_report,
                  'pawn_replacements': replacements, 'private_text': localized,
                  'private_localized_text': roster['localized_translations'] if roster else {},
                  'private_label_text': label_text, 'campaign_title': title_binding,
                  'private_event_text': private_event_text,
                  'private_choice_text': private_choice_text,
                  'private_production_text': private_production_text,
                  'created_production_groups': created_production_groups,
                  'created_reinforcement_groups': created_reinforcement_groups,
                  'production_position_edits': compiled.get('production_position_edits', []),
                  'created_turn_events': created_turn_events,
                  'created_ai_orders': created_ai_orders,
                  'ai_target_edits': compiled.get('ai_target_edits', []),
                  'created_formations': roster['created'] if roster else {},
                  'strategic_visual_changes': roster['visual_changes'] if roster else [],
                  'private_division_changes': roster['division_changes'] if roster else [],
                  'map_command_changes': order['report'] if order else [],
                  'frozen_deployments': frozen['report'],
                  'camp_by_side': compiled.get('camp_by_side'),
                  'frozen_verification': frozen_verification,
                  'playable_polygon_verification': playable_proof,
                  'source_definition': {name: sha256(raw) for name, raw in original.items()},
                  'edited_definition': {name: sha256(raw) for name, raw in edited.items()},
                  'source_manifest_sha256': compiled['source_manifest_sha256'],
                  'source_capabilities': source_capabilities,
                  'definition_reference': {name: base64.b64encode(raw).decode('ascii') for name, raw in edited.items()},
                  'details_resources': {name: sha256(raw) for name, raw in details.items()},
                  'world': world_build,
                  'installable': False, 'runtime_verified': False}
        report['files'] = {path.relative_to(staged).as_posix(): sha256(path.read_bytes()) for path in staged.rglob('*') if path.is_file()}
        (staged / 'native-build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (staged / 'native-campaign.compiled.json').write_text(json.dumps(compiled, ensure_ascii=False, indent=2), encoding='utf-8')
        staged.rename(destination)
    return report
