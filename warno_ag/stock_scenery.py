"""Read stock strategic scenery registrations without copying native assets."""
import re
from pathlib import Path

from .archives import read_directory
from .cndf import decode
from .storage import sha256


POINT_CLASSES = frozenset({
    'TSceneryDescriptorModel3D', 'TSceneryDescriptorMultiState',
    'TSceneryDescriptorMultiLOD', 'TSceneryDescriptorImpostor',
})


def scenery_catalog_from_graph(graph, decor_set, archive_sha256):
    if not isinstance(decor_set, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', decor_set) is None:
        raise ValueError('Invalid stock decor set name')
    if not isinstance(archive_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', archive_sha256) is None:
        raise ValueError('Stock scenery requires an archive SHA256')
    registrations = {}
    for obj in graph['objects']:
        if not obj['is_top_object'] or obj['class'] not in POINT_CLASSES:
            continue
        names = [prop['value'].get('value') for prop in obj['properties']
                 if prop['property_name'] == 'RegistrationName']
        if not names:
            continue
        if len(names) != 1 or not isinstance(names[0], str) or not names[0]:
            raise ValueError('Invalid stock scenery registration')
        name = names[0]
        if name in registrations:
            raise ValueError('Duplicate stock scenery registration: ' + name)
        registrations[name] = {'descriptor_class': obj['class'], 'descriptor_id': obj['id']}
    if not registrations:
        raise ValueError('No supported stock point scenery registrations')
    return {'format': 'agf-stock-scenery-v1', 'decor_set': decor_set,
            'archive_sha256': archive_sha256, 'registrations': registrations}


def load_stock_scenery(archive, decor_set='Steelman'):
    raw = Path(archive).read_bytes()
    header, entries, _ = read_directory(raw)
    name = f'NDF/DecorsSets/Scenery/{decor_set}.ndfbin'
    matches = [entry for entry in entries if entry.path == name]
    if len(matches) != 1:
        raise ValueError('Stock scenery archive must contain exactly one ' + name)
    entry = matches[0]
    start = header.file_offset + entry.offset
    _, graph = decode(raw[start:start + entry.size])
    return scenery_catalog_from_graph(graph, decor_set, sha256(raw))
