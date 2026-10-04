"""Emit isolated LevelBuild point scenes using inspected native schema tables."""
import math
import re
import struct

from .cndf import decode, encode_objects, encode_strings, rebuild_sections


def write_point_scene(template, placements):
    """Write native transforms, without guessing height units or ground adaptation."""
    document, graph = decode(template)
    if graph['exports'] or graph['imports']:
        raise ValueError('Scene schema template must not have imports or exports')
    if not isinstance(placements, list):
        raise ValueError('Scene placements must be a list')
    allowed_sections = {'OBJE', 'TOPO', 'CHNK', 'CLAS', 'PROP', 'STRG', 'TRAN', 'IMPR', 'EXPR'}
    if any(section.name not in allowed_sections for section in document.sections):
        raise ValueError('Unsupported scene schema section')
    classes = {name: index for index, name in enumerate(graph['classes'])}
    properties = {(prop['class'], prop['name']): prop['id'] for prop in graph['properties']}
    root_class = 'TSaveDescriptorItemList'
    point_class = 'TSaveDescriptorItemPoint'
    required = [(root_class, 'Items')] + [(point_class, name) for name in
                                          ('AxeX', 'AxeY', 'AxeZ', 'AxeT', 'SceneryDescriptor')]
    if any(key not in properties for key in required):
        raise ValueError('Missing native point scene schema')
    strings = []
    objects = []

    def value(type_id, type_name, data):
        return {'type_id': type_id, 'type': type_name, 'reference_prefix': False, 'value': data}

    def object_record(identifier, class_name, fields, top=False):
        return {'id': identifier, 'class': class_name, 'class_id': classes[class_name],
                'is_top_object': top, 'properties': [
                    {'property_id': properties[(class_name, name)], 'property_name': name,
                     'value': data} for name, data in fields]}

    references = []
    for placement in placements:
        if not isinstance(placement, dict) or set(placement) != {
                'asset', 'native_position', 'rotation_degrees', 'scale'}:
            raise ValueError('Native scene placement fields mismatch')
        asset = placement['asset']
        if not isinstance(asset, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', asset) is None:
            raise ValueError('Invalid scenery registration name')
        position = placement['native_position']
        if not isinstance(position, list) or len(position) != 3:
            raise ValueError('Native scene position requires three coordinates')
        numbers = position + [placement['rotation_degrees'], placement['scale']]
        if any(type(number) not in (int, float) or not math.isfinite(number)
               or abs(number) > 1e30 for number in numbers):
            raise ValueError('Native scene transform must be finite float32 data')
        scale = placement['scale']
        if scale <= 0 or not 0 <= placement['rotation_degrees'] <= 360:
            raise ValueError('Invalid native scene scale or rotation')
        angle = math.radians(placement['rotation_degrees'])
        cosine = math.cos(angle) * scale
        sine = math.sin(angle) * scale
        if asset not in strings:
            strings.append(asset)
        descriptor = dict(value(7, 'strg_ref', asset), index=strings.index(asset))
        fields = [('AxeX', value(11, 'vec3', [cosine, sine, 0.0])),
                  ('AxeY', value(11, 'vec3', [-sine, cosine, 0.0])),
                  ('AxeZ', value(11, 'vec3', [0.0, 0.0, float(scale)])),
                  ('AxeT', value(11, 'vec3', [float(number) for number in position])),
                  ('SceneryDescriptor', descriptor)]
        identifier = len(objects) + 1
        objects.append(object_record(identifier, point_class, fields))
        references.append({'type_id': 3149642683, 'type': 'obj_ref', 'reference_prefix': True,
                           'object_id': identifier, 'class_id': classes[point_class]})
    items = {'type_id': 17, 'type': 'list', 'reference_prefix': False,
             'length': len(references), 'items': references}
    objects.insert(0, object_record(0, root_class, [('Items', items)], top=True))
    result = rebuild_sections(document, {
        'OBJE': encode_objects(objects), 'TOPO': struct.pack('<I', 0),
        'CHNK': struct.pack('<II', 0, len(objects)), 'STRG': encode_strings(strings),
        'TRAN': b'', 'IMPR': b'', 'EXPR': b'',
    })
    _, output = decode(result)
    if len(output['objects']) != len(placements) + 1:
        raise ValueError('Native point scene readback count mismatch')
    return result
