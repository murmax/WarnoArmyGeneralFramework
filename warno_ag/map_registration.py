"""Append independently authored map points to editor and runtime databases."""
import math
import re

from .cndf import append_graph_objects, decode, encode_strings, rebuild_sections


KINDS = {
    'spawn': ('TGameDesignAddOn_Spawn', 'Tag', {'side', 'unit_export'}),
    'position': ('TGameDesignAddOn_Name', 'Tag', set()),
    'label': ('TGameDesignAddOn_LabelOnMap', 'Tag_LabelOnMap', {'token', 'component'}),
    'influence': ('TGameDesignAddOn_InfluencePoint', 'Tag_InfluencePoint', {'side', 'value'}),
    'battleground': ('TGameDesignAddOn_SpecificStrategicBattleground',
                    'Tag_SpecificStrategicBattleground', {'battleground_name'}),
    'detector': ('TGameDesignAddOn_CircularZone', 'Tag_CircularZone', {'radius_gru'}),
}


def campaign_map_items(compiled):
    from .authoring import _guid
    campaign_id = compiled['campaign']['id']
    rows = []
    for deployment in compiled['deployments']:
        name = deployment['adapter_slot']['name']
        rows.append({'kind': 'spawn', 'name': name,
                     'guid': _guid('deployment', campaign_id, deployment['id']),
                     'side': deployment['side'], 'position': deployment['position'],
                     'unit_export': deployment['unit_export']})
    for airfield in compiled.get('aviation', {}).get('airfields', []):
        rows.append({'kind': 'spawn', 'name': airfield['spawn_slot'],
                     'guid': airfield['guid'], 'side': airfield['side'],
                     'position': airfield['position'], 'unit_export': airfield['unit_export']})
    for row in compiled['map']['flags'] + compiled['map']['runtime_positions']:
        rows.append({'kind': 'position', 'name': row['adapter_slot']['name'],
                     'position': row['position'], 'guid': row['guid']})
    for row in compiled['map']['influence_sources']:
        name = row['adapter_slot']['name']
        rows.append({'kind': 'influence', 'name': name, 'position': row['position'],
                     'guid': _guid('map-influence', campaign_id, name),
                     'side': row['side'], 'value': row['value']})
    for row in compiled['map']['labels']:
        rows.append({'kind': 'label', 'name': row['adapter_slot']['name'],
                     'position': row['position'], 'guid': _guid('map-label', campaign_id, row['id']),
                     'token': row['token'], 'component': {'small': 'LabelVille_03',
                     'medium': 'LabelVille_02', 'large': 'LabelVille_01'}[row['size']]})
    strategic_map = compiled.get('adapter', {}).get('strategic_map')
    if compiled.get('aviation',{}).get('withdrawal_version') == 2:
        rows.append({'kind':'detector', 'name':'AGFW_AirWingTracking',
                     'guid':_guid('air-wing-detector',campaign_id,'all'),
                     'position':[655360.0,655360.0], 'radius_gru':32768.0})
    if strategic_map and strategic_map.get('tactical_policy', 'specific') == 'specific':
        left, bottom, right, top = strategic_map['bounds']
        width = strategic_map['dimensions']['width']
        height = strategic_map['dimensions']['height']
        cell_width = (right - left) / width
        cell_height = (top - bottom) / height
        for row in range(height):
            for column in range(width):
                item_id = f'r{row}c{column}'
                rows.append({
                    'kind': 'battleground', 'name': f'AGFW_Battle_{item_id}',
                    'guid': _guid('map-battleground', campaign_id, item_id),
                    'position': [left + (column + 0.5) * cell_width,
                                 bottom + (row + 0.5) * cell_height],
                    'battleground_name': strategic_map['fixed_battleground'],
                })
    elif strategic_map and strategic_map['tactical_policy'] != 'terrain_pool':
        raise ValueError('Unsupported strategic map tactical policy')
    return rows


def dynamic_script_registration_contract(graph, compiled):
    from .current_campaign import _int32_words
    paths = {path: index for index, path in graph['exports'].items()}
    guids = set()
    for row in campaign_map_items(compiled):
        if row['kind'] not in ('spawn', 'position', 'battleground', 'detector'):
            continue
        if row['kind'] == 'spawn':
            folder = 'Camp_1' if row['side'] == 'nato' else 'Camp_0'
        elif row['kind'] == 'battleground':
            folder = 'SpecificStrategicBattleground'
        elif row['kind'] == 'detector':
            folder = 'CircularZones'
        else:
            folder = 'Tags'
        path = '$/GDScript/GdItems/' + folder + '/' + row['name']
        if path not in paths:
            raise ValueError('Missing dynamic registration: ' + path)
        obj = graph['objects'][paths[path]]
        expected_class = 'TGDTagUnitGroup' if row['kind'] == 'spawn' else 'TGDTagDetecteur' if row['kind']=='detector' else 'TGDTagPosition'
        fields = {prop['property_name']: prop['value'].get('value') for prop in obj['properties']}
        words = tuple(fields.get('GUID' + str(index)) for index in range(1, 5))
        if (obj['class'] != expected_class or not obj['is_top_object']
                or words != tuple(_int32_words(row['guid'])) or words in guids):
            raise ValueError('Invalid dynamic registration: ' + path)
        guids.add(words)


def append_map_items(raw, rows, *, camp_by_side=None):
    camp_by_side = camp_by_side or {'nato': 1, 'pact': 0}
    if set(camp_by_side) != {'nato', 'pact'} or set(camp_by_side.values()) != {0, 1}:
        raise ValueError('Map registration requires an unambiguous source coalition-to-camp mapping')
    document, graph = decode(raw)
    if not isinstance(rows, list):
        raise ValueError('Map registrations must be a list')
    if not rows:
        return raw
    editor = 'TSaveDescriptorItemPoint' in graph['classes']
    point_class = 'TSaveDescriptorItemPoint' if editor else 'TGameDesignItem'
    root_class = 'TSaveDescriptorItemList' if editor else 'TGameDesignDatabase'
    root_field = 'Items' if editor else 'GameDesignItemList'
    roots = [obj for obj in graph['objects'] if obj['class'] == root_class and obj['is_top_object']]
    if len(roots) != 1 or point_class not in graph['classes']:
        raise ValueError('Unsupported map registration database')
    root_list = next((prop['value'] for prop in roots[0]['properties'] if prop['property_name'] == root_field), None)
    if root_list is None or root_list.get('type') != 'list':
        raise ValueError('Map registration root has no item list')
    names = {prop['value']['value'] for obj in graph['objects']
             if obj['class'].startswith('TGameDesignAddOn_') for prop in obj['properties']
             if prop['property_name'] == 'Name'}
    guids = {prop['value']['value_hex'] for obj in graph['objects'] for prop in obj['properties']
             if prop['property_name'] == 'GUID' and prop['value'].get('type') == 'guid'}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('kind'), str) or row['kind'] not in KINDS:
            raise ValueError('Unknown map registration kind')
        expected = {'kind', 'name', 'guid', 'position'} | KINDS[row['kind']][2]
        if set(row) != expected:
            raise ValueError('Invalid map registration fields')
        if not isinstance(row['name'], str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', row['name']):
            raise ValueError('Invalid map registration name')
        if not isinstance(row['guid'], str) or not re.fullmatch(r'[0-9a-f]{32}', row['guid']):
            raise ValueError('Invalid map registration GUID')
        if row['name'] in names or row['guid'] in guids:
            raise ValueError('Duplicate map registration name or GUID')
        names.add(row['name'])
        guids.add(row['guid'])
        position = row['position']
        if (not isinstance(position, list) or len(position) != 2
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in position)):
            raise ValueError('Invalid map registration position')
        if 'side' in row and row['side'] not in ('nato', 'pact'):
            raise ValueError('Invalid map registration side')
        if row['kind'] == 'spawn' and (not isinstance(row['unit_export'], str)
                or not re.fullmatch(r'Descriptor_Unit_[A-Za-z0-9_]+', row['unit_export'])):
            raise ValueError('Invalid map registration unit export')
        if row['kind'] == 'label' and any(not isinstance(row[field], str) or not row[field]
                                        for field in ('token', 'component')):
            raise ValueError('Invalid map registration label')
        if row['kind'] == 'influence' and (type(row['value']) not in (int, float)
                or not math.isfinite(row['value']) or row['value'] <= 0):
            raise ValueError('Invalid map registration influence')
        if row['kind'] == 'battleground' and (
                not isinstance(row['battleground_name'], str)
                or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', row['battleground_name'])):
            raise ValueError('Invalid map registration battleground name')
        if row['kind']=='detector' and (type(row['radius_gru']) not in (int,float)
                or not math.isfinite(row['radius_gru']) or row['radius_gru'] <= 0):
            raise ValueError('Invalid map detector radius')

    property_ids = {(prop['class'], prop['name']): prop['id'] for prop in graph['properties']}
    classes = list(graph['classes'])
    new_classes = []
    new_properties = []
    for kind, extra_field in [('battleground','BattlegroundName'),('detector','RadiusGRU')]:
        if not any(row['kind']==kind for row in rows):
            continue
        class_name = KINDS[kind][0]
        if class_name not in classes:
            classes.append(class_name)
            new_classes.append(class_name)
        key = (class_name, extra_field)
        if key not in property_ids:
            property_ids[key] = len(graph['properties']) + len(new_properties)
            new_properties.append((extra_field, class_name))
    common_ids = {}
    for prop in graph['properties']:
        if prop['class'].startswith('TGameDesignAddOn_') and prop['name'] in ('Name','Ranking','GUID'):
            previous=common_ids.setdefault(prop['name'],prop['id'])
            if previous!=prop['id']:
                raise ValueError('Ambiguous common map add-on schema')
    strings = list(graph['strings'])
    string_indices = {value: index for index, value in enumerate(strings)}
    added = []

    def value(type_id, type_name, data):
        return {'type_id': type_id, 'type': type_name, 'reference_prefix': False, 'value': data}

    def string(text):
        if text not in string_indices:
            string_indices[text] = len(strings)
            strings.append(text)
        return dict(value(7, 'strg_ref', text), index=string_indices[text])

    def reference(obj):
        return {'type_id': 3149642683, 'type': 'obj_ref', 'reference_prefix': True,
                'object_id': obj['id'], 'class_id': obj['class_id']}

    def create(class_name, fields):
        if class_name not in classes:
            raise ValueError('Missing map registration class: ' + class_name)
        obj = {'id': len(graph['objects']) + len(added), 'class': class_name,
               'class_id': classes.index(class_name), 'is_top_object': False, 'properties': []}
        for name, data in fields:
            property_id = property_ids.get((class_name, name))
            if property_id is None and class_name.startswith('TGameDesignAddOn_'):
                property_id = common_ids.get(name)
            if property_id is None:
                raise ValueError('Missing map registration property: ' + class_name + '.' + name)
            obj['properties'].append({'property_id': property_id, 'property_name': name, 'value': data})
        added.append(obj)
        return obj

    for row in rows:
        kind = row['kind']
        class_name, scenery, _ = KINDS[kind]
        ranking = {'spawn': 'Camp_' + str(camp_by_side[row['side']]) if kind == 'spawn' else '',
                   'position': 'Tags', 'label': 'LabelOnMap', 'influence': 'InfluencePoint',
                   'battleground': 'SpecificStrategicBattleground','detector':'CircularZones'}[kind]
        fields = [('Name', string(row['name'])), ('Ranking', string(ranking)),
                  ('GUID', {'type_id': 26, 'type': 'guid', 'reference_prefix': False, 'value_hex': row['guid']})]
        if kind == 'spawn':
            fields += [('AutoNameBase', string(row['name'])),
                       ('Camp', value(2, 'int32', camp_by_side[row['side']])),
                       ('ClassName', string('$/GFX/Pawn/' + row['unit_export']))]
            # Some current scenarios omit this optional property altogether;
            # the game's default is one pawn. Do not fabricate a property id.
            if (class_name, 'NbOfUnitToSpawn') in property_ids:
                fields.append(('NbOfUnitToSpawn', value(2, 'int32', 1)))
            fields += [
                       ('DisableAutoSpawn', value(0, 'bool', False))]
        elif kind == 'label':
            fields += [('Token', string(row['token'])), ('ComponentName', string(row['component']))]
        elif kind == 'battleground':
            fields += [('BattlegroundName', string(row['battleground_name']))]
        elif kind == 'detector':
            fields += [('RadiusGRU',value(5,'float32',float(row['radius_gru'])))]
        elif kind == 'influence':
            fields += [('CommandsInfluenceZone', value(0, 'bool', True)),
                       ('NumAlliance', value(2, 'int32', camp_by_side[row['side']])),
                       ('InfluenceValue', value(5, 'float32', float(row['value']))),
                       ('LossPerSecondWhenIsolated', value(5, 'float32', 1.0))]
        addon = create(class_name, fields)
        position = [float(coordinate) for coordinate in row['position']]
        fields = [('AddOn', reference(addon))]
        if editor:
            fields += [('AxeX', value(11, 'vec3', [1.0, 0.0, 0.0])),
                       ('AxeY', value(11, 'vec3', [0.0, 1.0, 0.0])),
                       ('AxeZ', value(11, 'vec3', [0.0, 0.0, 1.0])),
                       ('AxeT', value(11, 'vec3', position + [0.0])),
                       ('SceneryDescriptor', string(scenery))]
        else:
            fields += [('Position', value(33, 'float2', position))]
        point = create(point_class, fields)
        root_list['items'].append(reference(point))
        root_list['length'] += 1
    staged = rebuild_sections(document, {'STRG': encode_strings(strings)})
    staged_document, _ = decode(staged)
    result = append_graph_objects(staged_document, graph, added, new_classes, new_properties)
    _, final = decode(result)
    if len(final['objects']) != len(graph['objects']) + 2 * len(rows):
        raise ValueError('Map registration object count mismatch')
    return result
