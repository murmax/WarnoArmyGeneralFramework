"""Portable editor previews derived from native depictions, meshes and atlases.

This is an editor cache, never a replacement for the captured native resources.
The upstream SPK converter is pinned and downloaded into the local artifact cache;
its code and game assets are not redistributed with the framework.
"""
from collections import OrderedDict
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import urllib.request
import zlib

from .cndf import decode
from .game_resources import GameResources
from .native_campaign_source import properties, verify_native_snapshot
from .storage import safe_child, sha256
from .tgv import read_texture


UPSTREAM = 'https://github.com/kilivan4iK/warno-blender-plugin'
COMMIT = '8e27a87d20f99eaaa12160116420d518ee7e5a1c'
EXTRACTOR_SHA256 = 'd74452efef11c9f12225741f4efbdd8057f00d40e909b7db03bf8311c7308fe4'


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')


def ensure_extractor(cache):
    """Use exactly the reviewed upstream revision, including for existing caches."""
    path = Path(cache) / 'external-tools' / COMMIT / 'warno_spk_extract.py'
    if not path.exists():
        url = f'https://raw.githubusercontent.com/kilivan4iK/warno-blender-plugin/{COMMIT}/warno_spk_extract.py'
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(2 * 1024 * 1024)
        if sha256(raw) != EXTRACTOR_SHA256:
            raise ValueError('Downloaded SPK converter does not match the pinned revision')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(raw)
    if sha256(path.read_bytes()) != EXTRACTOR_SHA256:
        raise ValueError('Cached SPK converter changed; refusing to execute it')
    return path


def _load_extractor(path):
    name = '_agf_external_spk_' + COMMIT
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _copy_mesh_pack(entry, cache):
    """Stream the large SPK, checking its archive checksum without a RAM copy."""
    directory = Path(cache) / 'mesh-packs'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (entry.checksum + '.spk')
    expected = bytes.fromhex(entry.checksum)
    def checksum(stream, output=None):
        remaining = entry.size
        crc, md5 = 0, hashlib.md5()
        while remaining:
            block = stream.read(min(8 * 1024 * 1024, remaining))
            if not block:
                raise ValueError('Truncated mesh pack')
            remaining -= len(block)
            if output is not None:
                output.write(block)
            if entry.edat_version == 3:
                crc = zlib.crc32(block, crc)
            else:
                md5.update(block)
        return crc.to_bytes(4, 'little') if entry.edat_version == 3 else md5.digest()
    if target.is_file():
        with target.open('rb') as stream:
            if target.stat().st_size != entry.size or checksum(stream) != expected:
                raise ValueError('Cached mesh pack checksum changed')
        return target
    with tempfile.TemporaryDirectory(prefix='.spk-', dir=directory) as temporary:
        staged = Path(temporary) / 'pack.spk'
        with entry.archive.open('rb') as source, staged.open('xb') as output:
            source.seek(entry.offset)
            actual = checksum(source, output)
        if actual != expected:
            raise ValueError('Installed mesh pack checksum changed')
        staged.rename(target)
    return target


class VisualReader:
    def __init__(self, source, game):
        self.source = Path(source).resolve() if source is not None else None
        self.game = game
        self.manifest = (json.loads((self.source / 'native-source.json').read_text(encoding='utf-8'))
                         if self.source is not None else None)
        self.projection = (json.loads(safe_child(self.source, self.manifest['projection_file']).read_text(encoding='utf-8'))
                           if self.manifest is not None else None)
        self.graphs = {}
        self.atlases = {}
        self.textures = OrderedDict()
        self.visual_resources = [game.shared()]

    def visual_resource(self, path):
        for resources in reversed(self.visual_resources):
            try:
                return resources.require(path)
            except KeyError:
                pass
        raise KeyError('Missing native visual resource: ' + path)

    def graph(self, path):
        if path not in self.graphs:
            current = self.game.definitions().read(path)
            if self.manifest is not None:
                entry = next(row for row in self.manifest['resources']
                             if row['scope'] == 'shared_definitions' and row['path'] == path)
                if sha256(current) != entry['sha256']:
                    raise ValueError('Installed visual definitions differ from the source capture; import the scenario again: ' + path)
            _, graph = decode(current)
            graph['named'] = {name: graph['objects'][index] for index, name in graph['exports'].items()}
            self.graphs[path] = graph
        return self.graphs[path]

    def mesh(self, export):
        for path in ('NDF/GFX/DepictionResources.ndfbin', 'NDF/GFX/DepictionCommonResources.ndfbin'):
            obj = self.graph(path)['named'].get(export)
            if obj is not None:
                mesh = properties(obj).get('Mesh')
                if not isinstance(mesh, str) or not mesh.startswith('GameData:/Assets/'):
                    raise ValueError('Unsupported native mesh resource: ' + export)
                return mesh.removeprefix('GameData:/')
        raise ValueError('Missing native mesh export: ' + export)

    def depiction(self, export):
        graph = self.graph('NDF/GFX/Depiction.ndfbin')
        parts = []
        stack = set()
        def visit(obj, scale=1.0, parent=None, anchor=None):
            if obj['id'] in stack:
                raise ValueError('Cyclic native depiction')
            stack.add(obj['id'])
            props = properties(obj)
            def referenced(value):
                if isinstance(value, dict) and 'object_id' in value:
                    return graph['objects'][value['object_id']]
                if isinstance(value, str) and value in graph['named']:
                    return graph['named'][value]
                raise ValueError('Unsupported depiction reference: ' + str(value))
            if obj['class'] == 'TTimelyDepictionReceiverFactory':
                visit(referenced(props['DepictionDescriptor']), scale, parent, anchor)
            elif obj['class'] == 'TSubDepiction':
                anchors = props.get('Anchors', [None])
                for child_anchor in anchors:
                    visit(referenced(props['Depiction']), scale, parent, child_anchor)
            elif obj['class'] == 'TDepictionDescriptor':
                if 'Scaler' in props:
                    scaler = referenced(props['Scaler'])
                    if scaler['class'] == 'TConstantScaler':
                        scale *= properties(scaler).get('Scale', 1.0)
                alternatives = [referenced(item) for item in props.get('DepictionAlternatives', [])]
                # Stock strategic depictions use the constant "high" alternative.
                alternatives = [item for item in alternatives if 'high' in properties(item).get('SelectorId', ['high'])]
                for alternative in alternatives[:1]:
                    visual = properties(alternative)
                    if 'MeshDescriptor' in visual:
                        part = {'asset': self.mesh(visual['MeshDescriptor']), 'descriptor': visual['MeshDescriptor'],
                                'scale': scale, 'parent': parent, 'anchor': anchor}
                        parts.append(part)
                        parent = len(parts) - 1
                for child in props.get('SubDepictions', []):
                    visit(referenced(child), scale, parent, None)
            stack.remove(obj['id'])
        visit(graph['named'][export])
        return parts

    def material_texture(self, asset, texture_name):
        """Resolve a material's exact source filename through native atlas UVs."""
        folder = PurePosixPath(asset).parent
        matches = []
        while len(folder.parts) >= 3 and not matches:
            atlas_path = 'PC/Atlas/' + str(folder) + '/TextureSmall.atlas'
            try:
                if atlas_path not in self.atlases:
                    _, self.atlases[atlas_path] = decode(self.visual_resource(atlas_path).read())
                graph = self.atlases[atlas_path]
            except KeyError:
                folder = folder.parent
                continue
            for obj in graph['objects']:
                props = properties(obj)
                part_name = PurePosixPath(props.get('TexturePartFileName', '')).name
                # The cooker combines diffuse + alpha into one atlas region.
                diffuse_name = (part_name.split('$_$', 1)[0] + '.png'
                                if part_name.endswith('`_`daComb.png') else part_name)
                if (obj['class'] == 'TTextureSmall'
                        and diffuse_name.casefold() == texture_name.casefold()):
                    container = properties(graph['objects'][props['Container']['object_id']])
                    path = str(PurePosixPath(container['TextureFileName'].removeprefix('ZZ:/')).with_suffix('.tgv'))
                    matches.append((path, props.get('MinUV', [0, 0]), props['MaxUV'], props['TexturePartFileName'],
                                    part_name.casefold() == texture_name.casefold()))
            folder = folder.parent
        exact = [match for match in matches if match[-1]]
        if exact:
            matches = exact
        if len(matches) != 1:
            raise ValueError(f'No unique atlas texture for {asset}: {texture_name}')
        path, low, high, original, _ = matches[0]
        if path not in self.textures:
            raw = self.visual_resource(path).read()
            self.textures[path] = (read_texture(raw)[0], sha256(raw))
            while len(self.textures) > 6:
                self.textures.popitem(last=False)
        self.textures.move_to_end(path)
        image, digest = self.textures[path]
        box = tuple(round(value * extent) for value, extent in zip(low + high, [image.width, image.height] * 2))
        if not 0 <= box[0] < box[2] <= image.width or not 0 <= box[1] < box[3] <= image.height:
            raise ValueError('Native atlas region is outside the texture')
        return image.crop(box), {'atlas': path, 'sha256': digest, 'source_texture': original, 'region': list(box)}


def capture_editor_visuals(source, destination, *, cache=None, public_visuals=None, progress=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    def stage(percent, label):
        if progress is not None:
            progress(percent, label)
    if destination.exists():
        raise FileExistsError(destination)
    verify_native_snapshot(source)
    manifest = json.loads((source / 'native-source.json').read_text(encoding='utf-8'))
    game = GameResources(manifest['game_root'])
    reader = VisualReader(source, game)
    cache = Path(cache or Path(__file__).resolve().parents[1] / 'artifacts/editor-visual-cache')
    extractor = ensure_extractor(cache)
    shared = game.shared()
    pack = shared.require('MeshPack/Base.spk') if 'MeshPack/Base.spk' in shared.paths else shared.require('PC/Mesh/Pack/Base.spk')
    spk_path = _copy_mesh_pack(pack, cache)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.visual-import-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'visuals'
        staged.mkdir()
        models, battalions, issues, authored_visuals = {}, [], [], []
        from .editor_ground_visuals import capture_ground_preview
        stage(20, 'Converting ground textures')
        try:
            ground = capture_ground_preview(reader, staged)
        except (ValueError, KeyError, StopIteration) as error:
            ground = None
            issues.append({'ground': True, 'error': str(error)})
        stage(28, 'Preparing original 3D models')
        with _load_extractor(extractor).SpkMeshExtractor(spk_path) as spk:
            def model(asset, source_spk=spk, source_spk_path=spk_path):
                if asset in models:
                    return models[asset]
                key = sha256(asset.encode('utf-8'))[:20]
                folder = staged / 'models' / key
                folder.mkdir(parents=True)
                result = subprocess.run([sys.executable, '-B', str(extractor), '--spk', str(source_spk_path),
                    '--asset', asset, '--out', str(folder), '--flat'], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
                if result.returncode:
                    raise ValueError('SPK extraction failed: ' + result.stderr[-2000:])
                extracted = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
                if extracted['errors'] or len(extracted['items']) != 1:
                    raise ValueError('SPK mesh was not extracted: ' + asset)
                item = extracted['items'][0]
                material_rows = []
                for material in item['materials']:
                    names = source_spk.material_texture_names_by_id.get(material['id'], {})
                    texture_name = next((names[name] for name in ('DiffuseTextureNoAlpha', 'DiffuseTexture', 'DiffuseTextureAlpha') if name in names), None)
                    row = {'name': material['name'], 'texture': None}
                    if texture_name:
                        try:
                            image, origin = reader.material_texture(asset, texture_name)
                            texture_path = folder / (sha256(texture_name.encode('utf-8'))[:16] + '.png')
                            image.save(texture_path)
                            row.update(texture=texture_path.relative_to(staged).as_posix(), origin=origin)
                        except (ValueError, KeyError) as error:
                            issues.append({'asset': asset, 'material': material['name'], 'error': str(error)})
                    else:
                        issues.append({'asset': asset, 'material': material['name'], 'error': 'No native diffuse texture binding'})
                    material_rows.append(row)
                obj = Path(item['obj'])
                positions = [list(map(float, line.split()[1:4])) for line in obj.read_text(encoding='utf-8').splitlines() if line.startswith('v ')]
                if not positions:
                    raise ValueError('Empty extracted mesh: ' + asset)
                anchors = dict(item['skeleton']['bone_positions'])
                meta = source_spk.fat[asset]
                if meta['nodeIndex'] != 0xffffffff:
                    names = source_spk.parse_node_names(meta['nodeIndex'])
                    positions_by_node = source_spk.parse_node_exact_world_positions(meta['nodeIndex'])
                    if positions_by_node is not None and len(names) == len(positions_by_node):
                        # Exact locator transforms include meshless nodes such as
                        # the top of the strategic pawn's display stand.
                        anchors.update({name.lower(): list(point) for name, point in zip(names, positions_by_node)})
                row = {'asset': asset, 'file': obj.relative_to(staged).as_posix(), 'materials': material_rows,
                       'bounds': [[min(p[i] for p in positions), max(p[i] for p in positions)] for i in range(3)],
                       'anchors': anchors, 'stats': item['stats']}
                models[asset] = row
                return row
            source_battalions = reader.projection['battalions']
            total_battalions = max(1, len(source_battalions))
            for index, battalion in enumerate(source_battalions):
                if index % max(1, total_battalions // 25) == 0:
                    stage(30 + 28 * index // total_battalions,
                          f'Converting battalion models ({index + 1}/{total_battalions})')
                appearance = next((row['properties'] for row in battalion['modules'] if row['class'] == 'TApparenceModuleDescriptor'), None)
                if appearance is None:
                    continue
                try:
                    parts = reader.depiction(appearance['Depiction'])
                    for part in parts:
                        mesh = model(part['asset'])
                        part['model'] = mesh['file']
                        part['offset'] = [0.0, 0.0, 0.0]
                        if part['parent'] is not None:
                            parent = parts[part['parent']]
                            part['offset'] = parent['offset'].copy()
                            if part['anchor']:
                                anchor = models[parent['asset']]['anchors'].get(part['anchor'].lower())
                                if anchor is None:
                                    # Explicitly record unsupported anchors; no invented geometry is substituted.
                                    issues.append({'asset': part['asset'], 'error': 'Missing parent anchor: ' + part['anchor']})
                                else:
                                    part['offset'] = [a + b * parent['scale'] for a, b in zip(part['offset'], anchor)]
                    battalions.append({'export': battalion['export'], 'parts': parts})
                except (ValueError, KeyError, subprocess.TimeoutExpired) as error:
                    issues.append({'export': battalion['export'], 'error': str(error)})
            stage(59, 'Battalion models converted')
            if public_visuals is not None:
                from .native_campaign_source import NativeCampaignReader
                from .pawn import VISUALS
                from .visual_catalog import current_visual_catalog
                catalog = current_visual_catalog()
                native_reader = NativeCampaignReader(game)
                source_id = manifest['scenario']
                specs = json.loads(Path(public_visuals).read_text(encoding='utf-8'))
                if specs.get('schema') != 'agf-editor-visual-request/v1' or not isinstance(specs.get('visuals'), list):
                    raise ValueError('Unsupported public visual request')
                seen = set()
                for spec in specs['visuals']:
                    if (not isinstance(spec, dict) or set(spec) != {'id', 'country'}
                            or not isinstance(spec['id'], str) or not isinstance(spec['country'], str)
                            or (spec['id'], spec['country']) in seen):
                        raise ValueError('Invalid or duplicate public visual request')
                    seen.add((spec['id'], spec['country']))
                    try:
                        if spec['id'] in VISUALS:
                            export = '$/GFX/Pawn/Descriptor_Unit_' + VISUALS[spec['id']][1]
                            pawn = native_reader.battalion(source_id, export)
                            parts = reader.depiction(pawn['depiction'])
                        else:
                            unit = catalog[spec['id']]
                            country = {'RDA': 'DDR'}.get(spec['country'], spec['country'])
                            if country not in {'US', 'RFA', 'SOV', 'DDR', 'UK', 'BEL', 'NL', 'POL', 'CAN', 'ESP', 'FR', 'TCH', 'CUB'}:
                                raise ValueError('Unsupported public strategic base country')
                            stand = reader.mesh('$/GFX/DepictionResources/MeshModele_Socle_' + country)
                            stem = reader.mesh('$/GFX/DepictionResources/MeshModele_Tige_courte')
                            body = reader.mesh('$/GFX/DepictionResources/' + unit['mesh'])
                            tip = model(stem)['anchors'].get('sommet', [0, 0, 0])
                            parts = [{'asset': stand, 'scale': 6, 'offset': [0, 0, 0]},
                                     {'asset': stem, 'scale': 6, 'offset': [0, 0, 0]},
                                     {'asset': body, 'scale': 6, 'offset': [v * 6 for v in tip]}]
                        for part in parts:
                            item = model(part['asset'])
                            part['model'] = item['file']
                            if 'offset' not in part:
                                part['offset'] = [0., 0., 0.]
                                if part.get('parent') is not None:
                                    parent = parts[part['parent']]
                                    part['offset'] = parent['offset'].copy()
                                    if part.get('anchor'):
                                        anchor = models[parent['asset']]['anchors'].get(part['anchor'].lower())
                                        if anchor is None:
                                            raise ValueError('Missing public visual attachment: ' + part['anchor'])
                                        part['offset'] = [a + b * parent['scale'] for a, b in zip(part['offset'], anchor)]
                        authored_visuals.append({'id': spec['id'], 'country': spec['country'], 'parts': parts})
                    except (KeyError, ValueError, subprocess.TimeoutExpired) as error:
                        issues.append({'public_visual': spec['id'], 'error': str(error)})
            from .editor_scene_visuals import capture_scene_visuals
            stage(62, 'Converting map scenery')
            scene = capture_scene_visuals(reader, staged, cache, extractor, model, issues, progress=stage)
        stage(88, 'Checking converted files')
        files = []
        for path in sorted(staged.rglob('*')):
            if path.is_file() and (path.suffix in {'.obj', '.png'} or path.relative_to(staged).as_posix() == 'scene/paths.json'):
                files.append({'file': path.relative_to(staged).as_posix(), 'sha256': sha256(path.read_bytes())})
        report = {'format': 'agf-editor-native-visuals/v1', 'projection_sha256': manifest['projection_sha256'],
                  'scenario': manifest['scenario'], 'extractor': {'upstream': UPSTREAM, 'commit': COMMIT, 'sha256': EXTRACTOR_SHA256},
                  'mesh_pack': pack.origin(), 'models': list(models.values()), 'battalions': battalions,
                  'public_visuals': authored_visuals,
                  'ground': ground,
                  'scene': scene,
                  'files': files, 'issues': issues, 'runtime_verified': False}
        _json(staged / 'manifest.json', report)
        verify_editor_visuals(staged, manifest['projection_sha256'])
        staged.rename(destination)
        stage(91, 'Original visual assets ready')
    return report


def verify_editor_visuals(root, projection_sha256):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'agf-editor-native-visuals/v1' or manifest.get('projection_sha256') != projection_sha256:
        raise ValueError('Native visual cache belongs to another source capture')
    files = {}
    for row in manifest['files']:
        key = row['file'].casefold()
        if key in files or sha256(safe_child(root, row['file']).read_bytes()) != row['sha256']:
            raise ValueError('Native visual file hash changed or duplicated')
        files[key] = row
    models = {}
    for model in manifest['models']:
        if model['file'].casefold() not in files or model['file'] in models:
            raise ValueError('Missing or duplicated native visual model')
        models[model['file']] = model
        for material in model['materials']:
            if material['texture'] is not None and material['texture'].casefold() not in files:
                raise ValueError('Missing native material texture')
    for battalion in manifest['battalions']:
        if any(part['model'] not in models for part in battalion['parts']):
            raise ValueError('Missing battalion visual model')
    if len({(row['id'], row['country']) for row in manifest.get('public_visuals', [])}) != len(manifest.get('public_visuals', [])):
        raise ValueError('Duplicate public visual id')
    for visual in manifest.get('public_visuals', []):
        if any(part['model'] not in models for part in visual['parts']):
            raise ValueError('Missing public visual model')
    if manifest.get('ground') and manifest['ground']['albedo'].casefold() not in files:
        raise ValueError('Missing native ground preview')
    if manifest.get('scene'):
        scene = manifest['scene']
        if scene['path_overlay'].casefold() not in files:
            raise ValueError('Missing native scene path overlay')
        if scene.get('path_geometry') and scene['path_geometry'].casefold() not in files:
            raise ValueError('Missing native scene path geometry')
        import math
        identities = set()
        for obj in scene['objects'] + scene.get('templates', []):
            if obj['id'] in identities:
                raise ValueError('Duplicate native scene visual')
            identities.add(obj['id'])
            for part in obj['parts']:
                if (part['model'] not in models or len(part['transform']) != 12
                        or any(type(value) not in (int, float) or not math.isfinite(value) for value in part['transform'])):
                    raise ValueError('Invalid native scenery model or transform')
    return manifest
