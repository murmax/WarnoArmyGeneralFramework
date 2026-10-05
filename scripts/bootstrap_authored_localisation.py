"""Build local adapter compatibility dictionaries from a non-textual key recipe.

The recipe contains hash IDs and font character inventories only. Generated
TRAD files stay in ignored artifacts and are not a release input themselves;
authored campaign packaging replaces their prototype text with YAML text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from warno_ag.current_campaign import (EARLY_ISOLATED_SHA, EARLY_MAPS_COUNT,
    EARLY_MAPS_SHA, GLYPH_HASH, SCENARIO, _dictionary_keys, _early_maps_keys,
    _isolated_hash)
from warno_ag.full_campaign import _pack_trad


ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / 'warno_ag/data/localisation-compatibility.json'
LANGUAGES = ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')
CATEGORIES = ('TROPHIES', 'Scripting/Dialog', 'Scripting/Localization')
PLACEHOLDER = 'AGF bootstrap placeholder'
LEGACY_TITLE = 'Red Line 1989'


def bootstrap(destination: Path, *, recipe_path: Path = RECIPE) -> dict:
    recipe = json.loads(Path(recipe_path).read_text(encoding='utf-8'))
    if (recipe.get('format') != 'agf-redline-localisation-bootstrap/v1'
            or recipe.get('scenario') != SCENARIO
            or set(recipe.get('categories', {})) != set(CATEGORIES)):
        raise ValueError('Unsupported compatibility localisation recipe')
    early = {bytes.fromhex(value) for value in recipe['early_maps_keys']}
    titles = {bytes.fromhex(value) for value in recipe['title_keys']}
    if (len(early) != EARLY_MAPS_COUNT or not titles <= early
            or hashlib.sha256(b''.join(sorted(early))).hexdigest() != EARLY_MAPS_SHA
            or hashlib.sha256(b''.join(sorted(_isolated_hash(key) for key in early))).hexdigest()
            != EARLY_ISOLATED_SHA):
        raise ValueError('Compatibility early-load key identity changed')
    root = Path(destination).resolve()
    if not root.is_relative_to((ROOT / 'artifacts').resolve()):
        raise ValueError('Compatibility dictionaries must stay under ignored artifacts/')
    if root.exists():
        raise FileExistsError(root)
    target = root / 'Gen/Localisation/Localisation'
    scenario = target / SCENARIO
    all_keys = set()
    for name in CATEGORIES:
        category = recipe['categories'][name]
        if set(category) != {'base', 'ru_us_extra'}:
            raise ValueError('Unsupported dictionary category layout')
        base = {bytes.fromhex(value) for value in category['base']}
        extra = {bytes.fromhex(value) for value in category['ru_us_extra']}
        if (base & extra or GLYPH_HASH in base | extra or
                any(len(key) != 8 for key in base | extra)):
            raise ValueError('Invalid compatibility dictionary keys')
        all_keys.update(base | extra)
        alphabets = recipe['glyph_alphabets'][name]
        if set(alphabets) != set(LANGUAGES):
            raise ValueError('Incomplete compatibility font alphabets')
        for language in LANGUAGES:
            keys = base | (extra if language in ('RU', 'US') else set())
            values = {key: LEGACY_TITLE if key in titles else PLACEHOLDER for key in keys}
            values[GLYPH_HASH] = alphabets[language]
            path = scenario / f'{name}-{language}.dic'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_pack_trad(values))
    if len(all_keys) != recipe['expected_unique_keys'] or not early <= all_keys:
        raise ValueError('Compatibility dictionary union differs from recipe')
    core = target / 'Core'
    core.mkdir(parents=True)
    for language in ('RU', 'US'):
        (core / f'MAPS-{language}.dic').write_bytes(_pack_trad({
            key: LEGACY_TITLE if key in titles else PLACEHOLDER for key in early}))
    if _dictionary_keys(target) != all_keys or _early_maps_keys(target) != early:
        raise ValueError('Generated compatibility dictionaries failed readback')
    report = {'format': 'agf-redline-localisation-bootstrap-report/v1',
              'files': 26, 'unique_keys': len(all_keys), 'early_keys': len(early),
              'prototype_text_is_placeholder': True, 'runtime_verified': False}
    (root / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n',
                                                 encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(bootstrap(args.destination), indent=2))
