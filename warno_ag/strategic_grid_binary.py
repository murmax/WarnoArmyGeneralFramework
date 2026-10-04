"""Codec for TStrategicMapGridData; tile bytes remain opaque engine data."""

from .cndf import decode, rebuild_objects


TERRAIN_CODES = {
    'StrategicPlain': 4,
    'StrategicForest': 8,
    'StrategicSemiUrban': 12,
    'StrategicUrban': 16,
    'StrategicWater': 20,
}
DEFAULT_TERRAIN = 'StrategicPlain'


def _properties(graph):
    if len(graph['objects']) != 1 or graph['objects'][0]['class'] != 'TStrategicMapGridData':
        raise ValueError('Expected one TStrategicMapGridData object')
    obj = graph['objects'][0]
    if not obj['is_top_object']:
        raise ValueError('Strategic grid must be a top object')
    properties = {prop['property_name']: prop['value'] for prop in obj['properties']}
    if len(obj['properties']) != 2 or set(properties) != {'Size', 'TileCompressedData'}:
        raise ValueError('Unsupported strategic grid property schema')
    if properties['Size']['type'] != 'int2' or properties['TileCompressedData']['type'] != 'list':
        raise ValueError('Unsupported strategic grid property types')
    return properties


def read_grid(raw):
    _, graph = decode(raw)
    properties = _properties(graph)
    width, height = properties['Size']['value']
    if width <= 0 or height <= 0:
        raise ValueError('Invalid strategic grid dimensions')
    values = properties['TileCompressedData']
    if values['length'] != width * height or len(values['items']) != width * height:
        raise ValueError('Strategic grid tile count differs from Size')
    if any(item['type'] != 'int8' or not -128 <= item['value'] <= 127 for item in values['items']):
        raise ValueError('Strategic grid tiles must be signed bytes')
    return {'width': width, 'height': height,
            'tiles': [item['value'] & 255 for item in values['items']]}


def write_grid(template, width, height, tiles):
    read_grid(template)
    if any(type(size) is not int or not 1 <= size <= 2147483647 for size in (width, height)):
        raise ValueError('Strategic grid dimensions must be positive int32 values')
    if not isinstance(tiles, (list, tuple, bytes)) or len(tiles) != width * height:
        raise ValueError('Strategic grid requires exactly width * height tile bytes')
    if any(type(value) is not int or not 0 <= value <= 255 for value in tiles):
        raise ValueError('Strategic grid tile values must be bytes')
    doc, graph = decode(template)
    properties = _properties(graph)
    properties['Size']['value'] = [width, height]
    properties['TileCompressedData']['length'] = len(tiles)
    properties['TileCompressedData']['items'] = [
        {'type_id': 1, 'type': 'int8', 'reference_prefix': False,
         'value': value if value < 128 else value - 256} for value in tiles]
    result = rebuild_objects(doc, graph)
    if read_grid(result) != {'width': width, 'height': height, 'tiles': list(tiles)}:
        raise ValueError('Strategic grid binary readback mismatch')
    return result


def write_uniform_grid(template, width, height, terrain=DEFAULT_TERRAIN):
    if terrain not in TERRAIN_CODES:
        raise ValueError(f'Unsupported strategic terrain: {terrain}')
    return write_grid(template, width, height, [TERRAIN_CODES[terrain]] * (width * height))
