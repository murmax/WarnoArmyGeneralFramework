"""Expand native map patterns into selectable mesh groups and a path overlay.

All source Items.sav bytes remain in the native capture. Random decorators are
shown with a deterministic preview choice, not claimed to match the baker seed.
"""
from collections import Counter
from contextlib import ExitStack
import io
import json
import math
from pathlib import PurePosixPath

from PIL import Image, ImageDraw, ImageStat

from .cndf import decode
from .native_campaign_source import properties
from .storage import safe_child, sha256
from .tgv import read_texture


IDENTITY = (1., 0., 0., 0., 1., 0., 0., 0., 1., 0., 0., 0.)


def transform_point(matrix, point):
    return [sum(matrix[axis * 3 + i] * point[axis] for axis in range(3)) + matrix[9 + i] for i in range(3)]


def combine_transform(parent, child):
    linear = [sum(parent[k * 3 + i] * child[axis * 3 + k] for k in range(3))
              for axis in range(3) for i in range(3)]
    return linear + transform_point(parent, child[9:12])


def item_transform(props):
    return [*props.get('AxeX', [1, 0, 0]), *props.get('AxeY', [0, 1, 0]),
            *props.get('AxeZ', [0, 0, 1]), *props.get('AxeT', [0, 0, 0])]


class SceneRegistry:
    def __init__(self, reader, material_output=None):
        self.reader = reader
        self.material_output = material_output
        self.game = reader.game
        self.registry = {}
        self.exports = {}
        self.patterns = {}
        self.props = {}
        self.origins = []
        self.style_cache = {}
        self.color_cache = {}
        self.diagnostics = Counter()
        self.random_choices = 0
        self.fallback_sets_loaded = False
        # Current strategic maps load CommonSet and Steelman. Keep the map's
        # actual declaration rather than treating every installed decor as active.
        import ast, re
        row = next(r for r in reader.manifest['resources'] if r['scope'] == 'map_details' and r['path'] == 'Map.ndf')
        source = safe_child(reader.source, row['file']).read_text(encoding='utf-8-sig')
        declaration = re.findall(r'(?m)^\s*MapDecorSets\s+is\s*(\[[^\]]+\])\s*$', source)
        if len(declaration) != 1:
            raise ValueError('No unique map decor-set declaration')
        self.decor_names = ast.literal_eval(declaration[0])
        for name in self.decor_names:
            definition = self.game.decor(name, 'Definition')
            reader.visual_resources.append(self.game.decor(name, 'Assets'))
            for scope in ('Scenery', 'Scenery/Editor'):
                path = f'NDF/DecorsSets/{scope}/{name}.ndfbin'
                if path in definition.paths:
                    self.add_graph(definition.read(path), path)
            editor = self.game.decor(name, 'Editor')
            for entry in editor.entries:
                if entry.path.endswith('.sav'):
                    self.patterns[PurePosixPath(entry.path).stem] = entry
        self.active_registrations = set(self.registry)

    def add_graph(self, raw, origin):
        _, graph = decode(raw)
        self.origins.append({'path': origin, 'sha256': sha256(raw)})
        for obj in graph['objects']:
            props = properties(obj)
            self.props[id(obj)] = props
            if props.get('RegistrationName'):
                self.registry[props['RegistrationName']] = (graph, obj)
        for index, export in graph['exports'].items():
            self.exports[export] = (graph, graph['objects'][index])
        return graph

    def named(self, name):
        if name not in self.registry and name in self.patterns:
            entry = self.patterns[name]
            self.add_graph(entry.read(), entry.path)
        if name in self.registry:
            return self.registry[name]
        if name in self.exports:
            return self.exports[name]
        if not self.fallback_sets_loaded:
            self.fallback_sets_loaded = True
            # Some stock patterns explicitly reference a tactical decor's road
            # descriptor. Resolve that exact registration without replacing the
            # active map's own registrations or resource precedence.
            for other in self.game.decor_sets():
                if other in self.decor_names:
                    continue
                old_registry, old_exports = self.registry.copy(), self.exports.copy()
                definitions = self.game.decor(other, 'Definition')
                for scope in ('Scenery', 'Scenery/Editor'):
                    path = f'NDF/DecorsSets/{scope}/{other}.ndfbin'
                    if path in definitions.paths:
                        self.add_graph(definitions.read(path), path)
                self.registry.update(old_registry)
                self.exports.update(old_exports)
                self.reader.visual_resources.insert(0, self.game.decor(other, 'Assets'))
            if name in self.registry:
                return self.registry[name]
            if name in self.exports:
                return self.exports[name]
        raise KeyError('Unresolved scenery registration: ' + name)

    def referenced(self, graph, value):
        if isinstance(value, dict) and 'object_id' in value:
            return graph, graph['objects'][value['object_id']]
        if isinstance(value, str):
            return self.named(value)
        raise ValueError('Unsupported scenery reference')

    def material_style(self, graph, descriptor):
        """Use the native diffuse image and its world tiling for surface fillers."""
        props = self.props[id(descriptor)]
        if 'MeshBucketHandler' in props:
            graph, handler = self.referenced(graph, props['MeshBucketHandler'])
            props = self.props[id(handler)]
        if 'MeshMaterial' not in props:
            return None
        graph, material = self.referenced(graph, props['MeshMaterial'])
        props = self.props[id(material)]
        diffuse = next((p['value'] for p in props.get('TextureDico', []) if p['key'] == 'Diffuse'), None)
        if not isinstance(diffuse, str) or not diffuse.startswith(('GameData:/Assets/', 'CommonData:/Assets/')):
            return None
        path = 'PC/Texture/' + str(PurePosixPath(diffuse.split(':/', 1)[1]).with_suffix('.tgv'))
        if path not in self.color_cache:
            raw = self.reader.visual_resource(path).read()
            image = read_texture(raw)[0].convert('RGBA')
            color = tuple(round(v) for v in ImageStat.Stat(image).mean)
            saved = {'color': color}
            if self.material_output is not None:
                target = self.material_output / 'scene' / 'materials' / (sha256(path.encode('utf-8'))[:20] + '.png')
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target)
                saved['texturePath'] = '.native/visuals/' + target.relative_to(self.material_output).as_posix()
            self.color_cache[path] = saved
            self.origins.append({'path': path, 'sha256': sha256(raw)})
        style = dict(self.color_cache[path])
        if self.material_output is not None:
            tiling = next((row['value'] for row in props.get('ParameterDico', []) if row['key'] == 'TextureTiling'), None)
            if isinstance(tiling, dict) and 'object_id' in tiling:
                tiling = self.props[id(graph['objects'][tiling['object_id']])].get('Value')
            if type(tiling) in (int, float) and math.isfinite(tiling) and tiling > 0:
                style['tileNative'] = 215 / tiling
            else:
                style.pop('texturePath', None)
        return style

    def color(self, graph, descriptor):
        style = self.material_style(graph, descriptor)
        return style['color'] if style else None

    def styles(self, name, mode):
        key = name, mode
        if key in self.style_cache:
            return self.style_cache[key]
        output = []
        active = set()
        def visit(graph, obj, offset=0):
            identity = id(obj)
            if identity in active:
                raise ValueError('Cyclic scenery style')
            active.add(identity)
            props = self.props[identity]
            kind = obj['class']
            if kind == 'TSceneryDescriptorProxy':
                visit(*self.named(props['AliasedRegistrationName']), offset)
            elif kind in ('TSceneryDescriptorMultiLine', 'TSceneryDescriptorMultiFiller'):
                for entry in props.get('Entries', []):
                    visit(*self.referenced(graph, entry), offset)
            elif kind in ('TSceneryDescriptorMultiLineEntry', 'TSceneryDescriptorMultiFillerEntry'):
                visit(*self.referenced(graph, props['SceneryDescriptor']), offset + props.get('OffsetInLBU', 0) * 215)
            elif kind == 'TSceneryDescriptorSurfaceWithBorder':
                visit(*self.referenced(graph, props['Surface'] if mode == 'fill' else props['Border']), offset)
            elif kind == 'TSceneryDescriptorSurfaceSticker' and mode == 'fill':
                material = self.material_style(graph, obj)
                if material:
                    output.append({**material, 'width': 0, 'offset': offset})
            elif kind == 'TSceneryDescriptorExtrudedLine' and mode == 'line':
                color = self.color(graph, obj)
                if color:
                    output.append({'color': color, 'width': props.get('ThicknessInLBU', 1) * 215, 'offset': offset})
            # Gameplay masks, snap guides and procedural edge generators do not
            # contain a directly drawable material. Their source stays intact.
            active.remove(identity)
        try:
            visit(*self.named(name))
        except (KeyError, ValueError) as error:
            self.diagnostics[str(error)] += 1
        self.style_cache[key] = output
        return output

    def expand(self, name, seed, on_mesh, on_path):
        active = set()
        def visit(graph, obj, matrix, branch):
            identity = id(obj)
            if identity in active or len(active) > 64:
                raise ValueError('Cyclic or excessively deep scenery pattern')
            active.add(identity)
            props = self.props[identity]
            kind = obj['class']
            def child(value, transform=matrix, suffix=''):
                visit(*self.referenced(graph, value), transform, branch + suffix)
            if kind == 'TSceneryDescriptorProxy':
                visit(*self.named(props['AliasedRegistrationName']), matrix, branch)
            elif kind == 'TSaveDescriptorPattern':
                child(props['SaveDescriptorItemList'])
            elif kind == 'TSaveDescriptorItemList':
                for i, value in enumerate(props.get('Items', [])):
                    child(value, suffix='/' + str(i))
            elif kind == 'TSaveDescriptorItemPoint':
                visit(*self.named(props['SceneryDescriptor']), combine_transform(matrix, item_transform(props)), branch)
            elif kind == 'TSaveDescriptorItemPath':
                on_path(props, matrix)
            elif kind == 'TSceneryDescriptorRandom':
                alternatives = [self.referenced(graph, value) for value in props.get('Alternatives', [])]
                weights = [self.props[id(entry)].get('Weight', 1) for _, entry in alternatives]
                if not alternatives or any(w < 0 for w in weights) or sum(weights) <= 0:
                    raise ValueError('Invalid scenery random alternatives')
                digest = int(sha256((seed + branch).encode())[:16], 16)
                target = digest / (1 << 64) * sum(weights)
                chosen = len(weights) - 1
                for index, weight in enumerate(weights):
                    target -= weight
                    if target < 0:
                        chosen = index
                        break
                self.random_choices += 1
                visit(*alternatives[chosen], matrix, branch + '/random')
            elif kind == 'TSceneryDescriptorRandomEntry':
                child(props['SceneryDescriptor'])
            elif kind == 'TSceneryDescriptorMultiState':
                if 'Fallback' in props:
                    child(props['Fallback'])
            elif kind in ('TSceneryDescriptorModel3D', 'TSceneryDescriptorModel3DForImpostor'):
                resource_graph, resource = self.referenced(graph, props['Resource'])
                asset = self.props[id(resource)]['Mesh'].removeprefix('GameData:/')
                on_mesh(asset, matrix)
            elif kind == 'TSceneryDescriptorMultiLOD':
                for i, value in enumerate(props.get('High', props.get('Mid', props.get('Low', [])))):
                    child(value, suffix='/lod' + str(i))
            elif kind == 'TSceneryDescriptorImpostor':
                for i, value in enumerate(props.get('SceneryDescriptor', [])):
                    child(value, suffix='/impostor' + str(i))
            elif kind != 'TSceneryDescriptorFX':
                self.diagnostics['Point preview class: ' + kind] += 1
            active.remove(identity)
        visit(*self.named(name), list(IDENTITY), '')


def capture_scene_visuals(reader, root, cache, extractor, capture_mesh, issues, *, progress=None):
    from .editor_visuals import _copy_mesh_pack, _load_extractor
    registry = SceneRegistry(reader, root)
    resource = next(r for r in reader.manifest['resources'] if r['scope'] == 'map_details' and r['path'] == 'Items.sav')
    graph = registry.add_graph(safe_child(reader.source, resource['file']).read_bytes(), 'map_details/Items.sav')
    roots = [obj for obj in graph['objects'] if obj['class'] == 'TSaveDescriptorItemList' and obj['is_top_object']]
    if len(roots) != 1:
        raise ValueError('Map source requires one root item list')
    items = [graph['objects'][row['object_id']] for row in registry.props[id(roots[0])]['Items']]
    if progress is not None:
        progress(64, f'Map objects found ({len(items)})')
    bounds = reader.projection['map']['bounds']
    final_size = tuple(reader.projection['map']['surface_size'])
    size = tuple(value * 4 for value in final_size)
    overlay = Image.new('RGBA', size)
    draw = ImageDraw.Draw(overlay, 'RGBA')
    scale = size[0] / (bounds[2] - bounds[0])
    def pixel(point):
        return ((point[0] - bounds[0]) / (bounds[2] - bounds[0]) * size[0],
                (point[1] - bounds[1]) / (bounds[3] - bounds[1]) * size[1])
    path_count, fill_count, line_count = 0, 0, 0
    pending_lines = []
    geometry = []
    def path(props, matrix, owner=None, owner_matrix=IDENTITY):
        nonlocal path_count, fill_count, line_count
        positions = props.get('Positions', [])
        if len(positions) < 2:
            return
        path_count += 1
        local_points = [transform_point(matrix, point) for point in positions]
        points = [transform_point(owner_matrix, point) for point in local_points]
        record = {'owner': owner, 'points': [point[:2] for point in local_points], 'fills': [], 'segments': []}
        if props.get('SurfaceSceneryDescriptor') and len(points) >= 3:
            for style in registry.styles(props['SurfaceSceneryDescriptor'], 'fill'):
                draw.polygon([pixel(point) for point in points], fill=style['color'])
                record['fills'].append(style)
                fill_count += 1
        descriptors = props.get('SegmentSceneryDescriptors', [])
        segment_count = len(points) if props.get('Circular') else len(points) - 1
        for index in range(min(segment_count, len(descriptors))):
            first, second = points[index], points[(index + 1) % len(points)]
            dx, dy = second[0] - first[0], second[1] - first[1]
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            for style in registry.styles(descriptors[index], 'line'):
                ox, oy = -dy / length * style['offset'], dx / length * style['offset']
                pending_lines.append(([pixel([first[0] + ox, first[1] + oy]), pixel([second[0] + ox, second[1] + oy])],
                                      style['color'], max(1, round(style['width'] * scale))))
                line_count += 1
            styles = registry.styles(descriptors[index], 'line')
            if styles:
                record['segments'].append({'a': index, 'b': (index + 1) % len(points), 'styles': styles})
        if record['fills'] or record['segments']:
            geometry.append(record)
    objects, templates = [], []
    pack_origins = []
    with ExitStack() as stack:
        packs = []
        for name in registry.decor_names:
            assets = reader.game.decor(name, 'Assets')
            path_name = f'MeshPack/DecorsSets/{name}.spk'
            if path_name not in assets.paths:
                path_name = f'PC/Mesh/Pack/DecorsSets/{name}.spk'
            if path_name in assets.paths:
                entry = assets.require(path_name)
                file = _copy_mesh_pack(entry, cache)
                pack = stack.enter_context(_load_extractor(extractor).SpkMeshExtractor(file))
                packs.append((pack, file))
                pack_origins.append(entry.origin())
        def mesh(parts, asset, transform):
            found = [(pack, file) for pack, file in packs if asset in pack.fat]
            if len(found) != 1:
                raise ValueError('No unique scenery mesh pack for ' + asset)
            captured = capture_mesh(asset, *found[0])
            parts.append({'model': captured['file'], 'transform': [x * 215 for x in transform[:9]] + list(transform[9:])})
        total_items = max(1, len(items))
        for index, item in enumerate(items):
            if progress is not None and index % max(1, total_items // 25) == 0:
                progress(65 + 19 * index // total_items,
                         f'Converting map objects ({index + 1}/{total_items})')
            props = registry.props[id(item)]
            if item['class'] == 'TSaveDescriptorItemPath':
                path(props, IDENTITY)
                continue
            if item['class'] != 'TSaveDescriptorItemPoint':
                continue
            identifier = 'scenery_' + str(item['id'])
            parts = []
            try:
                registry.expand(props['SceneryDescriptor'], identifier, lambda asset, matrix: mesh(parts, asset, matrix),
                    lambda p, m: path(p, m, identifier, item_transform(props)))
            except (KeyError, ValueError) as error:
                registry.diagnostics[str(error)] += 1
            objects.append({'id': identifier, 'descriptor': props['SceneryDescriptor'], 'parts': parts})
        if progress is not None:
            progress(85, 'Checking scenery palette')
        for name, (_, descriptor) in sorted(registry.registry.items()):
            if name not in registry.active_registrations:
                continue
            if descriptor['class'] not in {'TSceneryDescriptorModel3D', 'TSceneryDescriptorMultiState', 'TSceneryDescriptorMultiLOD'}:
                continue
            parts = []
            try:
                registry.expand(name, 'template:' + name, lambda asset, matrix: mesh(parts, asset, matrix), lambda p, m: None)
            except (ValueError, KeyError) as error:
                issues.append({'scenery_template': name, 'error': str(error)})
            if parts:
                templates.append({'id': 'template_' + sha256(name.encode())[:16], 'descriptor': name, 'parts': parts})
    output = root / 'scene/paths.png'
    if progress is not None:
        progress(87, 'Drawing roads, rivers and forests')
    output.parent.mkdir(parents=True, exist_ok=True)
    for points, color, width in pending_lines:
        draw.line(points, fill=color, width=width)
    overlay.resize(final_size, Image.Resampling.LANCZOS).save(output)
    geometry_file = root / 'scene/paths.json'
    geometry_file.write_text(json.dumps({'format': 'agf-native-scene-paths/v1', 'width': final_size[0], 'height': final_size[1],
                                        'paths': geometry}, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    return {'objects': objects, 'templates': templates, 'path_overlay': output.relative_to(root).as_posix(), 'mesh_packs': pack_origins,
            'path_geometry': geometry_file.relative_to(root).as_posix(),
            'resource_origins': registry.origins, 'paths': path_count, 'filled_shapes': fill_count, 'line_segments': line_count,
            'random_choices': registry.random_choices, 'random_preview': 'stable source-id selection; baked seed not reproduced',
            'curve_preview': 'source control-point polyline; source tangents remain preserved in Items.sav',
            'diagnostics': dict(registry.diagnostics), 'runtime_geometry_equivalent': False}
