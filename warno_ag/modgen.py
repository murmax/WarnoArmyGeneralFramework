"""Deterministic Army General Pawn, Deck, division and OOB source generation.

Full YAML definitions emit explicit gameplay descriptors. The legacy JSON
catalog remains a separate compatibility/bootstrap input; shared visual and
engine resources are retained explicitly.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import uuid
from functools import lru_cache
from pathlib import Path

from .ndfsource import export_block
from .storage import sha256

DEFAULT_BATTALIONS_CONFIG = Path(__file__).resolve().parent / 'data/catalog-compatibility.json'
_GUID_NAMESPACE = uuid.UUID('03e3ea9b-6d02-57c3-a76a-d23b839763a6')
MAX_UI_TEXT_UNITS = 30


@lru_cache(maxsize=1)
def strategic_pack_signatures():
    source = Path(__file__).resolve().parents[1] / 'artifacts/modgen-201602-template/GameData/Generated/Gameplay/Decks/StrategicPacks.ndf'
    text = _read(source)
    result = {}
    for match in re.finditer(r'(?m)^(Descriptor_StrategicPack_\w+) is DeckPackDescriptor\s*\(\s*([^)]*)\)', text):
        fields = dict(re.findall(r'(?m)^\s*(\w+)\s*=\s*([^\r\n]+)', match[2]))
        if set(fields) - {'Xp', 'Unit', 'Transport', 'Number'} or 'Unit' not in fields:
            raise ValueError('Unsupported strategic pack schema: ' + match[1])
        result[match[1]] = {'unit': fields['Unit'].strip(),
                           'transport': fields.get('Transport', '').strip(),
                           'experience': int(fields.get('Xp', 0)),
                           'number': int(fields.get('Number', 1))}
    if not result:
        raise ValueError('Strategic pack catalog is empty')
    return result


@lru_cache(maxsize=1)
def _tactical_unit_source():
    return _read(Path(__file__).resolve().parents[1] /
                 'artifacts/modgen-201602-template/GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf')


@lru_cache(maxsize=512)
def is_tactical_transport(unit_id):
    """Check the game's unit descriptor instead of treating every vehicle as transport."""
    if not isinstance(unit_id, str) or re.fullmatch(r'[A-Za-z0-9_]+', unit_id) is None:
        return False
    block = export_block(_tactical_unit_source(), 'Descriptor_Unit_' + unit_id,
                         'TEntityDescriptor')
    return bool(re.search(r'TAcknowUnitType_\w*Transport|Vehicule_Transport|Helico\w*_Transport', block))


def prepare_custom_strategic_packs(template_path, destination, custom_packs):
    """Append campaign-owned packs for verified tactical units absent from AG."""
    template = _read(template_path)
    blocks = []
    for pack in custom_packs:
        name = 'Descriptor_StrategicPack_' + pack['id']
        if name + ' is DeckPackDescriptor' in template or any(name in block for block in blocks):
            raise ValueError('Duplicate custom strategic pack: ' + name)
        body = [name + ' is DeckPackDescriptor', '(',
                '    Xp = ' + str(pack['experience'])]
        if pack['transport']:
            body.append('    Transport = $/GFX/Unit/Descriptor_Unit_' + pack['transport'])
        body.extend(['    Unit = $/GFX/Unit/Descriptor_Unit_' + pack['unit'],
                     '    Number = ' + str(pack['number']), ')'])
        blocks.append('\n'.join(body))
    path = _write(destination, template.rstrip() + '\n\n' + '\n\n'.join(blocks) + '\n')
    return {'added_packs': [pack['id'] for pack in custom_packs],
            'template_sha256': sha256(Path(template_path).read_bytes()),
            'output_sha256': sha256(path.read_bytes())}


def _read(path):
    return Path(path).resolve().read_text(encoding='utf-8')


def _write(path, text):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    return path


def _token(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Z0-9_]+', value) is not None


def _ui_text(value):
    """WARNO UIGenericEditableText stores at most 30 UTF-16 code units."""
    return (isinstance(value, str) and bool(value)
            and len(value.encode('utf-16-le')) // 2 <= MAX_UI_TEXT_UNITS)


def load_battalion_config(path=DEFAULT_BATTALIONS_CONFIG):
    """Load and strictly validate the readable campaign OOB specification."""
    try:
        data = json.loads(_read(path))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid battalion configuration: {exc}') from exc
    if set(data) != {'schema', 'battalions'} or data['schema'] != 1 or not isinstance(data['battalions'], list):
        raise ValueError('Unsupported battalion configuration schema')
    ids, exports, tokens, spawns = set(), set(), set(), set()
    for row in data['battalions']:
        required = {'id', 'mode', 'role', 'unit_export', 'deck_export', 'base_unit'}
        if not isinstance(row, dict) or not required <= set(row):
            raise ValueError('Battalion entry has missing fields')
        if row['mode'] not in {'clone_replace', 'authored'} or not all(isinstance(row[k], str) and row[k] for k in required):
            raise ValueError('Invalid battalion identity')
        if row['id'] in ids or row['unit_export'] in exports or row['deck_export'] in exports:
            raise ValueError('Duplicate battalion identity')
        ids.add(row['id']); exports.update((row['unit_export'], row['deck_export']))
        mapped = row.get('map')
        event_deployment = row.get('event_deployment')
        if (mapped is None) == (event_deployment is None):
            raise ValueError('Battalion must have exactly one deployment mode')
        if mapped is not None:
            if set(mapped) != {'spawn', 'x', 'y'} or mapped['spawn'] in spawns or not isinstance(mapped['spawn'], str):
                raise ValueError('Invalid or duplicate map spawn')
            spawns.add(mapped['spawn'])
        elif (not isinstance(event_deployment, dict)
              or set(event_deployment) != {'event', 'choice', 'position_guid', 'objective_guid'}
              or event_deployment['event'] not in {'nato', 'pact'}
              or event_deployment['choice'] not in {0, 1}
              or not isinstance(event_deployment['position_guid'], str)
              or not isinstance(event_deployment['objective_guid'], str)
              or not re.fullmatch(r'[0-9a-fA-F]{32}', event_deployment['position_guid'])
              or not re.fullmatch(r'[0-9a-fA-F]{32}', event_deployment['objective_guid'])):
            raise ValueError('Invalid event battalion deployment')
        if row['mode'] == 'clone_replace':
            if set(row) - (required | {'map', 'event_deployment', 'base_deck', 'replace_pack', 'expected_slots', 'expected_changed_slots'}):
                raise ValueError('Unexpected clone battalion field')
            if not {'replace_pack', 'expected_slots', 'expected_changed_slots'} <= set(row):
                raise ValueError('Clone battalion is incomplete')
            continue
        needed = {'coalition', 'country', 'name', 'name_token', 'base_division', 'division', 'organization', 'state', 'companies'}
        if not needed <= set(row):
            raise ValueError('Authored battalion is incomplete')
        state = row['state']; org = row['organization']
        casualties = state.get('casualties') if isinstance(state, dict) else None
        if (not _token(row['name_token']) or not _ui_text(row['name'])
                or not isinstance(row['companies'], list) or not row['companies']
                or not isinstance(state, dict) or not isinstance(org, dict)
                or not _ui_text(org.get('name'))
                or state.get('frozen_turns', -1) < 0 or state.get('fatigue', -1) < 0
                or set(casualties or ()) != {'count', 'random_range', 'type'}
                or any(type(casualties[key]) is not int or casualties[key] < 0
                       for key in ('count', 'random_range', 'type'))):
            raise ValueError('Invalid authored battalion state')
        for value in (row['name_token'], org.get('name_token')):
            if not _token(value) or value in tokens: raise ValueError('Invalid duplicate localisation token')
            tokens.add(value)
        for company in row['companies']:
            if (not isinstance(company, dict) or not _token(company.get('name_token'))
                    or not _ui_text(company.get('name')) or not company.get('platoons')):
                raise ValueError('Invalid company')
            if company['name_token'] in tokens: raise ValueError('Duplicate localisation token')
            tokens.add(company['name_token'])
            for platoon in company['platoons']:
                if (not isinstance(platoon, dict) or not _token(platoon.get('name_token'))
                        or not _ui_text(platoon.get('name')) or not platoon.get('packs')):
                    raise ValueError('Invalid platoon')
                if platoon['name_token'] in tokens: raise ValueError('Duplicate localisation token')
                tokens.add(platoon['name_token'])
                for pack in platoon['packs']:
                    if not isinstance(pack, dict) or not isinstance(pack.get('pack'), str) or type(pack.get('count')) is not int or pack['count'] < 1:
                        raise ValueError('Invalid platoon pack')
    if not data['battalions']:
        raise ValueError('Battalion configuration is empty')
    # DeckIdentifier deliberately follows the public battalion id.  Expose it
    # as a derived field for consumers without duplicating it in user config.
    for row in data['battalions']:
        row['deck_id'] = row['id']
    return data


CUSTOM_BATTALIONS = tuple(load_battalion_config()['battalions'])


def campaign_spawns(config=None):
    return [{'name': r['map']['spawn'], 'x': r['map']['x'], 'y': r['map']['y'],
             'class_name': '$/GFX/Pawn/' + r['unit_export']}
            for r in (config or load_battalion_config())['battalions'] if 'map' in r]


def _replace_one(block, old, new):
    if block.count(old) != 1: raise ValueError(f'Expected exactly one {old!r}')
    return block.replace(old, new)


def _set_field(block, name, value):
    pattern = r'(?m)^(\s*' + re.escape(name) + r'\s*=\s*)[^\n]+'
    block, count = re.subn(pattern, r'\g<1>' + value, block, count=1)
    if count != 1: raise ValueError(f'Missing field {name}')
    return block


def _replace_list(block, name, values):
    pattern = r'(?ms)^(\s*' + re.escape(name) + r'\s*=\s*\n\s*\[).*?^(\s*\])'
    replacement = r'\g<1>\n' + ''.join('        ' + value + ',\n' for value in values) + r'\g<2>'
    block, count = re.subn(pattern, replacement, block, count=1)
    if count != 1: raise ValueError(f'Missing list {name}')
    return block


def _clone_pawn(template, row):
    if row['mode'] == 'authored' and 'strategic' in row:
        from .pawn import authored_pawn
        return authored_pawn(row, _GUID_NAMESPACE)
    block = export_block(template, row['base_unit'], 'TEntityDescriptor').rstrip()
    base = row['base_unit'].removeprefix('Descriptor_Unit_'); deck = row['id']
    guid = str(uuid.uuid5(_GUID_NAMESPACE, row['unit_export']))
    block = _replace_one(block, f'export {row["base_unit"]} is TEntityDescriptor', f'export {row["unit_export"]} is TEntityDescriptor')
    block, count = re.subn(r'DescriptorId\s*= GUID:\{[0-9a-fA-F-]+\}', f'DescriptorId       = GUID:{{{guid}}}', block, count=1)
    if count != 1: raise ValueError('Pawn descriptor GUID missing')
    block = _replace_one(block, f"ClassNameForDebug  = 'Pawn_{base}'", f"ClassNameForDebug  = 'Pawn_{deck}'")
    block = _replace_one(block, f'BlackHoleKey        = "{base}"', f'BlackHoleKey        = "{deck}"')
    block = _replace_one(block, f"DeckIdentifier = '{base}'", f"DeckIdentifier = '{deck}'")
    if row['mode'] == 'authored':
        block = _set_field(block, 'Coalition', 'TWargameCoalition/' + row['coalition'])
        block = _set_field(block, 'MotherCountry', "'" + row['country'] + "'")
        block = _set_field(block, 'InitialActionPoint', str(row['state']['action_points']['initial']))
        block = _set_field(block, 'ActionPointRecoveryPerTurn', str(row['state']['action_points']['recovery']))
        block = _set_field(block, 'NbInitialActionsPointsForProducedPawn', str(row['state']['action_points']['recovery']))
        block = _set_field(block, 'NameToken', "'" + row['name_token'] + "'")
        block, count = re.subn(r'(StrategicFatigueModuleDescriptor\(\s*InitialFatigue\s*=\s*)\d+', r'\g<1>' + str(row['state']['fatigue']), block, count=1)
        if count != 1: raise ValueError('Pawn fatigue field missing')
    return block, guid


def prepare_current_units(template_path, destination, battalions=None, airfields=None):
    from .aviation import authored_airfield

    template = _read(template_path)
    if 'export Descriptor_Unit_RDLN_' in template: raise ValueError('Unit template already contains RDLN exports')
    rows = list(CUSTOM_BATTALIONS if battalions is None else battalions)
    fields = list(airfields or [])
    cloned = [_clone_pawn(template, row) for row in rows]
    cloned.extend((authored_airfield(row), row['descriptor_guid']) for row in fields)
    output = template.rstrip() + '\n\n' + '\n\n'.join(x[0] for x in cloned) + '\n'
    destination = _write(destination, output)
    return {'template_sha256': sha256(Path(template_path).read_bytes()), 'output_sha256': sha256(destination.read_bytes()),
            'added_exports': [row['unit_export'] for row in rows + fields], 'descriptor_guids': [x[1] for x in cloned]}


def prepare_current_ghosts(template_path, destination, battalions=None):
    from .pawn import authored_depiction, pawn_visual, validate_strategy

    template = _read(template_path)
    rows = CUSTOM_BATTALIONS if battalions is None else battalions
    entries, keys, depictions = [], set(), []
    for row in rows:
        key = row['id']
        if not re.fullmatch(r'[A-Za-z0-9_]+', key) or key in keys:
            raise ValueError('Invalid or duplicate ghost mimetic key: ' + key)
        keys.add(key)
        if 'strategic' in row:
            validate_strategy(row['strategic'])
            visual = pawn_visual(row)[0]
            if isinstance(row['strategic']['visual'], dict):
                depictions.append(authored_depiction(row))
        else:
            visual = row['base_unit'].removeprefix('Descriptor_Unit_')
        if not re.search(r'(?m)^Depiction_' + re.escape(visual) + r' is ', template + '\n'.join(depictions)):
            raise ValueError('Missing ghost mimetic visual: ' + visual)
        if re.search(r"\(\s*'" + re.escape(key) + r"'\s*,", template):
            raise ValueError('Ghost mimetic key already registered: ' + key)
        entries.append("        ( '" + key + "', Depiction_" + visual + ' ),')
    output = template.rstrip() + '\n\n' + '\n'.join(depictions) + '\nunnamed TGhostMimeticRegistration\n(\n'
    output += '    GfxProperties = $/DepictionCore/GfxProperties\n    GhostMimetics = MAP\n    [\n'
    output += '\n'.join(entries) + '\n    ]\n)\n'
    destination = _write(destination, output)
    return {'keys': sorted(keys), 'output_sha256': sha256(destination.read_bytes())}


def _authored_deck(row, packs):
    packed, groups, index = [], [], 0
    for number, company in enumerate(row['companies'], 1):
        lines = []
        for platoon in company['platoons']:
            pairs=[]
            for item in platoon['packs']:
                if packs.count(item['pack'] + ' is DeckPackDescriptor') != 1: raise ValueError('Missing strategic pack: ' + item['pack'])
                packed.extend([item['pack']] * item['count']); pairs.append(f'({index},{item["count"]})'); index += item['count']
            lines += ['        TDeckSmartGroupDescriptor', '        (', f'            Name = "{platoon["name_token"]}"']
            if platoon.get('hq'): lines += ['            IsHQ = True']
            lines += ['            PackIndexUnitNumberList =', '            ['] + ['                ' + x + ',' for x in pairs] + ['            ]', '        ),']
        groups.append('\n'.join([f'Descriptor_CombatGroup_{row["id"]}_{number} is TDeckCombatGroupDescriptor', '(', f'    Name = "{company["name_token"]}"'] + (['    IsHQ = True'] if company.get('hq') else []) + ['    SmartGroupList =', '    ['] + lines + ['    ]', ')']))
    deck = '\n'.join([f'export {row["deck_export"]} is TDeckDescriptor', '(', f"    DeckIdentifier = '{row['id']}'", f"    DeckDivision = $/GFX/Division/{row['division']}", '    DeckPackList =', '    ['] + [f'        ~/{x},' for x in packed] + ['    ]', '    DeckCombatGroupList =', '    ['] + [f'        ~/Descriptor_CombatGroup_{row["id"]}_{i},' for i in range(1, len(groups)+1)] + ['    ]', ')'])
    return deck, groups, len(packed)


def _clone_division(template, row):
    """Give an authored battalion an isolated division with no stock deck rule.

    The stock division rules intentionally reject units and experience levels
    outside their historical TO&E.  A campaign-authored deck must not inherit
    those limits silently; a private clone with ``DivisionRule = nil`` is the
    engine-supported representation used by WARNO's challenge divisions.
    """
    if 'division_definition' in row:
        definition = row['division_definition']
        guid = str(uuid.uuid5(_GUID_NAMESPACE, row['division']))
        coalition = definition['coalition']
        return '\n'.join([
            f'export {row["division"]} is TDeckDivisionDescriptor', '(',
            f'    DescriptorId = GUID:{{{guid}}}',
            f"    CfgName = '{definition['id']}'",
            f"    DivisionName = '{definition['name_token']}'",
            '    InterfaceOrder = -1.0',
            f'    DivisionCoalition = TWargameCoalition/{coalition}',
            f"    DivisionTags = ['STRAT', '{coalition}']", '    DivisionRule = nil',
            f'    EmblemTexture = "{definition["emblem"]}"',
            '    StandoutUnits =', '    [', '    ]', ')',
        ]), guid
    block=export_block(template,row['base_division'],'TDeckDivisionDescriptor').rstrip()
    guid=str(uuid.uuid5(_GUID_NAMESPACE,row['division']))
    block=_replace_one(block,f'export {row["base_division"]} is TDeckDivisionDescriptor',
                       f'export {row["division"]} is TDeckDivisionDescriptor')
    block,count=re.subn(r'DescriptorId\s*= GUID:\{[0-9a-fA-F-]+\}',
                        f'DescriptorId = GUID:{{{guid}}}',block,count=1)
    if count!=1: raise ValueError('Division descriptor GUID missing')
    block=_set_field(block,'CfgName',"'"+row['id']+"'")
    block=_set_field(block,'DivisionRule','nil')
    # StandoutUnits is validated against the division's permitted units.  Once
    # the source division rule is intentionally removed, inherited showcase
    # units become invalid dangling membership claims.
    block=_replace_list(block,'StandoutUnits',[])
    return block,guid


def prepare_current_divisions(template_path, destination, battalions=None):
    template=_read(template_path)
    if 'export Descriptor_Deck_Division_RDLN_' in template:
        raise ValueError('Division template already contains RDLN exports')
    authored=[row for row in (CUSTOM_BATTALIONS if battalions is None else battalions) if row['mode']=='authored']
    unique = {}
    for row in authored:
        previous = unique.setdefault(row['division'], row)
        if previous.get('division_definition') != row.get('division_definition'):
            raise ValueError('Conflicting authored division definition: ' + row['division'])
    authored = list(unique.values())
    cloned=[_clone_division(template,row) for row in authored]
    output=template.rstrip()+'\n\n'+'\n\n'.join(item[0] for item in cloned)+'\n'
    destination=_write(destination,output)
    return {'template_sha256':sha256(Path(template_path).read_bytes()),
            'output_sha256':sha256(destination.read_bytes()),
            'added_exports':[row['division'] for row in authored],
            'descriptor_guids':[item[1] for item in cloned]}


def prepare_current_decks(template_path, packs_path, destination, battalions=None):
    template, packs = _read(template_path), _read(packs_path)
    if 'export Descriptor_Deck_RDLN_' in template: raise ValueError('Deck template already contains RDLN exports')
    blocks=[]; composition={}
    for row in (CUSTOM_BATTALIONS if battalions is None else battalions):
        if row['mode'] == 'authored':
            block, _, slots = _authored_deck(row, packs); composition[row['id']]={'slots': slots, 'companies': len(row['companies'])}
        else:
            old, new = row['replace_pack']['old'], row['replace_pack']['new']
            if packs.count(old + ' is DeckPackDescriptor') != 1 or packs.count(new + ' is DeckPackDescriptor') != 1: raise ValueError('Missing strategic pack')
            block = export_block(template, row['base_deck'], 'TDeckDescriptor').rstrip(); base=row['base_deck'].removeprefix('Descriptor_Deck_')
            before=block.count('~/Descriptor_StrategicPack_'); changed=block.count('~/' + old)
            block=_replace_one(block, f'export {row["base_deck"]} is TDeckDescriptor', f'export {row["deck_export"]} is TDeckDescriptor'); block=_replace_one(block, f"DeckIdentifier = '{base}'", f"DeckIdentifier = '{row['id']}'"); block=block.replace('~/' + old, '~/' + new)
            if before != row['expected_slots'] or changed != row['expected_changed_slots'] or block.count('~/' + old): raise ValueError('Deck source revision changed')
            composition[row['id']]={'before_slots':before,'after_slots':block.count('~/Descriptor_StrategicPack_'),'changed_slots':changed,'old_pack_remaining':block.count('~/' + old),'new_pack_added':block.count('~/' + new)}
        blocks.append(block)
    destination=_write(destination, template.rstrip()+'\n\n'+'\n\n'.join(blocks)+'\n')
    return {'template_sha256':sha256(Path(template_path).read_bytes()),'packs_sha256':sha256(Path(packs_path).read_bytes()),'output_sha256':sha256(destination.read_bytes()),'added_exports':[r['deck_export'] for r in (CUSTOM_BATTALIONS if battalions is None else battalions)],'composition':composition}


def prepare_current_combat_groups(template_path, destination, battalions=None, packs_path=None):
    template=_read(template_path); blocks=[]
    for row in (CUSTOM_BATTALIONS if battalions is None else battalions):
        if row['mode']=='authored': blocks.extend(_authored_deck(row, _read(packs_path or Path(template_path).parent/'StrategicPacks.ndf'))[1])
    return _write(destination, template.rstrip()+'\n\n'+'\n\n'.join(blocks)+'\n')


def prepare_current_battle_order(template_path, destination, battalions=None):
    template=_read(template_path); extra=[]
    organizations = {}
    for row in (CUSTOM_BATTALIONS if battalions is None else battalions):
        if row['mode']=='authored':
            for org in ([row['command']] if 'command' in row else []) + [row['organization']]:
                previous = organizations.setdefault(org['export'], org)
                if previous != org:
                    raise ValueError('Conflicting authored command organization')
    for org in organizations.values():
        superior = '~/' + org['superior'] if org['superior'] else 'nil'
        extra.append('\n'.join([f'export {org["export"]} is TBattleOrderSubordination', '(',
            f'    BackgroundTexture = ~/{org["texture"]}', f'    NameToken = "{org["name_token"]}"',
            f'    Superior = {superior}', ')']))
    return _write(destination, template.rstrip()+'\n\n'+'\n\n'.join(extra)+'\n')


def prepare_current_battle_order_resources(template_path, destination, battalions=None):
    text=_read(template_path); needle='    ]\n)'; extra=[]
    for row in (CUSTOM_BATTALIONS if battalions is None else battalions):
        if row['mode']=='authored': extra.append(f"        ('{row['id']}', $/UI/BattleOrder/{row['organization']['export']}),")
    if text.count(needle)!=1: raise ValueError('Unexpected battle order resource form')
    return _write(destination, text.replace(needle, '\n'.join(extra)+'\n'+needle))


def _csv(rows):
    output=io.StringIO(newline=''); writer=csv.writer(output, delimiter=';', quotechar='"', lineterminator='\n'); writer.writerow(('TOKEN','REFTEXT')); writer.writerows(rows); return output.getvalue()


def prepare_localisation_csvs(destination, compiled_campaign=None, battalions=None):
    destination=Path(destination); units=[]; companies=[]; platoons=[]
    for row in (CUSTOM_BATTALIONS if battalions is None else battalions):
        if row['mode']=='authored':
            units.append((row['name_token'],row['name'])); units.append((row['organization']['name_token'],row['organization']['name']))
            if 'command' in row:
                units.append((row['command']['name_token'], row['command']['name']))
            for company in row['companies']:
                companies.append((company['name_token'],company['name']))
                platoons.extend((p['name_token'],p['name']) for p in company['platoons'])
    if compiled_campaign is not None:
        units.extend((row['token'], f"__AGF_LABEL_{row['id'].upper()}__")
                     for row in compiled_campaign['map']['labels'])
    unique_units = {}
    for token, text in units:
        if token in unique_units and unique_units[token] != text:
            raise ValueError('Conflicting unit/command localization token')
        unique_units[token] = text
    return {name:_write(destination/name, _csv(rows)) for name,rows in [('UNITS.csv',unique_units.items()),('COMPANIES.csv',companies),('PLATOONS.csv',platoons)]}


def prepare_modgen_project(template_root, project_root, campaign_source=None, profile=None):
    template_root,project_root=Path(template_root).resolve(),Path(project_root).resolve()
    compiled_campaign = None
    if campaign_source is not None or profile is not None:
        if campaign_source is None or profile is None:
            raise ValueError('Both campaign source and map profile are required')
        from .authoring import compile_campaign
        compiled_campaign, _ = compile_campaign(campaign_source, profile)
        _ensure_authored_scenario_localisation(project_root)
    # A campaign-aware project is authored from its public definition.  Do
    # not silently merge the RedLine prototype catalogue into it: that makes
    # the generated decks, ghosts and localisation depend on unrelated legacy
    # battalions.  The no-argument path remains the compatibility builder.
    battalions = [] if compiled_campaign is not None else list(CUSTOM_BATTALIONS)
    airfields = []
    custom_packs = []
    if compiled_campaign is not None:
        battalions.extend(row['oob'] for row in compiled_campaign['battalions'] if 'oob' in row)
        airfields = compiled_campaign.get('aviation', {}).get('airfields', [])
        custom_packs = compiled_campaign.get('custom_packs', [])
    rels={'units':Path('GameData/Generated/Gameplay/Unit/Strategic/Units.ndf'),'decks':Path('GameData/Generated/Gameplay/Decks/StrategicDecks.ndf'),'packs':Path('GameData/Generated/Gameplay/Decks/StrategicPacks.ndf'),'groups':Path('GameData/Generated/Gameplay/Decks/StrategicCombatGroups.ndf'),'divisions':Path('GameData/Generated/Gameplay/Decks/Divisions.ndf'),'order':Path('GameData/Generated/UserInterface/BattleOrder.ndf'),'resources':Path('GameData/Generated/UserInterface/Strategic/StrategicBattleOrderResources.ndf')}
    rels['ghosts'] = Path('GameData/Generated/Gameplay/Gfx/Depictions/Pawns.ndf')
    localisation = _source_localisation_dir(project_root)
    targets=[rels['units'],rels['decks'],rels['groups'],rels['divisions'],rels['order'],rels['resources'],
             localisation/'UNITS.csv', localisation/'COMPANIES.csv', localisation/'PLATOONS.csv', rels['ghosts']]
    if custom_packs:
        targets.append(rels['packs'])
    if any(not (template_root/x).is_file() for x in rels.values()) or any(not (project_root/x).is_file() for x in targets): raise ValueError('ModGen template or project source inventory is incomplete')
    before={str(x).replace('\\','/'):sha256((project_root/x).read_bytes()) for x in targets}
    with tempfile.TemporaryDirectory(dir=project_root) as td:
        tmp=Path(td)
        packs_source = template_root/rels['packs']
        reports = {}
        if custom_packs:
            reports['packs'] = prepare_custom_strategic_packs(packs_source,
                                                               tmp/'StrategicPacks.ndf', custom_packs)
            packs_source = tmp/'StrategicPacks.ndf'
        reports.update({'units':prepare_current_units(template_root/rels['units'],tmp/'Units.ndf', battalions=battalions, airfields=airfields),'decks':prepare_current_decks(template_root/rels['decks'],packs_source,tmp/'StrategicDecks.ndf', battalions=battalions),'divisions':prepare_current_divisions(template_root/rels['divisions'],tmp/'Divisions.ndf', battalions=battalions)})
        prepare_current_combat_groups(template_root/rels['groups'],tmp/'StrategicCombatGroups.ndf', battalions=battalions, packs_path=packs_source); prepare_current_battle_order(template_root/rels['order'],tmp/'BattleOrder.ndf', battalions=battalions); prepare_current_battle_order_resources(template_root/rels['resources'],tmp/'StrategicBattleOrderResources.ndf', battalions=battalions); prepare_localisation_csvs(tmp/'loc', compiled_campaign, battalions=battalions)
        generated=[tmp/'Units.ndf',tmp/'StrategicDecks.ndf',tmp/'StrategicCombatGroups.ndf',tmp/'Divisions.ndf',tmp/'BattleOrder.ndf',tmp/'StrategicBattleOrderResources.ndf',tmp/'loc/UNITS.csv',tmp/'loc/COMPANIES.csv',tmp/'loc/PLATOONS.csv']
        reports['ghosts'] = prepare_current_ghosts(template_root/rels['ghosts'], tmp/'Pawns.ndf', battalions=battalions)
        generated.append(tmp/'Pawns.ndf')
        if custom_packs:
            generated.append(tmp/'StrategicPacks.ndf')
        for source,relative in zip(generated,targets): os.replace(source,project_root/relative)
    after={str(x).replace('\\','/'):sha256((project_root/x).read_bytes()) for x in targets}
    from .division_emblems import stage_emblems
    emblems = stage_emblems(campaign_source, project_root) if campaign_source is not None else {'count': 0, 'tokens': []}
    from .cinematic_layout import stage_cinematic_layout
    cinematic_layout = stage_cinematic_layout(campaign_source, project_root) if campaign_source is not None else None
    from .campaign_menu import stage_menu
    menu = stage_menu(campaign_source, project_root)
    return {'project':str(project_root),'before':before,'after':after,
            'campaign_labels':len(compiled_campaign['map']['labels']) if compiled_campaign else 0,
            'emblems': emblems,
            'cinematic_layout':cinematic_layout,
            'menu':menu,
            **reports}


def _ensure_authored_scenario_localisation(project_root):
    """Register the three authored scenario bootstrap dictionaries in a fresh ModGen project."""
    project_root = Path(project_root).resolve()
    scenario = 'CampagneStrat_RedLine1989'
    folder = project_root / 'GameData/Localisation' / scenario
    sources = {
        'TROPHIES.csv': ('RL_TROPHY', 'Red Line registration'),
        'Scripting/Dialog.csv': ('RL_DIALOG', 'Red Line registration'),
        'Scripting/Localization.csv': ('RL_LOCAL', 'Red Line registration'),
    }
    registry = project_root / 'GameData/Localisation' / project_root.name / 'LocalisationDicos.ndf'
    if not registry.is_file() and not project_root.name.startswith('WarnoAGF'):
        registry = project_root / _source_localisation_dir(project_root) / 'LocalisationDicos.ndf'
    if not registry.is_file():
        if project_root.name.startswith('WarnoAGF'):
            raise ValueError('Official ModGen localisation declaration is missing')
        return
    text = registry.read_text(encoding='utf-8-sig')
    changed = False
    for relative, (token, value) in sources.items():
        path = folder / relative
        raw = ('"TOKEN";"REFTEXT"\n"' + token + '";"' + value + '"\n').encode('utf-8')
        if path.is_file():
            if path.read_bytes() != raw:
                raise ValueError('Authored scenario localisation source changed: ' + relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        logical = 'GameData:/Localisation/' + scenario + '/' + relative
        if logical not in text:
            changed = True
            text += ('\nunnamed TLocalisationDicoResource\n(\n'
                     '    DicoToken = ~/LocalisationConstantes/dico_maps\n'
                     "    FileName = '" + logical + "'\n"
                     '    CanBeMissing = false\n)\n')
        elif text.count(logical) != 1:
            raise ValueError('Authored scenario localisation registration is ambiguous: ' + relative)
    if changed:
        registry.write_text(text, encoding='utf-8')


def _source_localisation_dir(project_root):
    root = Path(project_root).resolve()
    parent = root / 'GameData/Localisation'
    needed = ('UNITS.csv', 'COMPANIES.csv', 'PLATOONS.csv')
    matches = [folder for folder in parent.iterdir() if folder.is_dir()
               and all((folder / name).is_file() for name in needed)] if parent.is_dir() else []
    preferred = parent / root.name
    if preferred in matches:
        return Path('GameData/Localisation') / root.name
    if len(matches) != 1:
        raise ValueError('ModGen project has no unique campaign localisation source directory')
    return Path('GameData/Localisation') / matches[0].name
