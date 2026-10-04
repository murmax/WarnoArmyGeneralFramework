"""Validate runtime files referenced by the ModGen localisation registry."""
from pathlib import Path

from .cndf import decode
from .modgen_registry import authored_registry_path


LANGUAGES = ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')
REGISTRY = Path('Gen/NDF/Localisation/WarnoAGFRedLineBuild.ndfbin')


def validate_registry_localisation(root):
    root = Path(root).resolve()
    _, graph = decode(authored_registry_path(root).read_bytes())
    declared = set((root / 'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines())
    sources = []
    for obj in graph['objects']:
        if obj['class'] != 'TLocalisationDicoResource':
            continue
        properties = {row['property_name']: row['value'] for row in obj['properties']}
        filename = properties.get('FileName', {}).get('value')
        if (isinstance(filename, str) and filename.startswith('GameData:/Localisation/CampagneStrat_')
                and filename.endswith('.csv')):
            sources.append(filename)
    required = []
    for source in sources:
        stem = source.removeprefix('GameData:/').removesuffix('.csv')
        for language in LANGUAGES:
            uri = f'ZZ:/Localisation/{stem}-{language}.dic'
            path = root / 'Gen' / uri.removeprefix('ZZ:/')
            if not path.is_file() or (language != 'DEV' and uri not in declared):
                raise ValueError('Missing or undeclared registry dictionary: ' + uri)
            required.append(uri)
    if len(sources) != 3 or len(required) != 24:
        raise ValueError('Unexpected campaign registry dictionary inventory')
    return {'sources': sources, 'required_dictionaries': len(required)}
