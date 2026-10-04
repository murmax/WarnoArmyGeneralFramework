"""Append named, visible marker labels without replacing stock campaign scripts."""
import copy
import hashlib
import uuid

from .cndf import decode
from .current_campaign import _int32_words
from .map_registration import append_map_items
from .native_graph import NativeGraphEditor


NAMESPACE = uuid.UUID('2b296777-2892-5850-b63f-0d2cd979652d')


def native_marker_identity(target, marker_id):
    key = target + ':' + marker_id
    return {'guid': uuid.uuid5(NAMESPACE, key).hex,
            'name': 'AGFMarker_' + hashlib.sha256(key.encode()).hexdigest()[:16]}


def add_native_markers(script_raw, details, markers, target):
    if not markers:
        return script_raw, details, {}
    editor = NativeGraphEditor(script_raw)
    before_count = len(editor.objects)
    turn_setters = {obj['id'] for obj in editor.objects if obj['class'] == 'TGDDescriptorSetNumberMaxTurn'}
    kernels = [obj for obj in editor.objects if obj['class'] == 'TGDDescriptorSimultaneous'
               and editor.property(obj, 'SubActions') is not None
               and any(ref.get('object_id') in turn_setters for ref in editor.property(obj, 'SubActions')['value']['items'])]
    if not kernels:
        for sequence in editor.objects:
            prop = editor.property(sequence, 'SubActions')
            if sequence['class'] != 'TGDDescriptorSequential' or prop is None:
                continue
            actions = prop['value']['items']
            if actions and any(ref.get('object_id') in turn_setters for ref in actions[:-1]):
                last = editor.objects[actions[-1]['object_id']]
                if last['class'] == 'TGDDescriptorSimultaneous':
                    kernels.append(last)
    if len(kernels) != 1:
        raise ValueError('Native markers require an unambiguous initialized strategic kernel')
    kernel = kernels[0]
    actions = copy.deepcopy(editor.property(kernel, 'SubActions')['value']['items'])
    camps = [editor.reference(obj['id']) for obj in editor.objects if obj['class'] == 'TGDVariableCamp' and obj['is_top_object']]
    rows, localized, names = [], {}, set()
    for marker in markers:
        if set(marker) != {'id', 'name', 'position'} or not marker['name'] or marker['id'] in names:
            raise ValueError('Invalid or duplicate native marker')
        names.add(marker['id'])
        identity = native_marker_identity(target, marker['id'])
        guid, name = identity['guid'], identity['name']
        export = '$/GDScript/GdItems/Tags/' + name
        existing = [index for index, path in editor.exports.items() if path == export]
        if len(existing) > 1:
            raise ValueError('Private map marker tag is ambiguous')
        if existing:
            tag = editor.objects[existing[0]]
            values = [editor.property(tag, 'GUID' + str(number)) for number in range(1, 5)]
            if (tag['class'] != 'TGDTagPosition' or any(value is None for value in values)
                    or [value['value'].get('value') for value in values]
                        != list(_int32_words(guid))):
                raise ValueError('Private map marker conflicts with its production tag')
        else:
            tag = editor.add('TGDTagPosition', export=export)
            for number, word in enumerate(_int32_words(guid), 1):
                editor.set_scalar(tag, 'GUID' + str(number), word, kind='int32')
        key = hashlib.sha256((target + ':marker-text:' + marker['id']).encode()).digest()[:8].hex()
        localized[key] = marker['name']
        label = editor.add('TGDDescriptorDrawLabelOnPosition')
        editor.set_value(label, 'Position', editor.reference(tag['id']))
        editor.set_scalar(label, 'FoldedText', key, kind='loc_hash')
        editor.set_scalar(label, 'Text', key, kind='loc_hash')
        editor.set_scalar(label, 'LabelComponent', 'fixed')
        editor.set_value(label, 'ListVariablesForFoldedText', editor.sequence([]))
        editor.set_value(label, 'VisibleByCamps', editor.sequence(camps))
        actions.append(editor.reference(label['id']))
        rows.append({'kind': 'position', 'name': name, 'guid': guid,
                     'position': [marker['position']['x'], marker['position']['y']]})
    editor.set_value(kernel, 'SubActions', editor.sequence(actions))
    result = editor.save()
    _, before = decode(script_raw); _, after = decode(result)
    for old, new in zip(before['objects'], after['objects'][:before_count]):
        if old['id'] == kernel['id']:
            continue
        if {key: value for key, value in old.items() if key != 'offset'} != {key: value for key, value in new.items() if key != 'offset'}:
            raise ValueError('Marker registration changed original script behavior')
    updated = dict(details)
    for path in ('Items.sav', 'out/LevelDesign.ndfbin'):
        updated[path] = append_map_items(details[path], rows)
    return result, updated, localized
