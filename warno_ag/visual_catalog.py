"""Resolve tactical roster visuals from explicit local game resource references."""
from pathlib import Path
from functools import lru_cache
import re


@lru_cache(maxsize=1)
def current_visual_catalog():
    return build_visual_catalog(Path(__file__).resolve().parents[1] / 'artifacts/modgen-201602-template')


def _source(path):
    text = path.read_text(encoding='utf-8-sig')
    pattern = r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|//[^\r\n]*|/\*.*?\*/"
    return re.sub(pattern, lambda match: ' ' if match[0].startswith(('//', '/*'))
                  else match[0], text, flags=re.DOTALL)


def build_visual_catalog(template_root):
    root = Path(template_root)
    resources = root / 'GameData/Gameplay/Gfx/DepictionResources'
    models = {}
    categories = {'Char': 'vehicle', 'Vehicule': 'vehicle', 'Towed': 'vehicle',
                  'Helico': 'helicopter', 'Avion': 'airplane'}
    for path in sorted(resources.rglob('*.ndf')):
        text = _source(path)
        for name in re.findall(r'\bexport\s+(Modele_\w+)\s+is\s+TResourceMesh\b', text):
            if name in models:
                raise ValueError('Ambiguous visual mesh export: ' + name)
            category = ('infantry' if path.name == 'Gfx_infanterie.ndf'
                        else categories.get(path.parent.name))
            models[name] = {'mesh': name, 'category': category,
                            'mesh_source': path.relative_to(root).as_posix()}
    textures_path = root / 'GameData/Generated/UserInterface/Textures/ButtonTexturesUnites.ndf'
    textures = re.findall(r'\(\s*"(Texture_Button_Unit_\w+)"\s*,\s*MAP\s*\[',
                          _source(textures_path))
    if len(textures) != len(set(textures)):
        raise ValueError('Ambiguous tactical unit texture registration')
    textures = set(textures)
    units_path = root / 'GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf'
    text = _source(units_path)
    blocks = re.split(r'\bexport\s+Descriptor_Unit_(\w+)\s+is\s+TEntityDescriptor\b', text)
    catalog = {}
    for identifier, block in zip(blocks[1::2], blocks[2::2]):
        if identifier in catalog:
            raise ValueError('Ambiguous tactical unit export: ' + identifier)
        references = re.findall(r'ReferenceMesh\s*=\s*\$/GFX/DepictionResources/(\w+)', block)
        infantry = re.findall(r'MimeticName\s*=\s*"squad_(\w+)"', block)
        if len(references) > 1 or len(infantry) > 1 or references and infantry:
            raise ValueError('Ambiguous tactical visual reference: ' + identifier)
        if references:
            mesh = references[0]
        elif infantry:
            mesh = 'Modele_' + infantry[0]
        else:
            raise ValueError('Missing tactical visual reference: ' + identifier)
        if mesh not in models or models[mesh]['category'] is None:
            raise ValueError('Unresolved tactical visual mesh: ' + identifier + ': ' + mesh)
        texture = 'Texture_Button_Unit_' + identifier
        if texture not in textures:
            raise ValueError('Missing tactical unit texture: ' + identifier)
        tag_sets = re.findall(r'TagSet\s*=\s*\[([^]]*)\]', block)
        tags = re.findall(r'"([^"\r\n]+)"', tag_sets[0]) if len(tag_sets) == 1 else []
        catalog[identifier] = {**models[mesh], 'texture': texture, 'tags': tags}
    if not catalog:
        raise ValueError('Tactical visual catalog is empty')
    return catalog
