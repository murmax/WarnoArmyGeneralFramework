"""Source-driven ground albedo preview, kept separate from editable Div_map.

The preview uses native channel textures/tiling and source splat masks. It is a
static diffuse approximation, not a reproduction of WARNO's PBR/postprocess.
"""
import ast
import io
from pathlib import PurePosixPath
import re

from PIL import Image

from .cndf import decode
from .native_campaign_source import properties
from .storage import safe_child, sha256
from .tgv import read_texture


def capture_ground_preview(reader, root):
    resources = {row['path']: row for row in reader.manifest['resources'] if row['scope'] == 'map_details'}
    def source(name):
        return safe_child(reader.source, resources[name]['file']).read_bytes()
    map_text = source('Map.ndf').decode('utf-8-sig')
    settings = source('GraphicSettings.ndf').decode('utf-8-sig')
    matches = re.findall(r'(?m)^\s*MapDecorSets\s+is\s*(\[[^\]]+\])\s*$', map_text)
    if len(matches) != 1:
        raise ValueError('No unique native map decor-set declaration')
    names = ast.literal_eval(matches[0])
    if not isinstance(names, list) or not names or any(name not in reader.game.decor_sets() for name in names):
        raise ValueError('Unknown native map decor-set dependency')
    settings_name = re.findall(r'\bSplattingConfig\s*=\s*\$/GraphicSettings/Splatting/([A-Za-z0-9_]+)', settings)
    if len(settings_name) != 1:
        raise ValueError('No unique native splatting configuration')
    graph = None
    for name in names:
        definitions = reader.game.decor(name, 'Definition')
        path = 'NDF/DecorsSets/Splatting/' + name + '/' + settings_name[0] + '.ndfbin'
        if path in definitions.paths:
            raw = definitions.read(path)
            _, graph = decode(raw)
            graph_origin = {'path': path, 'sha256': sha256(raw)}
    if graph is None:
        raise ValueError('Native splatting descriptor is unavailable')
    config = next(properties(obj) for obj in graph['objects'] if obj['class'] == 'TSplattingConfig')
    with Image.open(io.BytesIO(source('Div_map.webp'))) as shade:
        size = shade.size
    with Image.open(io.BytesIO(source('Splat_map.png'))) as image:
        mask = image.convert('RGB').resize(size, Image.Resampling.BILINEAR)
    bounds = reader.projection['map']['bounds']
    layers = []
    origins = []
    for index in range(3):
        channel = properties(graph['objects'][config['Channel' + str(index)]['object_id']])
        original = channel['Diffuse']
        if not original.startswith(('GameData:/Assets/', 'CommonData:/Assets/')):
            raise ValueError('Unsupported native ground texture reference: ' + original)
        relative = original.split(':/', 1)[1]
        texture_path = 'PC/Texture/' + str(PurePosixPath(relative).with_suffix('.tgv'))
        matches = [reader.game.decor(name, 'Assets') for name in reversed(names)
                   if texture_path in reader.game.decor(name, 'Assets').paths]
        if not matches:
            matches = [reader.game.shared()]
        raw = matches[0].read(texture_path)
        texture = read_texture(raw)[0].convert('RGB')
        period = channel['TileInLBU'] * 215
        if period <= 0:
            raise ValueError('Invalid native ground texture period')
        tile_size = (max(1, round(size[0] * period / (bounds[2] - bounds[0]))),
                     max(1, round(size[1] * period / (bounds[3] - bounds[1]))))
        texture = texture.resize(tile_size, Image.Resampling.LANCZOS)
        layer = Image.new('RGB', size)
        for y in range(0, size[1], tile_size[1]):
            for x in range(0, size[0], tile_size[0]):
                layer.paste(texture, (x, y))
        layers.append(layer)
        origins.append({'channel': index, 'texture': texture_path, 'sha256': sha256(raw), 'tile_lbu': channel['TileInLBU']})
    # Source masks are retained independently. Uncovered pixels use the last
    # ground channel; exact shader normalization/lighting is outside this preview.
    composite = layers[-1]
    for layer, weight in zip(layers, mask.split()):
        composite = Image.composite(layer, composite, weight)
    destination = root / 'ground/albedo.png'
    destination.parent.mkdir(parents=True, exist_ok=True)
    composite.save(destination)
    return {'albedo': destination.relative_to(root).as_posix(), 'splat_sha256': resources['Splat_map.png']['sha256'],
            'descriptor': graph_origin, 'channels': origins, 'neutral_hillshade': 128,
            'method': 'native-diffuse-channels-static-approximation', 'runtime_shader_equivalent': False}
