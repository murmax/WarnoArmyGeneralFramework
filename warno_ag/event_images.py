"""Compile external event artwork into private ModGen texture-bank sources."""
import io
import json
from pathlib import Path
import re
import struct

from PIL import Image, ImageDraw, ImageOps
import zstandard

from .authoring import _read_yaml
from .cndf import decode
from .storage import safe_child, sha256


BANK_PATH = 'GameData/UserInterface/Use/Strategic/UIStrategicLDHint_ressources.ndf'
ASSET_ROOT = 'GameData/Assets/2D/Interface/UseStrategic/AGFEvents'


def compile_event_images(source, destination):
    """Stage source assets and a bank fragment; never edits an existing workspace."""
    source = Path(source).resolve()
    document = _read_yaml(source)
    if not isinstance(document, dict) or not {'schema', 'namespace', 'images'} <= set(document)\
            or set(document) - {'schema', 'namespace', 'images', 'composites', 'plain'}:
        raise ValueError('Event-image manifest fields mismatch')
    if document['schema'] not in ('agf-event-images/v1', 'agf-event-images/v2'):
        raise ValueError('Unsupported event-image schema')
    composites = document.get('composites', {})
    plain = document.get('plain', {})
    if document['schema'] == 'agf-event-images/v1' and (composites or plain):
        raise ValueError('Generated event images require v2')
    if not isinstance(composites, dict):
        raise ValueError('Event-image composites must be a mapping')
    if not isinstance(plain, dict):
        raise ValueError('Plain event images must be a mapping')
    namespace = document['namespace']
    if not isinstance(namespace, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', namespace) is None:
        raise ValueError('Invalid event-image namespace')
    images = document['images']
    if not isinstance(images, dict) or not (images or plain):
        raise ValueError('Event images or plain dialog images must be a nonempty mapping')
    staged = {}
    records = []
    decoded = {}
    for identifier, relative in sorted(images.items(), key=lambda pair: str(pair[0])):
        if not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None:
            raise ValueError('Invalid event-image identifier')
        if (not isinstance(relative, str) or not relative or '\\' in relative
                or any(part in ('', '.', '..') for part in relative.split('/'))):
            raise ValueError('Event image requires a confined relative path')
        path = safe_child(source.parent, relative)
        raw = path.read_bytes()
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'WEBP') or image.mode not in ('RGB', 'RGBA'):
                    raise ValueError('Event images require RGB/RGBA PNG or WebP')
                if any(not 2 <= dimension <= 8192 for dimension in image.size):
                    raise ValueError('Event-image dimensions must be between 2 and 8192')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Animated event images are unsupported')
                image.load()
                image = image.convert('RGBA')
                decoded[identifier] = image.copy()
                buffer = io.BytesIO()
                image.save(buffer, format='PNG')
                data = buffer.getvalue()
                size, mode = list(image.size), image.mode
        except (OSError, Image.DecompressionBombError) as error:
            raise ValueError('Cannot decode event image: ' + relative) from error
        token = 'AGF_EVT_' + namespace + '_' + identifier
        target = ASSET_ROOT + '/' + namespace + '/' + identifier + '.png'
        staged[target] = data
        records.append({'id': identifier, 'token': token, 'source': relative,
                        'source_sha256': sha256(raw), 'asset': target,
                        'asset_sha256': sha256(data), 'size': size, 'mode': mode})
    for identifier, recipe in sorted(composites.items(), key=lambda pair: str(pair[0])):
        if (not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                or identifier in decoded or not isinstance(recipe, dict)
                or set(recipe) != {'kind', 'cards'} or recipe['kind'] != 'two_cards'
                or not isinstance(recipe['cards'], list) or len(recipe['cards']) != 2
                or any(card not in decoded for card in recipe['cards'])):
            raise ValueError('Invalid two-card event-image composite: ' + str(identifier))
        image = compose_two_choice_cards(*(decoded[card] for card in recipe['cards']))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        data = buffer.getvalue()
        token = 'AGF_EVT_' + namespace + '_' + identifier
        target = ASSET_ROOT + '/' + namespace + '/' + identifier + '.png'
        staged[target] = data
        records.append({'id': identifier, 'token': token, 'source': 'composite:' + ','.join(recipe['cards']),
                        'source_sha256': sha256(json.dumps(recipe, sort_keys=True).encode('utf-8')),
                        'asset': target, 'asset_sha256': sha256(data),
                        'size': list(image.size), 'mode': 'RGBA', 'composite': recipe})
    for identifier, kind in sorted(plain.items(), key=lambda pair: str(pair[0])):
        if (not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                or identifier in decoded or identifier in composites or kind != 'text_choice'):
            raise ValueError('Invalid plain event-image recipe: ' + str(identifier))
        image = compose_plain_choice_background()
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        data = buffer.getvalue()
        token = 'AGF_EVT_' + namespace + '_' + identifier
        target = ASSET_ROOT + '/' + namespace + '/' + identifier + '.png'
        staged[target] = data
        records.append({'id': identifier, 'token': token, 'source': 'generated:text_choice',
                        'source_sha256': sha256(kind.encode('utf-8')),
                        'asset': target, 'asset_sha256': sha256(data),
                        'size': list(image.size), 'mode': 'RGBA', 'plain': kind})
    lines = ['unnamed TBUCKToolAdditionalTextureBank', '(', '    Textures = MAP', '    [']
    for record in records:
        virtual = record['asset'].replace('GameData/', 'GameData:/', 1)
        lines.append('        ("' + record['token'] + '", MAP [(~/ComponentState/Normal, '
                     + "TUIResourceTexture_Common(FileName='" + virtual + "'))]),")
    lines += ['    ]', ')', '']
    fragment = '\n'.join(lines)
    report = {'format': 'agf-event-images-compiled-v1', 'namespace': namespace,
              'source_sha256': sha256(source.read_bytes()), 'images': records,
              'bank_target': BANK_PATH, 'bank_fragment_sha256': sha256(fragment.encode('utf-8')),
              'profile_event_images': {record['id']: record['token'] for record in records},
              'cooked_verified': False, 'runtime_verified': False}
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    for relative, raw in staged.items():
        target = safe_child(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (destination / 'event-texture-bank.ndf').write_text(fragment, encoding='utf-8')
    (destination / 'event-images.compiled.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def compose_two_choice_cards(left, right):
    """Create the single 1348x604 texture used by WARNO's five-text popup.

    The five localized strings remain live native UI components; no language
    is baked into the art.  Each author image is cropped only inside its own
    card, so replacing one branch never changes the other branch's picture.
    """
    canvas = Image.new('RGBA', (1348, 604), (13, 19, 20, 255))
    draw = ImageDraw.Draw(canvas, 'RGBA')
    draw.rounded_rectangle((7, 7, 1340, 596), radius=9, fill=(28, 32, 29, 255),
                           outline=(160, 146, 110, 255), width=3)
    for artwork, left_edge in ((left, 31), (right, 684)):
        top, width, height = 91, 633, 471
        box = (left_edge, top, left_edge + width, top + height)
        canvas.paste(ImageOps.fit(artwork.convert('RGBA'), (width, height),
                                  method=Image.Resampling.LANCZOS), box[:2])
        # Keep the card opaque: drawing translucent rectangles directly into
        # the RGBA canvas previously replaced alpha and exposed the map below.
        shade=Image.new('RGBA',(width,height),(0,0,0,0));fade=ImageDraw.Draw(shade)
        for y in range(270,height):
            opacity=min(220,int((y-270)*220/201))
            fade.line((0,y,width,y),fill=(8,12,13,opacity))
        canvas.alpha_composite(shade,(left_edge,top))
        draw.rectangle(box, outline=(178, 161, 118, 255), width=4)
    return canvas


def compose_plain_choice_background():
    canvas = Image.new('RGBA', (1348, 604), (16, 23, 26, 255))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((8, 8, 1339, 595), radius=9,
                           outline=(168, 151, 112, 255), width=3)
    draw.line((32, 458, 1316, 458), fill=(109, 105, 85, 255), width=2)
    return canvas


def merge_event_texture_bank(existing, fragment):
    """Append a private bank without rewriting stock registrations."""
    tokens = re.findall(r'\("(AGF_EVT_[a-z0-9_]+)", MAP', fragment)
    if not tokens or len(set(tokens)) != len(tokens):
        raise ValueError('Invalid or duplicate private event-image registrations')
    if any(re.search(r"['\"]" + re.escape(token) + r"['\"]", existing) for token in tokens):
        raise ValueError('Private event-image token already registered')
    if 'unnamed TBUCKToolAdditionalTextureBank' not in existing:
        raise ValueError('Expected strategic texture-bank source is missing')
    return existing + '\n' + fragment


def read_event_texture(raw):
    """Read the inspected single-mip lossless UI texture format, failing closed."""
    if len(raw) < 72:
        raise ValueError('Truncated event texture')
    version, flags, width, height, stored_width, stored_height, mips, name_length = struct.unpack_from(
        '<6IHH', raw)
    if (version != 3 or flags != 2 or mips != 1 or name_length != 12
            or (width, height) != (stored_width, stored_height)
            or any(not 2 <= dimension <= 8192 for dimension in (width, height))
            or raw[28:40] != b'A8B8G8R8_LIN' or raw[40:56] != bytes(16)):
        raise ValueError('Unsupported event texture layout')
    offset, size = struct.unpack_from('<II', raw, 56)
    end = offset + size
    if (offset != 64 or size < 8 or end > len(raw)
            or len(raw) != (end + 3) // 4 * 4 or any(raw[end:])
            or raw[offset:offset + 4] != b'ZSTD'):
        raise ValueError('Invalid event texture payload bounds')
    expected_size = width * height * 4
    if struct.unpack_from('<I', raw, offset + 4)[0] != expected_size:
        raise ValueError('Event texture pixel size mismatch')
    try:
        frame = raw[offset + 8:end]
        if zstandard.frame_content_size(frame) != expected_size:
            raise ValueError('Event texture frame size mismatch')
        pixels = zstandard.ZstdDecompressor(max_window_size=256 * 1024).decompress(
            frame, max_output_size=expected_size, allow_extra_data=False)
    except zstandard.ZstdError as error:
        raise ValueError('Invalid event texture compression') from error
    if len(pixels) != expected_size:
        raise ValueError('Event texture decoded size mismatch')
    return Image.frombytes('RGBA', (width, height), pixels)


def verify_cooked_event_images(staged, gen):
    """Prove private binding and pixels, accounting for native alpha premultiplication."""
    staged, gen = Path(staged).resolve(), Path(gen).resolve()
    manifest = json.loads((staged / 'event-images.compiled.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'agf-event-images-compiled-v1' or not manifest.get('images'):
        raise ValueError('Invalid compiled event-image manifest')
    components_raw = (gen / 'NDF/UI/Components.ndfbin').read_bytes()
    _, graph = decode(components_raw)
    requested = {record['token'] for record in manifest['images']}
    if len(requested) != len(manifest['images']):
        raise ValueError('Duplicate event-image token in manifest')
    registrations = {}
    for obj in graph['objects']:
        if obj['class'] != 'TBUCKToolAdditionalTextureBank' or not obj['is_top_object']:
            continue
        for prop in obj['properties']:
            if prop['property_name'] != 'Textures':
                continue
            for pair in prop['value']['items']:
                token = pair['key'].get('value')
                if token not in requested:
                    continue
                if token in registrations:
                    raise ValueError('Duplicate cooked event-image registration')
                registrations[token] = pair['value']
    if set(registrations) != requested:
        raise ValueError('Missing cooked event-image registration')
    declared = (gen / 'DeclaredFiles.txt').read_text(encoding='utf-8').splitlines()
    records = []
    for record in manifest['images']:
        states = registrations[record['token']]
        if states['type'] != 'map_list' or len(states['items']) != 1:
            raise ValueError('Event-image state binding mismatch')
        state = states['items'][0]
        reference = state['value']
        if state['key'].get('value') != 0 or reference.get('type') != 'obj_ref':
            raise ValueError('Event image requires the normal component state')
        target = graph['objects'][reference['object_id']]
        fields = {prop['property_name']: prop['value'].get('value') for prop in target['properties']}
        asset = record['asset']
        if (not asset.startswith(ASSET_ROOT + '/') or not asset.endswith('.png')
                or target['class'] != 'TUIResourceTexture'
                or fields.get('FileName') != asset.replace('GameData/', 'GameData:/', 1)):
            raise ValueError('Cooked event-image resource path mismatch')
        source = safe_child(staged, asset)
        if sha256(source.read_bytes()) != record['asset_sha256']:
            raise ValueError('Staged event-image hash mismatch')
        relative = 'PC/Texture/' + asset.removeprefix('GameData/')[:-4] + '.tgv'
        if declared.count('ZZ:/' + relative) != 1:
            raise ValueError('Event texture must be declared exactly once')
        raw = safe_child(gen, relative).read_bytes()
        cooked = read_event_texture(raw)
        with Image.open(source) as original:
            comparison = compare_event_pixels(original.convert('RGBA'), cooked)
        records.append({'token': record['token'], 'texture': relative, 'sha256': sha256(raw),
                        'size': list(cooked.size), **comparison})
    return {'format': 'agf-event-images-readback-v1', 'components_sha256': sha256(components_raw),
            'images': records, 'cooked_verified': True, 'runtime_verified': False}


def compare_event_pixels(source, cooked):
    """Require exact alpha/opaque color, and at most one premultiplied RGB quantization unit."""
    if source.mode != 'RGBA' or cooked.mode != 'RGBA' or source.size != cooked.size:
        raise ValueError('Cooked event pixels differ in format or size')
    maximum_error = 0
    exact = True
    for original, actual in zip(source.getdata(), cooked.getdata()):
        alpha = original[3]
        if actual[3] != alpha:
            raise ValueError('Cooked event pixels differ in alpha')
        exact = exact and original == actual
        for channel in range(3):
            expected = round(original[channel] * alpha / 255)
            error = abs(actual[channel] - expected)
            tolerance = 0 if alpha in (0, 255) else 1
            if error > tolerance or actual[channel] > alpha:
                raise ValueError('Cooked event pixels differ from expected alpha-premultiplied color')
            maximum_error = max(maximum_error, error)
    return {'pixel_exact': exact, 'alpha_exact': True,
            'color_encoding': 'premultiplied_rgba8', 'max_rgb_quantization_error': maximum_error}
