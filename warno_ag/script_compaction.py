"""Explicit-root graph compaction for the pinned GDScript CNDF layout."""
import copy
import struct

from .cndf import decode, encode_objects, rebuild_sections


def verify_compaction(before, after, roots, mapping):
    _, source = decode(before)
    _, target = decode(after)
    if (not isinstance(roots, list) or not roots or len(set(roots)) != len(roots)
            or any(type(index) is not int or not 0 <= index < len(source['objects']) for index in roots)):
        raise ValueError('Compaction verification requires valid roots')
    if (not isinstance(mapping, dict)
            or any(type(key) is not int or type(value) is not int for key, value in mapping.items())
            or set(mapping.values()) != set(range(len(target['objects'])))
            or len(mapping) != len(target['objects'])):
        raise ValueError('Invalid compaction mapping')

    def references(value):
        if isinstance(value, dict):
            if value.get('type') == 'obj_ref':
                yield value['object_id']
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    closure = set()
    pending = list(roots)
    while pending:
        index = pending.pop()
        if index not in closure:
            closure.add(index)
            pending.extend(references(source['objects'][index]['properties']))
    if set(mapping) != closure:
        raise ValueError('Compaction mapping does not equal root closure')
    inverse = {value: key for key, value in mapping.items()}
    used_imports = set()

    def collect_imports(value):
        if isinstance(value, dict):
            if value.get('type') == 'trans_ref':
                used_imports.add(value['index'])
            for child in value.values():
                collect_imports(child)
        elif isinstance(value, list):
            for child in value:
                collect_imports(child)

    for index in closure:
        collect_imports(source['objects'][index]['properties'])
    if not used_imports <= source['imports'].keys():
        raise ValueError('Compaction source contains unresolved import indices')
    import_inverse = dict(enumerate(sorted(used_imports)))
    expected_imports = {index: source['imports'][old_index]
                        for index, old_index in import_inverse.items()}
    if target['imports'] != expected_imports:
        raise ValueError('Compaction changed reference tables or non-dense import indices')

    def restore(value):
        if isinstance(value, dict):
            if value.get('type') == 'obj_ref':
                value['object_id'] = inverse[value['object_id']]
            elif value.get('type') == 'trans_ref':
                if value['index'] not in import_inverse:
                    raise ValueError('Compaction contains out-of-bounds import index')
                value['index'] = import_inverse[value['index']]
            for child in value.values():
                restore(child)
        elif isinstance(value, list):
            for child in value:
                restore(child)

    for old_id, new_id in mapping.items():
        restored = copy.deepcopy(target['objects'][new_id])
        restored['id'] = old_id
        restored['offset'] = source['objects'][old_id]['offset']
        restore(restored['properties'])
        if restored != source['objects'][old_id]:
            raise ValueError(f'Compaction changed object {old_id}')
    expected_exports = {mapping[index]: path for index, path in source['exports'].items()
                        if index in closure}
    if target['exports'] != expected_exports or target['imports'] != expected_imports:
        raise ValueError('Compaction changed reference tables')
    for table in ('classes', 'properties', 'strings', 'translations'):
        if source.get(table) != target.get(table):
            raise ValueError('Compaction changed schema table: ' + table)
    return {'objects': len(closure), 'roots': [mapping[index] for index in roots],
            'imports': len(expected_imports), 'exports': len(expected_exports)}


def compact_script(raw, roots):
    document, graph = decode(raw)
    sections = {section.name: section for section in document.sections}
    expected = {'OBJE', 'TOPO', 'CHNK', 'CLAS', 'PROP', 'STRG', 'TRAN', 'IMPR', 'EXPR'}
    if set(sections) != expected or sections['CHNK'].size != 8:
        raise ValueError('Unsupported script compaction section layout')
    if (not isinstance(roots, list) or not roots
            or any(type(index) is not int or not 0 <= index < len(graph['objects']) for index in roots)
            or len(set(roots)) != len(roots)):
        raise ValueError('Script compaction requires unique valid explicit roots')

    def references(value):
        if isinstance(value, dict):
            if value.get('type') == 'obj_ref':
                yield value['object_id']
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    kept = set()
    pending = list(roots)
    while pending:
        index = pending.pop()
        if index in kept:
            continue
        kept.add(index)
        pending.extend(references(graph['objects'][index]['properties']))
    mapping = {index: number for number, index in enumerate(sorted(kept))}
    imports = set()

    def collect_imports(value):
        if isinstance(value, dict):
            if value.get('type') == 'trans_ref':
                imports.add(value['index'])
            for child in value.values():
                collect_imports(child)
        elif isinstance(value, list):
            for child in value:
                collect_imports(child)

    for index in kept:
        collect_imports(graph['objects'][index]['properties'])
    if not imports <= graph['imports'].keys():
        raise ValueError('Compaction source contains unresolved import indices')
    import_mapping = {index: number for number, index in enumerate(sorted(imports))}

    def remap(value):
        if isinstance(value, dict):
            if value.get('type') == 'obj_ref':
                value['object_id'] = mapping[value['object_id']]
            elif value.get('type') == 'trans_ref':
                value['index'] = import_mapping[value['index']]
            for child in value.values():
                remap(child)
        elif isinstance(value, list):
            for child in value:
                remap(child)

    objects = []
    for old_id, new_id in mapping.items():
        obj = copy.deepcopy(graph['objects'][old_id])
        obj['id'] = new_id
        remap(obj['properties'])
        objects.append(obj)
    exports = {mapping[index]: path for index, path in graph['exports'].items() if index in kept}
    kept_imports = {import_mapping[index]: graph['imports'][index] for index in sorted(imports)}
    from .bruderkrieg import _reference_table_sections
    replacements = _reference_table_sections(document, kept_imports)
    export_sections = _reference_table_sections(document, exports, 'EXPR')
    if replacements['TRAN'] != export_sections['TRAN']:
        raise ValueError('Compaction unexpectedly introduced translation segments')
    replacements.update(export_sections)
    chunk = bytearray(document.full_data[sections['CHNK'].offset:sections['CHNK'].offset + sections['CHNK'].size])
    struct.pack_into('<I', chunk, 4, len(objects))
    top = [obj['id'] for obj in objects if obj['is_top_object']]
    replacements.update({'OBJE': encode_objects(objects), 'CHNK': bytes(chunk),
                         'TOPO': struct.pack('<' + 'I' * len(top), *top)})
    result = rebuild_sections(document, replacements)
    _, verified = decode(result)
    if verified['exports'] != exports or verified['imports'] != kept_imports:
        raise ValueError('Script compaction reference-table mismatch')
    verify_compaction(raw, result, roots, mapping)
    return result, {'object_map': mapping, 'import_map': import_mapping,
                    'root_ids': [mapping[index] for index in roots],
                    'removed_objects': len(graph['objects']) - len(objects),
                    'removed_imports': len(graph['imports']) - len(kept_imports),
                    'removed_exports': len(graph['exports']) - len(exports)}
