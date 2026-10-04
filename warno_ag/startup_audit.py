"""Read-only Red Line startup resource audit, independent of AI build changes.

This is not a runtime smoke test and never launches WARNO.
"""
import argparse
import json
from pathlib import Path
from .event_localisation import script_choice_keys, validate_ingame_choices

from .bruderkrieg import _payloads
from .cndf import decode
from .current_campaign import _generated_dictionary, _trad_uint64_sorted
from .deployment import active_mods, default_mod_parent
from .full_campaign import DISPLAY_NAME, MOD_NAME, SCENARIO, _owned, _trad_data
from .modconfig import validate_scenario_config


LANGUAGES = ('FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')


def require_dictionary(root, declared, uri):
    if not uri.startswith('ZZ:/Localisation/') or '..' in uri.split('/'):
        raise ValueError(f'Unsupported dictionary URI: {uri}')
    if uri not in declared:
        raise ValueError(f'Runtime dictionary is not declared: {uri}')
    path = root / 'Gen' / uri.removeprefix('ZZ:/')
    if not path.is_file():
        raise ValueError(f'Declared runtime dictionary is missing: {uri}')
    raw = path.read_bytes()
    if not _trad_data(raw) or not _trad_uint64_sorted(raw):
        raise ValueError(f'Empty or incorrectly ordered TRAD: {uri}')


def audit(mod_parent):
    parent = Path(mod_parent).resolve()
    active = active_mods(parent)
    if active != [DISPLAY_NAME]:
        raise ValueError(f'Expected only the recovered Red Line installation active: {active}')
    root = parent / MOD_NAME
    files, receipt, _ = _owned(root)
    validate_scenario_config(files['Config.ini'], DISPLAY_NAME)
    expected = {f'{SCENARIO}_Definition.dat', f'{SCENARIO}_Details.dat'}
    if {p.name for p in (root / 'Scenarios').glob('*.dat')} != expected:
        raise ValueError('Unexpected scenario pack in active installation')
    declared = set((root / 'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines())
    sources = set()
    choice_keys = set()
    for pack in sorted((root / 'Scenarios').glob('*.dat')):
        payloads = _payloads(pack.read_bytes())  # validates archive checksums
        for name, raw in payloads.items():
            if not name.endswith('.ndfbin'):
                continue
            _, graph = decode(raw)
            choice_keys.update(script_choice_keys(graph))
            sources.update(s for s in graph['strings']
                           if s.startswith('ScenariosData:/') and s.endswith('.csv'))
    if not any(s.endswith('/TROPHIES.csv') for s in sources):
        raise ValueError('No trophy dictionary dependency found')
    required = {_generated_dictionary(s, lang) for s in sources for lang in LANGUAGES}
    required.update(uri for uri in declared if uri.endswith('.dic'))
    for uri in sorted(required):
        require_dictionary(root, declared, uri)
    dictionaries = list((root / 'Gen').rglob('*.dic'))
    for path in dictionaries:
        if not _trad_uint64_sorted(path.read_bytes()):
            raise ValueError(f'Unsorted dictionary projection: {path}')
    for lang in (*LANGUAGES, 'DEV'):
        raw = (root / f'Gen/Localisation/Localisation/Core/MAPS-{lang}.dic').read_bytes()
        for rel in (f'Gen/AllPlatforms/Localisation/Localisation/Core/MAPS-{lang}.dic',
                    f'Gen/AllPlatforms/Localisation/{lang}/Localisation/Core/MAPS.dic'):
            if (root / rel).read_bytes() != raw:
                raise ValueError(f'MAPS projection mismatch: {rel}')
    registry = root / 'Gen/NDF/Localisation/WarnoAGFRedLineBuild.ndfbin'
    decode(registry.read_bytes())
    choice_localisation = validate_ingame_choices(root, choice_keys)
    return {'active_mods': active, 'bundle_id': receipt['bundle_id'],
            'installed_files_verified': len(files), 'dictionary_sources': sorted(sources),
            'runtime_dictionaries_verified': len(required),
            'sorted_dictionary_files': len(dictionaries),
            'startup_resource_audit': 'passed', 'runtime_verified': False,
            'choice_localisation': choice_localisation,
            'ai_semantic_contract_checked': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod-parent', type=Path, default=default_mod_parent())
    args = parser.parse_args()
    print(json.dumps(audit(args.mod_parent), indent=2, ensure_ascii=False))
