"""Publish event buttons in the INGAME dictionary used by the native UI."""
from pathlib import Path

from .cndf import decode
from .full_campaign import _pack_trad, _trad_data
from .modgen_registry import authored_build_name, authored_registry_path


LANGUAGES = ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')
INGAME_TOKEN = 'cfb544d804000000'


def _resource(root):
    return 'Localisation/Localisation/' + authored_build_name(root) + '/INTERFACE_INGAME'


def _registry(root):
    path = authored_registry_path(root)
    _, graph = decode(path.read_bytes())
    matches = []
    for obj in graph['objects']:
        properties = {prop['property_name']: prop['value'] for prop in obj['properties']}
        if properties.get('FileName', {}).get('value') == (
                'GameData:/Localisation/' + authored_build_name(root) + '/INTERFACE_INGAME.csv'):
            matches.append((obj, properties))
    if (len(matches) != 1 or matches[0][0]['class'] != 'TLocalisationDicoResource'
            or not matches[0][0]['is_top_object']
            or matches[0][1].get('DicoToken', {}).get('value_hex') != INGAME_TOKEN):
        raise ValueError('Event choice dictionary is not registered in INGAME')


def _paths(root, language):
    resource = _resource(root)
    return (f'Gen/{resource}-{language}.dic',
            f'Gen/AllPlatforms/{resource}-{language}.dic',
            f'Gen/AllPlatforms/Localisation/{language}/Localisation/{authored_build_name(root)}/INTERFACE_INGAME.dic')


def publish_ingame_choices(root, translations):
    root = Path(root).resolve()
    if set(translations) != set(LANGUAGES):
        raise ValueError('INGAME choice translations must cover every language')
    keys = set(translations['US'])
    if any(set(values) != keys for values in translations.values()):
        raise ValueError('INGAME choice keys differ between languages')
    if not keys:
        return {'choice_keys': 0, 'dictionaries': 0}
    _registry(root)
    updates = {}
    for language in LANGUAGES:
        paths = _paths(root, language)
        source = root / paths[0]
        values = _trad_data(source.read_bytes()) if source.is_file() else {}
        for key, text in translations[language].items():
            if key in values and values[key] != text:
                raise ValueError(f'INGAME choice localisation collision: {language}/{key.hex()}')
            values[key] = text
        raw = _pack_trad(values)
        updates.update({path: raw for path in paths})
    declared_path = root / 'Gen/DeclaredFiles.txt'
    declared = declared_path.read_text(encoding='utf-8').splitlines()
    for language in LANGUAGES:
        uri = f'ZZ:/{_resource(root)}-{language}.dic'
        if language != 'DEV' and uri not in declared:
            declared.append(uri)
    for relative, raw in updates.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    declared_path.write_text('\n'.join(declared) + '\n', encoding='utf-8', newline='\n')
    return validate_ingame_choices(root, keys, translations)


def validate_ingame_choices(root, keys, translations=None):
    root = Path(root).resolve()
    keys = set(keys)
    if not keys:
        return {'choice_keys': 0, 'dictionaries': 0}
    _registry(root)
    declared = set((root / 'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines())
    for language in LANGUAGES:
        paths = _paths(root, language)
        source = root / paths[0]
        if not source.is_file():
            raise ValueError(f'INGAME choice dictionary is missing: {language}')
        if language != 'DEV' and f'ZZ:/{_resource(root)}-{language}.dic' not in declared:
            raise ValueError(f'INGAME choice dictionary is not mounted: {language}')
        raw = source.read_bytes()
        values = _trad_data(raw)
        if not keys <= set(values):
            raise ValueError(f'INGAME choice keys are missing: {language}')
        if translations is not None and any(values[key] != translations[language][key] for key in keys):
            raise ValueError(f'INGAME choice text mismatch: {language}')
        for relative in paths[1:]:
            path = root / relative
            if not path.is_file() or path.read_bytes() != raw:
                raise ValueError(f'INGAME choice projection mismatch: {relative}')
    return {'choice_keys': len(keys), 'dictionaries': len(LANGUAGES)}


def script_choice_keys(graph, reachable=None):
    return {bytes.fromhex(prop['value']['value_hex'])
            for obj in graph['objects'] for prop in obj['properties']
            if (reachable is None or obj['id'] in reachable)
            and obj['class'] == 'TGDDescriptorCutsceneDialogWithMultipleChoice'
            and prop['property_name'].startswith('TokenBoutonChoix')
            and prop['value'].get('value_hex', '').startswith(b'AGF1'.hex())}
