"""Campaign-owned division emblems for official ModGen workspaces."""
from __future__ import annotations

import re
from pathlib import Path
import shutil

import yaml
from PIL import Image

from .storage import sha256


RESOURCE = Path('GameData/Generated/UserInterface/Textures/DivisionTextures.ndf')
ASSET_ROOT = Path('GameData/Assets/2D/Interface/UseOutGame/Division/Emblem')


def declared_emblems(source):
    root = Path(source).resolve()
    recipe = root / 'emblems.yaml'
    if not recipe.is_file():
        return []
    doc = yaml.safe_load(recipe.read_text(encoding='utf-8'))
    if (not isinstance(doc, dict) or set(doc) != {'schema', 'emblems'}
            or doc['schema'] != 1 or not isinstance(doc['emblems'], list)):
        raise ValueError('Invalid emblems.yaml document')
    result, seen = [], set()
    for item in doc['emblems']:
        if (not isinstance(item, dict) or set(item) != {'token', 'image'}
                or not isinstance(item['token'], str)
                or re.fullmatch(r'Texture_Division_Emblem_AGF_[A-Za-z0-9_]+',
                                item['token']) is None
                or item['token'] in seen
                or not isinstance(item['image'], str)):
            raise ValueError('Invalid or repeated campaign emblem')
        seen.add(item['token'])
        path = (root / item['image']).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() != '.png':
            raise ValueError('Campaign emblem image is missing or outside its source')
        with Image.open(path) as image:
            if image.format != 'PNG' or image.width < 64 or image.height < 64:
                raise ValueError('Campaign emblem must be a readable PNG of at least 64 pixels')
        if path.stat().st_size > 4_000_000:
            raise ValueError('Campaign emblem exceeds the 4 MB source limit')
        name = item['token'].removeprefix('Texture_Division_Emblem_') + '.png'
        result.append({'token': item['token'], 'image': item['image'],
                       'asset': (ASSET_ROOT / name).as_posix(),
                       'sha256': sha256(path.read_bytes())})
    return result


def stage_emblems(source, workspace):
    root, workspace = Path(source).resolve(), Path(workspace).resolve()
    rows = declared_emblems(root)
    if not rows:
        return {'count': 0, 'tokens': []}
    bank = workspace / RESOURCE
    content = bank.read_text(encoding='utf-8')
    fragment = []
    for row in rows:
        if row['token'] + ' is TUIResourceTexture_Common' in content:
            raise ValueError('Campaign emblem token collides with a stock resource')
        destination = workspace / row['asset']
        if destination.exists():
            raise ValueError('Campaign emblem collides with an existing image')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / row['image'], destination)
        fragment.append(f"{row['token']} is TUIResourceTexture_Common\n"
                        f"(\n    FileName = \"GameData:/{row['asset'].removeprefix('GameData/')}\"\n)\n")
    fragment.extend(['unnamed TBUCKToolAdditionalTextureBank', '(', '    Textures = MAP', '    ['])
    fragment.extend(f'        ("{row["token"]}", MAP [(~/ComponentState/Normal, ~/{row["token"]})]),'
                    for row in rows)
    fragment.extend(['    ]', ')', ''])
    bank.write_text(content.rstrip() + '\n\n' + '\n'.join(fragment), encoding='utf-8')
    return {'count': len(rows), 'tokens': [row['token'] for row in rows]}


def verify_runtime_emblems(gen, rows):
    """Require the runtime token bank, resource path and cooked texture together."""
    from .cndf import decode
    gen = Path(gen).resolve()
    if not rows:
        return {'count': 0, 'tokens': []}
    components = gen / 'NDF/UI/Components.ndfbin'
    _, graph = decode(components.read_bytes())
    requested = {row['token'] for row in rows}
    bindings = {}
    for obj in graph['objects']:
        if obj['class'] != 'TBUCKToolAdditionalTextureBank' or not obj['is_top_object']:
            continue
        for prop in obj['properties']:
            if prop['property_name'] != 'Textures':
                continue
            for pair in prop['value']['items']:
                token = pair['key'].get('value')
                if token in requested:
                    if token in bindings:
                        raise ValueError('Duplicate runtime division emblem registration: ' + token)
                    bindings[token] = pair['value']
    if set(bindings) != requested:
        raise ValueError('Missing runtime division emblem texture-bank token')
    declared = (gen / 'DeclaredFiles.txt').read_text(encoding='utf-8').splitlines()
    for row in rows:
        states = bindings[row['token']]
        if states['type'] != 'map_list' or len(states['items']) != 1:
            raise ValueError('Division emblem state binding mismatch')
        state = states['items'][0]
        if state['key'].get('value') != 0 or state['value'].get('type') != 'obj_ref':
            raise ValueError('Division emblem needs a normal-state texture binding')
        texture = graph['objects'][state['value']['object_id']]
        fields = {prop['property_name']:prop['value'].get('value') for prop in texture['properties']}
        if texture['class'] != 'TUIResourceTexture' or fields.get('FileName') != row['asset'].replace('GameData/', 'GameData:/', 1):
            raise ValueError('Runtime division emblem points to the wrong resource')
        relative = 'PC/Texture/' + str(Path(row['asset']).relative_to('GameData').with_suffix('.tgv')).replace('\\', '/')
        cooked = gen / relative
        if not cooked.is_file() or cooked.stat().st_size == 0:
            raise ValueError('Official cooker omitted campaign emblem: ' + row['token'])
        if declared.count('ZZ:/' + relative) != 1:
            raise ValueError('Runtime division emblem is not declared exactly once')
    return {'count': len(rows), 'tokens': [row['token'] for row in rows]}


def verify_cooked_emblems(source, modgen_output):
    from .event_images import compare_event_pixels
    from .tgv import read_texture
    rows = declared_emblems(source)
    gen = Path(modgen_output).resolve() / 'Gen'
    proof = verify_runtime_emblems(gen, rows)
    for row in rows:
        cooked = gen / 'PC/Texture' / Path(row['asset']).relative_to('GameData').with_suffix('.tgv')
        pixels, header = read_texture(cooked.read_bytes())
        if header['format'] != 'A8B8G8R8_LIN':
            raise ValueError('Campaign emblem must retain lossless RGBA pixels')
        with Image.open(Path(source) / row['image']) as original:
            compare_event_pixels(original.convert('RGBA'), pixels)
    return proof
