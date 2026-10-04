"""Extract a portable, localized catalog of original WARNO unit icons."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile

from PIL import Image

from .cndf import decode
from .editor_catalog import discover_editor_catalog
from .game_resources import GameResources
from .label_tokens import label_token_key
from .native_campaign_source import NativeCampaignReader, properties
from .storage import sha256
from .tgv import read_texture


def capture_unit_catalog(game_root, template_root, destination, *, progress=None):
    game = GameResources(game_root)
    template = Path(template_root).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)

    def stage(percent, message):
        if progress is not None:
            progress(percent, message)

    stage(5, 'Reading verified unit catalog')
    catalog = discover_editor_catalog(template)
    if catalog['base_game']['status'] != 'verified':
        raise ValueError('The current base-game unit catalog is unavailable')
    source = (template / 'GameData/Generated/UserInterface/Textures/ButtonTexturesUnites.ndf').read_text(encoding='utf-8-sig')
    registrations = dict(re.findall(
        r'\(\s*"(Texture_Button_Unit_\w+)"\s*,\s*MAP\s*\[\s*\(\s*~/ComponentState/Normal\s*,\s*TUIResourceTexture\s*\(\s*FileName\s*=\s*"([^"]+)"',
        source))
    units = (template / 'GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf').read_text(encoding='utf-8-sig')
    blocks = re.split(r'\bexport\s+Descriptor_Unit_(\w+)\s+is\s+TEntityDescriptor\b', units)
    name_tokens = {}
    for identifier, block in zip(blocks[1::2], blocks[2::2]):
        tokens = re.findall(r'\bNameToken\s*=\s*[\'\"](\w+)', block)
        if len(tokens) == 1:
            name_tokens[identifier] = tokens[0]
    reader = NativeCampaignReader(game)
    scenario = next(iter(game.campaigns()))
    translations = reader.translations(scenario)
    entries = catalog['base_game']['entries']
    needed = {}
    for entry in entries:
        identifier = entry['id']
        token = name_tokens.get(identifier)
        if token is None or entry['icon_path'] not in registrations:
            raise ValueError('Verified unit lacks its name or icon registration: ' + identifier)
        key = label_token_key(token)
        localized = reader.text(scenario, key, identifier, domain='/Core/UNITS-')
        if any(not any('/Core/UNITS-' in item['resource'] for item in translations[language].get(key, []))
               for language in ('en', 'ru')):
            raise ValueError('Verified unit name is absent from the installed game: ' + identifier)
        entry['display_name'] = localized['ru'] or localized['en']
        entry['name_ru'] = localized['ru']
        entry['name_en'] = localized['en']
        icon_file = registrations[entry['icon_path']]
        entry['faction'] = ('NATO' if '/NATO/' in icon_file else 'PACT' if '/PACT/' in icon_file else 'Other')
        needed[icon_file] = None
    stage(15, 'Resolving original unit icon atlases')
    shared = game.shared()
    for path in shared.paths:
        if not path.startswith('PC/Atlas/UnitIcons-') or not path.endswith('/TextureSmall.atlas'):
            continue
        _, graph = decode(shared.read(path))
        for obj in graph['objects']:
            if obj['class'] != 'TTextureSmall':
                continue
            part = properties(obj)
            name = part.get('TexturePartFileName')
            if name not in needed:
                continue
            if needed[name] is not None:
                raise ValueError('Original unit icon appears in multiple atlases: ' + name)
            container = properties(graph['objects'][part['Container']['object_id']])
            texture = str(PurePosixPath(container['TextureFileName'].removeprefix('ZZ:/')).with_suffix('.tgv'))
            needed[name] = (texture, part.get('MinUV', [0, 0]), part['MaxUV'], path)
    if any(value is None for value in needed.values()):
        raise ValueError('An original unit icon is missing from the installed atlases')

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.editor-unit-icons-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'catalog'
        (staged / 'icons').mkdir(parents=True)
        by_texture = {}
        for file, (texture, low, high, atlas) in needed.items():
            by_texture.setdefault(texture, []).append((file, low, high, atlas))
        inventory = {}
        for index, (texture, parts) in enumerate(sorted(by_texture.items()), start=1):
            stage(20 + 70 * index // max(1, len(by_texture)),
                  f'Extracting unit icons ({index}/{len(by_texture)} atlases)')
            raw = shared.read(texture)
            image = read_texture(raw)[0].convert('RGBA')
            for file, low, high, atlas in parts:
                box = tuple(round(value * extent) for value, extent in zip(low + high, [image.width, image.height] * 2))
                if not 0 <= box[0] < box[2] <= image.width or not 0 <= box[1] < box[3] <= image.height:
                    raise ValueError('Unit icon atlas region is invalid: ' + file)
                icon = image.crop(box)
                icon.thumbnail((120, 64), Image.Resampling.LANCZOS)
                filename = hashlib.sha256(file.encode('utf-8')).hexdigest()[:20] + '.png'
                icon.save(staged / 'icons' / filename, compress_level=3)
                inventory[file] = {'path': '.native/unit-icons/' + filename,
                                   'file': 'icons/' + filename, 'sha256': sha256((staged / 'icons' / filename).read_bytes()),
                                   'atlas': atlas, 'texture': texture}
        for entry in entries:
            entry['icon_asset_path'] = inventory[registrations[entry['icon_path']]]['path']
        (staged / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        manifest = {'format': 'agf-editor-unit-icons/v1', 'game_root': str(game.root),
                    'catalog_entries': len(entries), 'icon_files': len(inventory),
                    'files': list(inventory.values()), 'runtime_verified': False}
        (staged / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        staged.rename(destination)
    stage(100, 'Unit catalog and icons ready')
    return manifest
