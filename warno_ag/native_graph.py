"""Small typed graph editor that preserves old objects while appending private copies."""
import copy
import struct

from .bruderkrieg import _reference_table_sections
from .cndf import decode, encode_objects, encode_strings, rebuild_sections


class NativeGraphEditor:
    def __init__(self, raw):
        self.document, self.graph = decode(raw)
        self.original_count = len(self.graph['objects'])
        self.original_properties = len(self.graph['properties'])
        self.original_classes = len(self.graph['classes'])
        self.original_imports = dict(self.graph['imports'])
        self.original_exports = dict(self.graph['exports'])
        self.objects = self.graph['objects']
        self.strings = self.graph['strings']
        self.exports = self.graph['exports']
        self.imports = self.graph['imports']

    def named(self, path):
        found = [self.objects[index] for index, value in self.exports.items() if value == path]
        if len(found) != 1:
            raise ValueError('Missing or ambiguous native export: ' + path)
        return found[0]

    def add(self, class_name, *, export=None):
        if class_name not in self.graph['classes']:
            self.graph['classes'].append(class_name)
        obj = {'id': len(self.objects), 'class': class_name, 'class_id': self.graph['classes'].index(class_name),
               'is_top_object': export is not None, 'properties': []}
        self.objects.append(obj)
        if export is not None:
            if export in self.exports.values(): raise ValueError('Native export already exists: ' + export)
            self.exports[obj['id']] = export
        return obj

    def property(self, obj, name):
        found = [prop for prop in obj['properties'] if prop['property_name'] == name]
        if len(found) > 1:
            raise ValueError('Ambiguous native property: ' + name)
        return found[0] if found else None

    def string(self, value):
        if value not in self.strings:
            self.strings.append(value)
        return self.strings.index(value)

    def set_value(self, obj, name, value):
        prop = self.property(obj, name)
        if prop is None:
            matches = [i for i, row in enumerate(self.graph['properties']) if row['name'] == name and row['class'] == obj['class']]
            if not matches:
                index = len(self.graph['properties'])
                self.graph['properties'].append({'name': name, 'class': obj['class'], 'class_id': obj['class_id']})
            else:
                index = matches[0]
            prop = {'property_id': index, 'property_name': name, 'value': copy.deepcopy(value)}
            obj['properties'].append(prop)
        else:
            prop['value'] = copy.deepcopy(value)

    def set_scalar(self, obj, name, value, *, kind=None):
        current = self.property(obj, name)
        wire = copy.deepcopy(current['value']) if current else None
        if wire is None:
            kind = kind or ('bool' if type(value) is bool else 'int32' if type(value) is int else 'float32' if type(value) is float else 'strg_ref')
            type_id = {'bool': 0, 'int32': 2, 'uint32': 3, 'float32': 5, 'strg_ref': 7, 'loc_hash': 29, 'guid': 26}[kind]
            wire = {'type_id': type_id, 'type': kind, 'reference_prefix': False}
        if wire['type'] in {'strg_ref', 'file_strg_ref'}:
            if not isinstance(value, str):
                raise ValueError('Native string property requires text')
            wire.update(index=self.string(value), value=value)
        elif wire['type'] in {'guid', 'loc_hash'}:
            wire['value_hex'] = value
        else:
            wire['value'] = value
        self.set_value(obj, name, wire)

    def reference(self, identifier):
        return {'type_id': 0xbbbbbbbb, 'type': 'obj_ref', 'reference_prefix': True,
                'object_id': identifier, 'class_id': self.objects[identifier]['class_id']}

    @staticmethod
    def sequence(values):
        return {'type_id': 17, 'type': 'list', 'reference_prefix': False, 'length': len(values), 'items': list(values)}

    def clone(self, identifier, *, keep_classes=(), export=None):
        mapping = {}
        def visit(old_id):
            if old_id in mapping:
                return mapping[old_id]
            original = self.objects[old_id]
            if original['class'] in keep_classes:
                return old_id
            copied = copy.deepcopy(original)
            copied['id'] = len(self.objects)
            copied['is_top_object'] = False
            mapping[old_id] = copied['id']
            self.objects.append(copied)
            def remap(value):
                if isinstance(value, dict):
                    if value.get('type') == 'obj_ref' and value.get('object_id') != 0xffffffff:
                        value['object_id'] = visit(value['object_id'])
                    for item in value.values():
                        remap(item)
                elif isinstance(value, list):
                    for item in value:
                        remap(item)
            remap(copied['properties'])
            return copied['id']
        new_id = visit(identifier)
        if export:
            if export in self.exports.values():
                raise ValueError('Native export already exists: ' + export)
            self.exports[new_id] = export
            self.objects[new_id]['is_top_object'] = True
        return new_id, mapping

    def save(self):
        sections = {section.name: self.document.full_data[section.offset:section.offset + section.size] for section in self.document.sections}
        objects = encode_objects(self.objects)
        changed = {}
        if objects != sections['OBJE']:
            changed['OBJE'] = objects
        strings = encode_strings(self.strings)
        if strings != sections.get('STRG', b''):
            changed['STRG'] = strings
        if len(self.objects) != self.original_count:
            chunk = bytearray(sections['CHNK'])
            struct.pack_into('<I', chunk, 4, len(self.objects))
            changed['CHNK'] = bytes(chunk)
            changed['TOPO'] = sections.get('TOPO', b'') + b''.join(struct.pack('<I', obj['id']) for obj in self.objects[self.original_count:] if obj['is_top_object'])
        if len(self.graph['properties']) != self.original_properties:
            props = bytearray(sections['PROP'])
            for row in self.graph['properties'][self.original_properties:]:
                name = row['name'].encode('latin1')
                props.extend(struct.pack('<I', len(name)) + name + struct.pack('<I', row['class_id']))
            changed['PROP'] = bytes(props)
        if len(self.graph['classes']) != self.original_classes:
            classes = bytearray(sections['CLAS'])
            for name in self.graph['classes'][self.original_classes:]:
                raw = name.encode('latin1'); classes.extend(struct.pack('<I', len(raw)) + raw)
            changed['CLAS'] = bytes(classes)
        if self.imports != self.original_imports:
            # New private objects can reference newly appended imports.
            changed.update(_reference_table_sections(self.document, self.imports, 'IMPR'))
        result = rebuild_sections(self.document, changed) if changed else self.document.raw_data
        for section, values, original in (('EXPR', self.exports, self.original_exports),):
            if values != original:
                document, _ = decode(result)
                result = rebuild_sections(document, _reference_table_sections(document, values, section))
        return result
