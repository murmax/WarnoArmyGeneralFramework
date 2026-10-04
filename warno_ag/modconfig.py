"""Validation of the Config.ini emitted by WARNO's own ModGen."""
import configparser
import re


def _parse(raw):
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(';',), strict=True)
    parser.optionxform = str
    try:
        parser.read_string(raw.decode('utf-8-sig'))
    except (UnicodeError, configparser.Error) as exc:
        raise ValueError('Invalid mod Config.ini') from exc
    if parser.defaults() or set(parser.sections()) != {'Properties', 'Config'}:
        raise ValueError('Unexpected mod Config.ini sections')
    return parser


def _validate_local_mod_id(local_mod_id):
    if type(local_mod_id) is not int or not 0 < local_mod_id < (1 << 63):
        raise ValueError('Invalid local mod identity')


def validate_scenario_config(raw, display_name, *, local_mod_id=None):
    """Accept only a gameplay config shaped by the current official generator."""
    parser = _parse(raw)
    props, compatibility = parser['Properties'], parser['Config']
    if props.get('Name') != display_name:
        raise ValueError('Scenario display name mismatch')
    if local_mod_id is not None:
        _validate_local_mod_id(local_mod_id)
        if props.get('ID') != str(local_mod_id):
            raise ValueError('Scenario local mod identity mismatch')
    if props.get('ModGenVersion') != '201602':
        raise ValueError('Unexpected ModGen revision')
    if props.get('DeckFormatVersion') != '1':
        raise ValueError('Gameplay deck format is missing')
    if props.get('CosmeticOnly') != '0' or 'CosmeticOnly' in compatibility:
        raise ValueError('CosmeticOnly must be in [Properties], never in [Config]')
    hashes = dict(compatibility)
    if not hashes:
        raise ValueError('Official ModGen compatibility fingerprint is missing')
    if any(not re.fullmatch(r'[0-9a-f]{32}', value) for value in hashes.values()):
        raise ValueError('Invalid ModGen compatibility fingerprint')
    return parser


def scenario_config(source, display_name, *, local_mod_id=None):
    """Set local identity without changing the generator's compatibility data."""
    parser = _parse(source)
    if parser['Properties'].get('ModGenVersion') != '201602':
        raise ValueError('Unexpected source ModGen revision')
    cosmetic_values = [parser[section]['CosmeticOnly'] for section in parser.sections()
                       if 'CosmeticOnly' in parser[section]]
    if len(cosmetic_values) > 1 or any(value != '0' for value in cosmetic_values):
        raise ValueError('Source Config.ini has conflicting CosmeticOnly flags')
    text = source.decode('utf-8-sig')
    if local_mod_id is not None:
        _validate_local_mod_id(local_mod_id)
        previous_id = parser['Properties'].get('ID')
        if previous_id not in (None, '0', str(local_mod_id)):
            raise ValueError('Refusing to replace a different published or local mod identity')
        replacement = f'ID = {local_mod_id} ; AGF local identity, not a Workshop publication'
        if previous_id is None:
            text = text.replace('[Properties]', '[Properties]\r\n' + replacement, 1)
        else:
            text, replaced = re.subn(r'(?m)^ID\s*=.*$', replacement, text)
            if replaced != 1:
                raise ValueError('Source Config.ini has no unique ID field')
    if parser['Properties'].get('DeckFormatVersion') == '0':
        text, count = re.subn(r'(?m)^(DeckFormatVersion\s*=\s*)0(?=\s|;|$)', r'\g<1>1', text)
        if count != 1:
            raise ValueError('Source Config.ini has no unique DeckFormatVersion')
    # Current CopyModGenData appends this gameplay flag after [Config].  Real
    # current Workshop packages keep it in [Properties]; in [Config] the game
    # interprets it as a cluster compatibility key and disables the mod.
    text, cosmetic_count = re.subn(
        r'(?m)^CosmeticOnly\s*=\s*0(?:\s*;[^\r\n]*)?\r?\n?', '', text)
    if cosmetic_count != len(cosmetic_values):
        raise ValueError('Source Config.ini has no unique CosmeticOnly flag')
    config_marker = re.search(r'(?m)^\[Config\].*$', text)
    if config_marker is None:
        raise ValueError('Source Config.ini has no [Config] section')
    prefix = text[:config_marker.start()].rstrip('\r\n')
    text = prefix + '\r\nCosmeticOnly = 0\r\n\r\n' + text[config_marker.start():]
    pattern = r'(?m)^(Name\s*=\s*).*$'
    output, count = re.subn(pattern, rf'\g<1>{display_name}', text, count=1)
    if count != 1:
        raise ValueError('Source Config.ini has no Name field')
    raw = output.replace('\n', '\r\n').replace('\r\r\n', '\r\n').encode('utf-8')
    validate_scenario_config(raw, display_name, local_mod_id=local_mod_id)
    return raw
