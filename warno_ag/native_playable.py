"""Edit the captured scenario playable polygons without changing stock maps."""
import copy
import math

from .cndf import decode
from .native_graph import NativeGraphEditor
from .storage import sha256


def _area(points):
    return sum(first[0] * second[1] - second[0] * first[1]
               for first, second in zip(points, points[1:])) / 2


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _intersects(a, b, c, d):
    ab_c, ab_d = _cross(a, b, c), _cross(a, b, d)
    cd_a, cd_b = _cross(c, d, a), _cross(c, d, b)
    return ab_c * ab_d < 0 and cd_a * cd_b < 0


def contains_point(polygons, point):
    x, y = point
    for polygon in polygons:
        inside = False
        for a, b in zip(polygon, polygon[1:]):
            cross = _cross(a, b, point)
            if (abs(cross) < 1e-6 and min(a[0], b[0]) <= x <= max(a[0], b[0])
                    and min(a[1], b[1]) <= y <= max(a[1], b[1])):
                return True
            if (a[1] > y) != (b[1] > y):
                hit = a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                if hit > x:
                    inside = not inside
        if inside:
            return True
    return False


def validate_playable_polygons(before, after, bounds):
    if not isinstance(after, list) or len(after) != len(before) or not after:
        raise ValueError('Native playable polygon inventory cannot change')
    normalized = []
    for original, polygon in zip(before, after):
        if not isinstance(polygon, list) or len(polygon) != len(original) or len(polygon) < 4:
            raise ValueError('Native playable polygon vertex inventory cannot change')
        points = []
        for item in polygon:
            if (not isinstance(item, dict) or set(item) != {'x', 'y'}
                    or any(type(item[key]) not in (int, float) or not math.isfinite(item[key])
                           for key in ('x', 'y'))
                    or not bounds['minX'] <= item['x'] <= bounds['maxX']
                    or not bounds['minY'] <= item['y'] <= bounds['maxY']):
                raise ValueError('Native playable vertex is outside its map bounds')
            points.append([float(item['x']), float(item['y'])])
        if points[0] != points[-1] or len({tuple(point) for point in points[:-1]}) != len(points) - 1:
            raise ValueError('Native playable polygon must close without duplicate vertices')
        old_points = [[float(item['x']), float(item['y'])] for item in original]
        if _area(points) * _area(old_points) <= 0 or abs(_area(points)) < 1:
            raise ValueError('Native playable polygon winding or area changed invalidly')
        edges = list(zip(points, points[1:]))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i + 1 or i == 0 and j == len(edges) - 1:
                    continue
                if _intersects(a, b, c, d):
                    raise ValueError('Native playable polygon crosses itself')
        normalized.append(points)
    return normalized


def _polygon_objects(editor):
    roots = [obj for obj in editor.objects if obj['class'] == 'TMapAreaSet']
    if len(roots) != 1:
        raise ValueError('Native playable zone has no unique area set')
    areas = editor.property(roots[0], 'Areas')['value']['items']
    objects = []
    for ref in areas:
        area = editor.objects[ref['object_id']]
        if area['class'] != 'TMapArea':
            raise ValueError('Native playable zone area class changed')
        model = editor.property(area, 'Model')
        target = editor.objects[model['value']['object_id']] if model is not None else area
        if target['class'] not in {'TAreaModel', 'TMapArea'}:
            raise ValueError('Native playable zone model class changed')
        objects.append(target)
    return objects


def read_playable_polygons(raw):
    editor = NativeGraphEditor(raw)
    return [[[float(v) for v in item['value']] for item in
             editor.property(obj, 'BasePolygon2D')['value']['items']]
            for obj in _polygon_objects(editor)]


def _patch_one(raw, before, after):
    editor = NativeGraphEditor(raw)
    objects = _polygon_objects(editor)
    if len(objects) != len(before):
        raise ValueError('Native playable zone area count differs from imported source')
    allowed = set()
    for obj, expected, points in zip(objects, before, after):
        polygon = editor.property(obj, 'BasePolygon2D')
        wire = copy.deepcopy(polygon['value'])
        if (wire['type'] != 'list' or len(wire['items']) != len(expected)
                or [[float(v) for v in item['value']] for item in wire['items']] != expected
                or any(item['type'] != 'float2' for item in wire['items'])):
            raise ValueError('Native playable source vertices changed before build')
        for item, point in zip(wire['items'], points):
            item['value'] = point
        editor.set_value(obj, 'BasePolygon2D', wire)
        allowed.add((obj['id'], 'BasePolygon2D'))
        center = editor.property(obj, 'Center')
        if center is not None:
            value = copy.deepcopy(center['value'])
            if value['type'] != 'vec3':
                raise ValueError('Native playable area center type changed')
            value['value'][:2] = [sum(p[axis] for p in points[:-1]) / (len(points) - 1)
                                   for axis in (0, 1)]
            editor.set_value(obj, 'Center', value)
            allowed.add((obj['id'], 'Center'))
    output = editor.save()
    _, original = decode(raw)
    _, changed = decode(output)
    if (original['imports'] != changed['imports'] or original['exports'] != changed['exports']
            or original['classes'] != changed['classes']
            or len(original['objects']) != len(changed['objects'])):
        raise ValueError('Native playable edit changed its graph schema')
    for old, new in zip(original['objects'], changed['objects']):
        old_fields = {item['property_name']: item['value'] for item in old['properties']}
        new_fields = {item['property_name']: item['value'] for item in new['properties']}
        if (old['id'], old['class']) != (new['id'], new['class']):
            raise ValueError('Native playable edit changed an object identity')
        if any(old_fields.get(name) != new_fields.get(name) and (old['id'], name) not in allowed
               for name in set(old_fields) | set(new_fields)):
            raise ValueError('Native playable edit changed an unrelated property')
    if read_playable_polygons(output) != after:
        raise ValueError('Native playable polygon binary readback mismatch')
    return output


def patch_playable_zones(source, compiled):
    before = compiled['baseline']['playable_polygons']
    after = compiled['state']['playable_polygons']
    points = validate_playable_polygons(before, after,
                                       compiled['state']['world']['nativeField']['bounds'])
    expected = [[[float(value[key]) for key in ('x', 'y')] for value in polygon]
                for polygon in before]
    result = {}
    for path in ('PlayableZone/Areas.ndfbin', 'out/PlayableZone.ndfbin'):
        if path not in source:
            raise ValueError('Native scenario lacks a playable-zone resource: ' + path)
        result[path] = _patch_one(source[path], expected, points)
    proof = {'polygons': len(points), 'vertices': [len(polygon) for polygon in points],
             'before': {path: sha256(source[path]) for path in result},
             'after': {path: sha256(result[path]) for path in result},
             'runtime_verified': False}
    return result, proof
