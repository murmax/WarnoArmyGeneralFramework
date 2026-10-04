"""Clone a current stock Definition and prove its native gameplay graph survives.

This is one build stage. Details, media, registration and an installed-game
acceptance are separate stages; a successful Definition clone is not a campaign
bundle. The comparison reads the emitted archive independently.
"""
import copy
import hashlib
import re
import uuid

from .archives import pack_v3, read_directory, repack
from .cndf import decode, encode_objects, encode_strings, rebuild_sections
from .storage import sha256


NAMESPACE = uuid.UUID('92269d1a-2944-57da-9c82-d9cfd7a6d64b')
IDENTITY_CLASSES = {'TStrategicMapInfo', 'TScenarioLoadInfo'}
TROPHY_FIELDS = {
    'TTrophy': 'Id',
    'TTrophyUnlockerOnObjectiveCompleted': 'ObjectiveId',
    'TGDDescriptorUnlockAchievementForObjective': 'IdForAchievement',
}


def _value(obj, name):
    matches = [prop['value'] for prop in obj['properties'] if prop['property_name'] == name]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous native identity field: ' + obj['class'] + '.' + name)
    return matches[0]


def _payloads(raw):
    header, entries, _ = read_directory(raw)
    return {entry.path: raw[header.file_offset + entry.offset:header.file_offset + entry.offset + entry.size] for entry in entries}


def clone_native_definition(payloads, source, target):
    if (not isinstance(source, str) or not isinstance(target, str)
            or re.fullmatch(r'CampagneStrat_[A-Za-z0-9_]+', source) is None
            or re.fullmatch(r'CampagneStrat_[A-Za-z0-9_]+', target) is None
            or source.casefold() == target.casefold()):
        raise ValueError('Native clone requires a distinct valid campaign identity')
    graphs = {name: decode(raw) for name, raw in payloads.items()}
    guids = {value['value_hex'] for _, graph in graphs.values() for obj in graph['objects']
             if obj['class'] in IDENTITY_CLASSES for value in [_value(obj, 'GUID')]}
    if len(guids) != 1:
        raise ValueError('Native Definition has inconsistent campaign GUIDs')
    source_guid = next(iter(guids))
    target_guid = uuid.uuid5(NAMESPACE, target).hex
    trophy_ids = sorted({int(_value(obj, TROPHY_FIELDS[obj['class']])['value']) for _, graph in graphs.values()
                         for obj in graph['objects'] if obj['class'] in TROPHY_FIELDS})
    mapping = {}
    for identifier in trophy_ids:
        digest = hashlib.sha256((target + ':trophy:' + str(identifier)).encode()).digest()
        mapping[identifier] = 0x40000000 | (int.from_bytes(digest[:4], 'little') & 0x3fffffff)
    if len(set(mapping.values())) != len(mapping) or set(mapping.values()) & set(trophy_ids):
        raise ValueError('Native trophy identity collision')
    outputs = {}
    changes = []
    for name, (document, graph) in graphs.items():
        if source not in name:
            raise ValueError('Definition contains a resource outside the source campaign: ' + name)
        sections = {}
        for key, section in (('strings', 'STRG'), ('translations', 'TRAN')):
            before = graph[key]
            after = [value.replace(source, target) for value in before]
            if before != after:
                sections[section] = encode_strings(after)
                changes.extend({'resource': name, 'table': key, 'index': index, 'before': old, 'after': new}
                               for index, (old, new) in enumerate(zip(before, after)) if old != new)
        updated_objects = copy.deepcopy(graph['objects'])
        object_changes = False
        for obj in updated_objects:
            if obj['class'] in IDENTITY_CLASSES:
                value = _value(obj, 'GUID')
                if value.get('value_hex') != source_guid:
                    raise ValueError('Native campaign GUID precondition changed')
                value['value_hex'] = target_guid
                object_changes = True
                changes.append({'resource': name, 'object_id': obj['id'], 'class': obj['class'],
                                'property': 'GUID', 'before': source_guid, 'after': target_guid})
            trophy_field = TROPHY_FIELDS.get(obj['class'])
            if trophy_field:
                value = _value(obj, trophy_field)
                previous = value.get('value')
                if previous in mapping:
                    value['value'] = mapping[previous]
                    object_changes = True
                    changes.append({'resource': name, 'object_id': obj['id'], 'class': obj['class'],
                                    'property': trophy_field, 'before': previous, 'after': value['value']})
        if object_changes:
            sections['OBJE'] = encode_objects(updated_objects)
        result = rebuild_sections(document, sections) if sections else payloads[name]
        outputs[name.replace(source, target)] = result
    result = pack_v3(outputs)
    report = {'format': 'agf-native-definition-clone/v1', 'source': source, 'target': target,
              'source_guid': source_guid, 'target_guid': target_guid,
              'trophy_ids': {str(key): value for key, value in mapping.items()}, 'changes': changes,
              'source_resources': {name: sha256(raw) for name, raw in payloads.items()},
              'output_sha256': sha256(result), 'runtime_verified': False}
    report['verification'] = verify_native_definition_clone(payloads, result, report)
    return result, report


def _semantics(graph):
    return {key: value for key, value in graph.items() if key in
            {'classes', 'properties', 'strings', 'translations', 'imports', 'exports', 'objects'}}


def verify_native_definition_clone(original, cloned, report):
    source, target = report['source'], report['target']
    if source == target or report['source_guid'] == report['target_guid']:
        raise ValueError('Clone identity is not independent')
    if {name: sha256(raw) for name, raw in original.items()} != report['source_resources']:
        raise ValueError('Native source Definition changed since cloning')
    repack(cloned, {})
    output = _payloads(cloned)
    if set(output) != {name.replace(source, target) for name in original}:
        raise ValueError('Unexpected native Definition resource inventory')
    reverse_trophies = {new: int(old) for old, new in report['trophy_ids'].items()}
    checked_guids = 0
    unchanged = 0
    for original_name, raw in original.items():
        emitted = output[original_name.replace(source, target)]
        if emitted == raw:
            unchanged += 1
        before_document, before = decode(raw)
        after_document, after = decode(emitted)
        before_sections = {section.name: before_document.full_data[section.offset:section.offset + section.size]
                           for section in before_document.sections}
        after_sections = {section.name: after_document.full_data[section.offset:section.offset + section.size]
                          for section in after_document.sections}
        if set(before_sections) != set(after_sections):
            raise ValueError('Unexpected native section inventory in ' + original_name)
        if any(before_sections[name] != after_sections[name] for name in before_sections if name not in {'OBJE', 'STRG', 'TRAN'}):
            raise ValueError('Unexpected native opaque section change in ' + original_name)
        if before_document.full_data[:16] != after_document.full_data[:16] or before_document.full_data[24:32] != after_document.full_data[24:32]:
            raise ValueError('Unexpected native header change in ' + original_name)
        # Reverse only the specified campaign/trophy identities. All rules,
        # branches, links, timings, default omissions and unknown fields compare.
        for table in ('strings', 'translations'):
            after[table] = [value.replace(target, source) for value in after[table]]
        for table in ('imports', 'exports'):
            after[table] = {index: value.replace(target, source) for index, value in after[table].items()}
        def unmap(value):
            if isinstance(value, dict):
                if value.get('type') in {'strg_ref', 'file_strg_ref', 'trans_ref'} and isinstance(value.get('value'), str):
                    value['value'] = value['value'].replace(target, source)
                for nested in value.values():
                    unmap(nested)
            elif isinstance(value, list):
                for nested in value:
                    unmap(nested)
        unmap(after['objects'])
        for obj in after['objects']:
            if obj['class'] in IDENTITY_CLASSES:
                value = _value(obj, 'GUID')
                if value.get('value_hex') != report['target_guid']:
                    raise ValueError('Unexpected target campaign GUID')
                value['value_hex'] = report['source_guid']
                checked_guids += 1
            trophy_field = TROPHY_FIELDS.get(obj['class'])
            if trophy_field:
                value = _value(obj, trophy_field)
                before_obj = before['objects'][obj['id']]
                previous = _value(before_obj, trophy_field)['value']
                expected = report['trophy_ids'].get(str(previous))
                if value.get('value') != expected or expected not in reverse_trophies:
                    raise ValueError('Unexpected unisolated trophy or achievement identity')
                value['value'] = previous
        if _semantics(before) != _semantics(after):
            raise ValueError('Unexpected native gameplay semantic change in ' + original_name)
    if checked_guids != 2:
        raise ValueError('Native clone must isolate exactly the scenario and map GUIDs')
    return {'resources_verified': len(output), 'byte_identical_payloads': unchanged,
            'guid_fields_verified': checked_guids, 'gameplay_preserved': True, 'runtime_verified': False}
