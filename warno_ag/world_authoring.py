"""Compile an explicitly authored world without baking or installing a map."""
import io
import json
import math
import re
from pathlib import Path, PurePosixPath

from PIL import Image

from .authoring import _read_yaml
from .stock_scenery import POINT_CLASSES
from .storage import safe_child, sha256


SCHEMA = 'agf-world/v1'
MAX_IMAGE_AXIS = 8192


def _fields(value, keys, where, *, optional=()):
    if not isinstance(value, dict) or not set(keys) <= set(value) or not set(value) <= set(keys) | set(optional):
        raise ValueError(where + ' fields mismatch')


def _number(value, where, minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(where + ' must be finite numeric data')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(where + ' is out of range')
    return float(value)


def _size(value, where):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(item) is not int or not 2 <= item <= MAX_IMAGE_AXIS for item in value)):
        raise ValueError(where + ' requires two integer dimensions between 2 and 8192')
    return value


def _source_image(root, relative, role):
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))
            or PurePosixPath(relative).is_absolute()):
        raise ValueError(role + ' must use a confined relative file path')
    path = safe_child(root, relative)
    try:
        raw = path.read_bytes()
        with Image.open(io.BytesIO(raw)) as opened:
            _size(list(opened.size), role)
            if role == 'heightmap':
                if opened.format != 'PNG' or opened.mode not in ('I;16', 'I;16B', 'I;16L'):
                    raise ValueError('heightmap requires a 16-bit grayscale PNG')
            elif opened.format not in ('PNG', 'WEBP') or opened.mode != 'RGB':
                raise ValueError('surface requires an opaque RGB PNG or WebP')
            opened.load()
            image = opened.copy()
            metadata = {'file': relative, 'sha256': sha256(raw),
                        'size': list(opened.size), 'format': opened.format, 'mode': opened.mode}
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('Cannot read ' + role + ': ' + relative) from error
    return image, metadata


def _interpolate(values, horizontal, vertical):
    height = len(values)
    width = len(values[0])
    column = horizontal * (width - 1)
    row = vertical * (height - 1)
    left = min(int(column), width - 2)
    top = min(int(row), height - 2)
    fraction_x = column - left
    fraction_y = row - top
    upper = values[top][left] * (1 - fraction_x) + values[top][left + 1] * fraction_x
    lower = values[top + 1][left] * (1 - fraction_x) + values[top + 1][left + 1] * fraction_x
    return upper * (1 - fraction_y) + lower * fraction_y


def _heightmap(root, specification):
    if not isinstance(specification, dict):
        raise ValueError('heightmap must be a mapping')
    maximum = _number(specification.get('max_altitude_lbu'), 'max_altitude_lbu', minimum=0)
    if maximum == 0:
        raise ValueError('max_altitude_lbu must be positive')
    if maximum * 215 >= 5000:
        raise ValueError('max_altitude_lbu must remain below the 5000-native-unit strategic overlay')
    if 'file' in specification:
        _fields(specification, {'file', 'max_altitude_lbu'}, 'heightmap')
        image, metadata = _source_image(root, specification['file'], 'heightmap')
        return image, {'kind': 'file', 'max_altitude_lbu': maximum, 'input': metadata}
    _fields(specification, {'samples', 'resolution', 'max_altitude_lbu'}, 'heightmap')
    width, height = _size(specification['resolution'], 'heightmap resolution')
    samples = specification['samples']
    if (not isinstance(samples, list) or not 2 <= len(samples) <= MAX_IMAGE_AXIS
            or any(not isinstance(row, list) for row in samples)
            or not 2 <= len(samples[0]) <= MAX_IMAGE_AXIS
            or any(len(row) != len(samples[0]) for row in samples)):
        raise ValueError('heightmap samples must be a rectangular grid of at least 2x2')
    values = [[_number(value, 'height sample', minimum=0, maximum=1) for value in row]
              for row in samples]
    pixels = bytearray(width * height * 2)
    for row in range(height):
        for column in range(width):
            sample = round(_interpolate(values, column / (width - 1), row / (height - 1)) * 65535)
            offset = 2 * (row * width + column)
            pixels[offset:offset + 2] = sample.to_bytes(2, 'little')
    image = Image.frombytes('I;16', (width, height), bytes(pixels))
    return image, {'kind': 'inline', 'max_altitude_lbu': maximum,
                   'samples': values, 'resolution': [width, height]}


def sample_height_lbu(image, bounds, position, max_altitude_lbu):
    if len(position) != 2:
        raise ValueError('Object position requires two coordinates')
    horizontal = (_number(position[0], 'object x') - bounds[0]) / (bounds[2] - bounds[0])
    vertical = (_number(position[1], 'object y') - bounds[1]) / (bounds[3] - bounds[1])
    if not 0 <= horizontal <= 1 or not 0 <= vertical <= 1:
        raise ValueError('Object position is outside world bounds')
    column = horizontal * (image.width - 1)
    row = vertical * (image.height - 1)
    left = min(int(column), image.width - 2)
    top = min(int(row), image.height - 2)
    values = [[image.getpixel((left + delta_x, top + delta_y)) for delta_x in (0, 1)]
              for delta_y in (0, 1)]
    return _interpolate(values, column - left, row - top) / 65535 * max_altitude_lbu


def compile_world(source, destination=None, *, scenery_catalog=None):
    source = Path(source).resolve()
    document = _read_yaml(source)
    _fields(document, {'schema', 'id', 'map_name', 'bounds', 'render_cases',
                       'raster_axes', 'heightmap', 'surface', 'objects'}, 'world',
            optional={'georeference'})
    if document['schema'] != SCHEMA:
        raise ValueError('Unsupported world schema')
    for name, pattern in [('id', r'[a-z][a-z0-9_]*'), ('map_name', r'[A-Za-z][A-Za-z0-9_]*')]:
        if not isinstance(document[name], str) or re.fullmatch(pattern, document[name]) is None:
            raise ValueError('Invalid world ' + name)
    if document['raster_axes'] != 'columns_x_rows_y':
        raise ValueError('World rasters must explicitly declare columns_x_rows_y')
    georeference = document.get('georeference')
    if georeference is not None:
        _fields(georeference, {'crs', 'bounds_wgs84', 'elevation_ceiling_m',
                              'source_sha256', 'raster_origin'}, 'georeference')
        coordinates = georeference['bounds_wgs84']
        if (georeference['crs'] != 'EPSG:4326'
                or georeference['raster_origin'] not in ('northwest', 'southwest')
                or not isinstance(coordinates, list) or len(coordinates) != 4
                or any(type(item) not in (int, float) or not math.isfinite(item)
                       for item in coordinates)
                or not -180 <= coordinates[0] < coordinates[2] <= 180
                or not -90 <= coordinates[1] < coordinates[3] <= 90
                or not isinstance(georeference['source_sha256'], str)
                or re.fullmatch('[0-9a-f]{64}', georeference['source_sha256']) is None):
            raise ValueError('Invalid WGS84 GeoTIFF georeference')
        _number(georeference['elevation_ceiling_m'], 'georeference.elevation_ceiling_m',
                minimum=1, maximum=10000)
    bounds = document['bounds']
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise ValueError('World bounds require four numbers')
    bounds = [_number(value, 'world bound') for value in bounds]
    if bounds[0] != 0 or bounds[1] != 0 or bounds[2] <= 0 or bounds[3] <= 0:
        raise ValueError('World bounds must start at zero and have positive extents')
    _fields(document['render_cases'], {'width', 'height'}, 'render_cases')
    if any(type(value) is not int or value <= 0 for value in document['render_cases'].values()):
        raise ValueError('Render cases must be positive integers')
    _fields(document['surface'], {'file'}, 'surface')
    surface, surface_metadata = _source_image(source.parent, document['surface']['file'], 'surface')
    height_image, height_metadata = _heightmap(source.parent, document['heightmap'])
    if not isinstance(document['objects'], list):
        raise ValueError('World objects must be an explicit list')
    if document['objects'] and (not isinstance(scenery_catalog, dict)
            or scenery_catalog.get('format') != 'agf-stock-scenery-v1'):
        raise ValueError('Object placement requires an inspected stock scenery catalog')
    objects = []
    identifiers = set()
    for obj in document['objects']:
        _fields(obj, {'id', 'asset', 'position', 'rotation_degrees', 'scale', 'ground_offset_lbu'}, 'object')
        identifier = obj['id']
        if (not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]*', identifier) is None
                or identifier in identifiers):
            raise ValueError('Object ids must be unique lowercase identifiers')
        identifiers.add(identifier)
        asset = obj['asset']
        if not isinstance(asset, str) or asset not in scenery_catalog['registrations']:
            raise ValueError('Unknown stock scenery asset: ' + str(asset))
        registration = scenery_catalog['registrations'][asset]
        if registration['descriptor_class'] not in POINT_CLASSES:
            raise ValueError('Unsupported stock point scenery class')
        position = obj['position']
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError('Object position requires two coordinates')
        ground = sample_height_lbu(height_image, bounds, position, height_metadata['max_altitude_lbu'])
        rotation = _number(obj['rotation_degrees'], 'object rotation', minimum=0, maximum=360)
        scale = _number(obj['scale'], 'object scale', minimum=0)
        if scale == 0:
            raise ValueError('Object scale must be positive')
        offset = _number(obj['ground_offset_lbu'], 'ground offset')
        objects.append({'id': identifier, 'asset': asset, 'descriptor_class': registration['descriptor_class'],
                        'position': [float(value) for value in position], 'rotation_degrees': rotation,
                        'scale': scale, 'ground_offset_lbu': offset, 'sampled_ground_lbu': ground,
                        'placement_height_lbu': ground + offset})
    compiled = {'format': 'agf-world-compiled-v1', 'id': document['id'], 'map_name': document['map_name'],
                'bounds': bounds, 'render_cases': document['render_cases'], 'raster_axes': document['raster_axes'],
                'source_sha256': sha256(source.read_bytes()), 'heightmap': height_metadata,
                'surface': surface_metadata, 'objects': objects,
                'scenery_catalog': scenery_catalog if objects else None}
    if georeference is not None:
        compiled['georeference'] = georeference
    height_bytes = io.BytesIO()
    height_image.save(height_bytes, format='PNG')
    surface_bytes = io.BytesIO()
    surface.save(surface_bytes, format='WEBP', lossless=True)
    compiled['generated_images'] = {'HeightMap.png': sha256(height_bytes.getvalue()),
                                    'Div_map.webp': sha256(surface_bytes.getvalue())}
    if destination is not None:
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        (destination / 'HeightMap.png').write_bytes(height_bytes.getvalue())
        (destination / 'Div_map.webp').write_bytes(surface_bytes.getvalue())
        (destination / 'world.compiled.json').write_text(
            json.dumps(compiled, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return compiled, {'objects': len(objects), 'heightmap_size': list(height_image.size),
                      'surface_size': list(surface.size), 'runtime_verified': False,
                      'engine_scene_emitted': False}
