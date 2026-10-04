"""Read the preserved native scenario graph for the editor's advanced browser."""
import json
from pathlib import Path

from .cndf import decode
from .game_resources import GameResources
from .native_campaign_source import NativeCampaignReader, verify_native_snapshot
from .storage import safe_child, sha256
from .native_script_fields import editable_fields, native_capability_inventory


EDITABLE = {'TGDVariableInteger': 'int32', 'TGDVariableFloat': 'float32',
            'TGDVariableBoolean': 'bool'}


def capture_native_script_catalog(source):
    source = Path(source).resolve()
    verify_native_snapshot(source)
    manifest = json.loads((source / 'native-source.json').read_text(encoding='utf-8'))
    script_name = f"NDF/Scenarios/GDScript/{manifest['scenario']}.ndfbin"
    resource = next(row for row in manifest['resources'] if row['scope'] == 'scenario_definition'
                    and row['path'] == script_name)
    return capture_native_script_catalog_files(source / 'native-source.json',
        safe_child(source, resource['file']), safe_child(source, manifest['projection_file']))


def capture_native_script_catalog_files(manifest_path, script_path, projection_path):
    manifest_path, script_path, projection_path = (Path(path).resolve()
                                                   for path in (manifest_path, script_path, projection_path))
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    script_name = f"NDF/Scenarios/GDScript/{manifest['scenario']}.ndfbin"
    resource = next(row for row in manifest['resources'] if row['scope'] == 'scenario_definition'
                    and row['path'] == script_name)
    if sha256(projection_path.read_bytes()) != manifest['projection_sha256']:
        raise ValueError('Captured native projection changed before graph browsing')
    raw = script_path.read_bytes()
    if sha256(raw) != resource['sha256']:
        raise ValueError('Captured native script changed before graph browsing')
    _, graph = decode(raw)
    reader = NativeCampaignReader(GameResources(manifest['game_root']))
    try:
        translations = reader.translations(manifest['scenario'])
    except (FileNotFoundError, KeyError):
        translations = {'ru': {}, 'en': {}}

    def localized(key):
        result = {language: (translations[language].get(key, [{}])[-1].get('text') or '#' + key)
                  for language in ('ru', 'en')}
        result['display'] = result['ru'] if '\ufffd' not in result['ru'] else result['en']
        return result

    def references(value):
        if isinstance(value, dict):
            if value.get('type') == 'obj_ref' and value.get('object_id') != 0xffffffff:
                yield value['object_id']
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    def preview(value):
        if value['type'] == 'loc_hash':
            return {'token': value.get('value_hex'), 'text': localized(value.get('value_hex', ''))}
        if value['type'] == 'obj_ref':
            index = value.get('object_id')
            return {'object_id': index,
                    'class': graph['objects'][index]['class'] if index is not None and index < len(graph['objects']) else None}
        if value['type'] == 'trans_ref':
            return {'path': value.get('value')}
        if 'value' in value:
            return {'value': value['value']}
        if 'value_hex' in value:
            return {'value_hex': value['value_hex']}
        if 'items' in value:
            values = value['items']
            return {'count': len(values), 'sample': [preview(item) for item in values[:4]
                    if isinstance(item, dict) and 'type' in item]}
        return {'type': value['type']}

    def categories(obj, export):
        kind = obj['class'].lower()
        path = (export or '').lower()
        found = []
        if (any(word in kind for word in ('iastrategic', 'strategicmoveandattack', 'strategicdefend'))
                or '/ia/' in path or '/ai/' in path):
            found.append('ai')
        if any(word in kind for word in ('production', 'reinforcement', 'createunitonposition')):
            found.append('production')
        if any(word in kind for word in ('cutscene', 'dialog', 'gereobjectif', 'event', 'drawlabel')):
            found.append('events')
        return found

    parents = {obj['id']: [] for obj in graph['objects']}
    nodes = []
    for obj in graph['objects']:
        export = graph['exports'].get(obj['id'])
        fields = []
        links = []
        for prop in obj['properties']:
            wire = prop['value']
            children = list(dict.fromkeys(references(wire)))
            links.extend(children)
            field_preview = preview(wire)
            if (obj['class'] == 'TGDDescriptorStrategicAddPossibleProduction'
                    and prop['property_name'] == 'Pawns' and wire['type'] == 'list'):
                field_preview['paths'] = [item.get('value') for item in wire['items']]
            fields.append({'name': prop['property_name'], 'type': wire['type'],
                           'preview': field_preview, 'references': children})
        links = list(dict.fromkeys(links))
        for child in links:
            if child in parents:
                parents[child].append(obj['id'])
        editable = (obj['class'] in EDITABLE and any(prop['property_name'] == 'Value'
                    and prop['value']['type'] == EDITABLE[obj['class']] for prop in obj['properties']))
        nodes.append({'id': obj['id'], 'class': obj['class'], 'export': export,
                      'categories': categories(obj, export), 'fields': fields,
                      'references': links, 'editable_value': editable,
                      'editable_fields': editable_fields(obj)})
    for node in nodes:
        node['parents'] = parents[node['id']]
    counts = {key: sum(key in node['categories'] for node in nodes)
              for key in ('ai', 'events', 'production')}
    return {'format': 'agf-native-script-catalog/v1', 'scenario': manifest['scenario'],
            'script_sha256': resource['sha256'], 'projection_sha256': manifest['projection_sha256'],
            'nodes': nodes, 'counts': counts,
            'capabilities': native_capability_inventory(graph, manifest['scenario'], resource['sha256']),
            'runtime_verified': False}
