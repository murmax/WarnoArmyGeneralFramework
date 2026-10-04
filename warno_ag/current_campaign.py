"""Build the Red Line MVP solely from current WARNO campaign formats."""
import copy
import functools
import hashlib
import json
from pathlib import Path
import shutil
import struct

from .archives import read_directory, repack, clone_v3, pack_v3
from .cndf import decode, rebuild_objects, append_graph_objects, rebuild_sections, encode_strings
from .identity import patch_identity
from .items import patch_items, spawn_inventory
from .storage import sha256
from .transforms import patch_native
from .modconfig import scenario_config, validate_scenario_config
from .modgen import CUSTOM_BATTALIONS, load_battalion_config
from .modgen_registry import authored_build_name, authored_registry_path
from .full_campaign import (SCENARIO, DISPLAY_NAME, _final_modgen_config,
                            _publish_generated_localisation, _trad, TITLE_HASH,
                            SUBTITLE_HASH, BRIEF_HASH, OBJECTIVES_HASH,
                            _gamedata_contract, _trad_data, _pack_trad)


OLD = 'CampagneStrat_Bruderkrieg'
DEFINITION_SHA = '5e872980e8a817346f8e66729624e6f80a6186b189b77b296515f937407c7999'
DETAILS_SHA = '8deb7b08fcc9a58b35b2bff0f7ba52afaec1ee6dc64da13dee67837a4b218944'
GUID = '0a1f0e3c2ac272ea19b1fff29408e223'
SCENARIO_LOCALISATION = f'ScenariosData:/Localisation/{SCENARIO}'
DETAILS_LAYERS = (
    ('189668/193438/Scenarios/CampagneStrat_Bruderkrieg_Details.dat',
     'b347b9a1ab234ed93f99eb4e6e816315a0ab6ec7900f2fe8ca30f84ae1831cb8'),
    ('193438/197351/Scenarios/CampagneStrat_Bruderkrieg_Details.dat',
     'a01e404c1ec7b8f64f912bf23895685317576ea907f3917cf5bc131a475d3ef2'),
    ('197351/201602/Scenarios/CampagneStrat_Bruderkrieg_Details.dat', DETAILS_SHA),
)
DETAILS_RESOURCES = {
    'CamPaths_LevelDesign.ndfbin', 'Items.sav', 'out/CommandZone.ndfbin',
    'out/DeploymentZone.ndfbin', 'out/IAStratZone.ndfbin',
    'out/LevelDesign.ndfbin', 'out/MapStrategies.ndfbin',
    'out/PlayableZone.ndfbin'}
GAME_DATA = Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC')
VANILLA_MAPS = {
    'DEV': ('183326/184174/ZZ_1.dat', 'dc14726c943184dd4594190d69a3d0a52d15ebaa769d6a4b55de90f0948e04fa'),
    'FR':  ('183326/184174/ZZ_1.dat', '3a8bba6aaeb8b86126a9829b4660dfc6cbb10e1aa058ef8201fd312858ae3e26'),
    'GER': ('184174/188908/ZZ_1.dat', '44c9bb63f63c42c08470a3fab31e9d86242013d22f26c7355e3caa8dbf80f432'),
    'POL': ('183326/184174/ZZ_1.dat', '2e494dc6ceddefc4c135b6a4e6aeee10a45290d0fa53ede4368df221f489cb2a'),
    'RU':  ('184174/188908/ZZ_1.dat', 'e8405288860db22651a4120992b8908bdb87a496fa7c9b6e27356ef52820a8ff'),
    'SC':  ('184174/188908/ZZ_1.dat', 'a807aa6b751f7b52d705a8febd355376bfe690cc3b943061e12f3088ee1bb2ea'),
    'SPA': ('183326/184174/ZZ_1.dat', 'fce8f6aa2629d5da02a080b317dc0e23f2d765eec744ef2d355573e1bdfc9ade'),
    'US':  ('183326/184174/ZZ_1.dat', 'd38a9e2cbc38bf69d892eb79ee144594ad0ef7b312154e4b008ce9d21fed4c7c'),
}
GLYPH_HASH = bytes.fromhex('0000000000000080')
# These are the hashes the legacy, in-game-working prototype had to publish in
# Core/MAPS before the ScenarioLoader could mount its scenario dictionaries.
# Keeping the fingerprint makes that early-load boundary an explicit contract.
EARLY_MAPS_COUNT = 38
EARLY_MAPS_SHA = '1e7d0bf384b3ebf2e28c88c011a1ffb5c4493daac0eca61dd6df376a18e0e09d'
EARLY_ISOLATED_SHA = '592258d7c48c1502986b01b0f4214e17e84811d87e7c756984a444b4552333c4'
OLD_REINFORCEMENTS = (
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_5PzD_131MxPzG',
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_5PzD_132PzG',
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_5PzD_133PzG',
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_5PzD_134Pz',
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_5PzD_135Art',
    '$/GFX/Pawn/Descriptor_Unit_pion_RFA_3K_FlaK340',
)
# This production descriptor is explicitly Camp_1/NATO.  Substituting PACT
# Pawns here was the cause of a red MVD battalion becoming player-controllable
# as NATO.  Its reserve roster must remain exclusively NATO.
NEW_REINFORCEMENTS = OLD_REINFORCEMENTS

# These are intentionally private localisation keys.  They are injected into
# every runtime language dictionary alongside the campaign's isolated keys.
EVENT_TEXT = {
    'nato_title': (b'RDLNNE01', 'РЕЗЕРВ НАТО', 'NATO RESERVE'),
    'nato_body': (b'RDLNNE02', 'Выберите ударную группу у переднего края.', 'Choose a strike group at the forward edge.'),
    'nato_iron': (b'RDLNNE03', 'ГРУППА «АЙРОН» — ТАНКИ И ПВО', 'TASK FORCE IRON — ARMOUR AND AA'),
    'nato_jaguar': (b'RDLNNE04', 'ГРУППА «ЯГУАР» — МАНЁВР И АВИАЦИЯ', 'TASK FORCE JAGUAR — MANOEUVRE AND AIR'),
    'pact_title': (b'RDLNPE01', 'РЕЗЕРВ ОВД', 'PACT RESERVE'),
    'pact_body': (b'RDLNPE02', 'Выберите группу прорыва у переднего края.', 'Choose a breakthrough group at the forward edge.'),
    'pact_guard': (b'RDLNPE03', 'ГВАРДЕЙСКИЙ АВАНГАРД — Т-80', 'GUARDS SPEARHEAD — T-80'),
    'pact_elbe': (b'RDLNPE04', 'ГРУППА «ЭЛЬБА» — Т-72Б И ПВО', 'ELBE GROUP — T-72B AND AA'),
}


def _payloads(raw):
    header, entries, _ = read_directory(raw)
    return header, entries, {entry.path: raw[header.file_offset+entry.offset:
                                             header.file_offset+entry.offset+entry.size]
                             for entry in entries}


def _identity(raw, strings=(), translations=(), properties=()):
    return patch_identity(raw, {'source_sha256': sha256(raw),
        'strings': [{'table':'strings', 'expected':old, 'value':new} for old,new in strings]
                 + [{'table':'translations', 'expected':old, 'value':new}
                    for old,new in translations],
        'properties': list(properties)})[0]


def _property(obj, name):
    found = [p['value'] for p in obj['properties'] if p['property_name'] == name]
    if len(found) != 1:
        raise ValueError(f'Missing or ambiguous {obj["class"]}.{name}')
    return found[0]


def _custom_battalion_contract(root):
    """Validate the compiled Pawn -> private Deck -> changed pack chain."""
    root = Path(root).resolve()
    pawn_path = root/'Gen/NDF/GFX/Pawn.ndfbin'
    deck_path = root/'Gen/NDF/GFX/Deck.ndfbin'
    division_path = root/'Gen/NDF/GFX/Division.ndfbin'
    if not pawn_path.is_file() or not deck_path.is_file() or not division_path.is_file():
        raise ValueError('Compiled custom Pawn, Deck, or Division registry is missing')
    _, pawns = decode(pawn_path.read_bytes(), str(pawn_path))
    _, decks = decode(deck_path.read_bytes(), str(deck_path))
    _, divisions = decode(division_path.read_bytes(), str(division_path))
    dictionaries={}
    for category in ('UNITS','COMPANIES','PLATOONS'):
        path=root/'Gen/Localisation/Localisation'/authored_build_name(root)/f'{category}-RU.dic'
        if not path.is_file(): raise ValueError(f'Compiled authored localisation is missing: {category}')
        dictionaries[category]=_trad_data(path.read_bytes())

    order_path=root/'Gen/NDF/UI/BattleOrder.ndfbin'
    components_path=root/'Gen/NDF/UI/Components.ndfbin'
    if not order_path.is_file() or not components_path.is_file():
        raise ValueError('Compiled battle-order registries are missing')
    _, order_graph=decode(order_path.read_bytes(),str(order_path))
    _, components_graph=decode(components_path.read_bytes(),str(components_path))

    def localised(value, category):
        if value.get('type')!='loc_hash': raise ValueError(f'Expected compiled localisation hash: {category}')
        return dictionaries[category].get(bytes.fromhex(value['value_hex']))

    def exported(graph, path):
        ids = [index for index, value in graph['exports'].items() if value == path]
        if len(ids) != 1:
            raise ValueError(f'Missing or ambiguous compiled export: {path}')
        return ids[0], graph['objects'][ids[0]]

    slot_counts, changed_counts, guids = [], [], []
    authored_shapes = {}
    for row in CUSTOM_BATTALIONS:
        _, pawn = exported(pawns, f'$/GFX/Pawn/{row["unit_export"]}')
        modules = _property(pawn, 'ModulesDescriptors')
        deck_modules = [pawns['objects'][item['object_id']] for item in modules['items']
                        if item.get('type') == 'obj_ref'
                        and pawns['objects'][item['object_id']]['class'] == 'TDeckModuleDescriptor']
        if len(deck_modules) != 1 or _property(deck_modules[0], 'DeckIdentifier')['value'] != row['deck_id']:
            raise ValueError(f'Custom Pawn is not linked to its private deck: {row["unit_export"]}')
        guid = _property(pawn, 'DescriptorId')['value_hex']
        if len(guid) != 32:
            raise ValueError(f'Invalid compiled custom Pawn GUID: {row["unit_export"]}')
        guids.append(guid)

        if row['mode'] == 'authored':
            def one_module(name):
                found=[pawns['objects'][item['object_id']] for item in modules['items']
                       if item.get('type')=='obj_ref' and pawns['objects'][item['object_id']]['class']==name]
                if len(found)!=1: raise ValueError(f'Authored Pawn module mismatch: {row["id"]}/{name}')
                return found[0]
            kind=one_module('TTypeUnitModuleDescriptor'); ap=one_module('TActionPointsModuleDescriptor')
            ui=one_module('TPawnUIModuleDescriptor'); fatigue=one_module('TStrategicFatigueModuleDescriptor')
            state=row['state']
            fatigue_value=next((p['value']['value'] for p in fatigue['properties'] if p['property_name']=='InitialFatigue'),0)
            if (_property(kind,'MotherCountry')['value']!=row['country']
                    or localised(_property(ui,'NameToken'),'UNITS')!=row['name']
                    or _property(ap,'InitialActionPoint')['value']!=state['action_points']['initial']
                    or _property(ap,'ActionPointRecoveryPerTurn')['value']!=state['action_points']['recovery']
                    or fatigue_value!=state['fatigue']):
                raise ValueError(f'Compiled authored Pawn state mismatch: {row["id"]}')

        _, deck = exported(decks, f'$/GFX/Deck/{row["deck_export"]}')
        if _property(deck, 'DeckIdentifier')['value'] != row['deck_id']:
            raise ValueError(f'Custom deck identifier mismatch: {row["deck_export"]}')
        pack_list = _property(deck, 'DeckPackList')
        if row['mode'] == 'authored':
            _, division = exported(divisions, f'$/GFX/Division/{row["division"]}')
            if any(prop['property_name'] in {'DivisionRule','StandoutUnits'}
                   for prop in division['properties']):
                raise ValueError(f'Authored division inherited a stock deck rule: {row["division"]}')
            division_ref=_property(deck,'DeckDivision')
            if (division_ref.get('type')!='trans_ref' or
                    division_ref.get('value') != f'$/GFX/Division/{row["division"]}'):
                raise ValueError(f'Authored deck does not reference its private division: {row["deck_id"]}')
            object_ids = [item.get('object_id') for item in pack_list['items']]
            expected_slots = sum(item['count'] for company in row['companies']
                                 for platoon in company['platoons']
                                 for item in platoon['packs'])
            group_refs = _property(deck, 'DeckCombatGroupList')['items']
            if len(object_ids) != expected_slots or len(group_refs) != len(row['companies']):
                raise ValueError(f'Compiled authored deck composition mismatch: {row["deck_id"]}')
            cursor=0; company_report=[]
            for company,group_ref in zip(row['companies'],group_refs):
                group=decks['objects'][group_ref['object_id']]
                if group['class']!='TDeckCombatGroupDescriptor' or localised(_property(group,'Name'),'COMPANIES')!=company['name']:
                    raise ValueError(f'Compiled authored company mismatch: {row["id"]}/{company["id"]}')
                smart_refs=_property(group,'SmartGroupList')['items']
                if len(smart_refs)!=len(company['platoons']): raise ValueError('Compiled authored platoon count mismatch')
                platoon_report=[]
                for platoon,smart_ref in zip(company['platoons'],smart_refs):
                    smart=decks['objects'][smart_ref['object_id']]
                    pairs=_property(smart,'PackIndexUnitNumberList')['items']
                    expected_pairs=[]
                    for item in platoon['packs']:
                        expected_pairs.append([cursor,item['count']]); cursor+=item['count']
                    actual_pairs=[[item['key']['value'],item['value']['value']] for item in pairs]
                    if (smart['class']!='TDeckSmartGroupDescriptor'
                            or localised(_property(smart,'Name'),'PLATOONS')!=platoon['name']
                            or actual_pairs!=expected_pairs):
                        raise ValueError(f'Compiled authored platoon mismatch: {row["id"]}/{platoon["id"]}')
                    platoon_report.append({'token':platoon['name_token'],'packs':actual_pairs})
                company_report.append({'token':company['name_token'],'platoons':platoon_report})
            if cursor!=len(object_ids): raise ValueError('Compiled authored deck index coverage mismatch')
            authored_shapes[row['id']]={'name_token':row['name_token'],'fatigue':state['fatigue'],
                'initial_action_points':state['action_points']['initial'],'recovery_action_points':state['action_points']['recovery'],
                'companies':company_report,'slots':len(object_ids)}
            slot_counts.append(len(object_ids)); changed_counts.append(0)
            continue
        _, base_deck = exported(decks, f'$/GFX/Deck/{row["base_deck"]}')
        base_pack_list = _property(base_deck, 'DeckPackList')
        object_ids = [item.get('object_id') for item in pack_list['items']]
        base_ids = [item.get('object_id') for item in base_pack_list['items']]
        differences = [(old, new) for old, new in zip(base_ids, object_ids) if old != new]
        changed = len(differences)
        if (len(object_ids) != row['expected_slots']
                or len(base_ids) != len(object_ids)
                or changed != row['expected_changed_slots']
                or len({old for old, _ in differences}) != 1
                or len({new for _, new in differences}) != 1
                or differences[0][0] == differences[0][1]):
            raise ValueError(f'Compiled custom deck composition mismatch: {row["deck_id"]}')
        slot_counts.append(len(object_ids)); changed_counts.append(changed)
    if len(set(guids)) != len(CUSTOM_BATTALIONS):
        raise ValueError('Compiled custom Pawn GUIDs are not unique')
    resources=[obj for obj in components_graph['objects'] if obj['class']=='TStrategicBattleOrderResources']
    if len(resources)!=1: raise ValueError('Compiled battle-order mapping is ambiguous')
    superior_map={item['key']['value']:item['value']['value']
                  for item in _property(resources[0],'DeckSuperiors')['items']}
    for row in CUSTOM_BATTALIONS:
        if row['mode']!='authored': continue
        org=row['organization']; path=f'$/UI/BattleOrder/{org["export"]}'
        found=[order_graph['objects'][index] for index,value in order_graph['exports'].items() if value==path]
        if len(found)!=1 or localised(_property(found[0],'NameToken'),'UNITS')!=org['name']:
            raise ValueError(f'Compiled authored organization mismatch: {row["id"]}')
        superior=_property(found[0],'Superior')['object_id']
        reverse={index:value for index,value in order_graph['exports'].items()}
        if reverse.get(superior)!=f'$/UI/BattleOrder/{org["superior"]}' or superior_map.get(row['id'])!=path:
            raise ValueError(f'Compiled authored affiliation mismatch: {row["id"]}')
    return {'custom_pawn_count': len(CUSTOM_BATTALIONS),
            'custom_deck_count': len(CUSTOM_BATTALIONS),
            'custom_division_count': len([row for row in CUSTOM_BATTALIONS if row['mode']=='authored']),
            'deck_slot_counts': slot_counts,
            'changed_pack_counts': changed_counts,
            'authored_shapes': authored_shapes,
            'pawn_guids': guids}


def _patch_reinforcements(raw):
    """Replace Pawns using existing imports; no path-table rewrite is needed."""
    doc,graph=decode(raw)
    expected=copy.deepcopy(graph)
    production=[obj for obj in expected['objects']
                if obj['class']=='TGDDescriptorStrategicAddPossibleProduction']
    if len(production)!=1:
        raise ValueError('Missing or ambiguous reinforcement action')
    pawns=_property(production[0],'Pawns')
    if pawns.get('type')!='list' or [item.get('value') for item in pawns['items']]!=list(OLD_REINFORCEMENTS):
        raise ValueError('Vanilla reinforcement list precondition mismatch')
    import_by_path={path:index for index,path in expected['imports'].items()}
    if len(import_by_path)!=len(expected['imports']):
        raise ValueError('Ambiguous GDScript import paths')
    missing=[path for path in NEW_REINFORCEMENTS if path not in import_by_path]
    if missing:
        raise ValueError(f'Reinforcement import is unavailable: {missing[0]}')
    template=copy.deepcopy(pawns['items'][0])
    pawns['items']=[]
    for path in NEW_REINFORCEMENTS:
        item=copy.deepcopy(template)
        item['index']=import_by_path[path]
        item['value']=path
        pawns['items'].append(item)
    pawns['length']=len(pawns['items'])
    result=rebuild_objects(doc,expected)
    _,after=decode(result)
    after_production=[obj for obj in after['objects']
                      if obj['class']=='TGDDescriptorStrategicAddPossibleProduction']
    if len(after_production)!=1 or [item['value'] for item in _property(after_production[0],'Pawns')['items']]!=list(NEW_REINFORCEMENTS):
        raise ValueError('Reinforcement rewrite did not survive CNDF round trip')
    return result


def _authored_spawn_guids():
    """Map authored battalion spawn names to their immutable level-design GUID."""
    path = GAME_DATA/'197351/201602/Scenarios/CampagneStrat_Bruderkrieg_Details.dat'
    _, _, payloads = _payloads(path.read_bytes())
    _, graph = decode(payloads['out/LevelDesign.ndfbin'], str(path))
    result = {}
    for obj in graph['objects']:
        if obj['class'] == 'TGameDesignAddOn_Spawn':
            result[_property(obj, 'Name')['value']] = _property(obj, 'GUID')['value_hex']
    return result


def _native_map_groups(objects):
    """Return the native strategic unit-groups by actual map camp.

    A campaign Pawn's allegiance comes from the LevelDesign spawn's Ranking,
    not its descriptor's country field.  This covers all map forces — default
    and replaced — and prevents controlling only the handful named in config.
    """
    path=GAME_DATA/'197351/201602/Scenarios/CampagneStrat_Bruderkrieg_Details.dat'
    _,_,payloads=_payloads(path.read_bytes()); _,level=decode(payloads['out/LevelDesign.ndfbin'],str(path))
    camp_by_guid={_property(obj,'GUID')['value_hex']:_property(obj,'Ranking')['value']
                  for obj in level['objects'] if obj['class']=='TGameDesignAddOn_Spawn'}
    tag_camp={}
    for tag in objects:
        if tag['class']!='TGDTagUnitGroup': continue
        guid=struct.pack('>4i',*[_property(tag,f'GUID{i}')['value'] for i in range(1,5)]).hex()
        if guid in camp_by_guid: tag_camp[tag['id']]=camp_by_guid[guid]
    groups={}
    for collector in objects:
        if collector['class']!='TGDDescriptorAddUnitGroupListToUnitGroup': continue
        camps={tag_camp[item['object_id']] for item in _property(collector,'ListGroupSource')['items']
               if item.get('object_id') in tag_camp}
        if len(camps)>1: raise ValueError('Native group mixes map camps')
        if camps:
            groups.setdefault(camps.pop(),set()).add(_property(collector,'GroupDestination')['object_id'])
    return groups


def _int32_words(guid_hex):
    raw = bytes.fromhex(guid_hex)
    if len(raw) != 16: raise ValueError('Invalid strategic spawn GUID')
    return list(struct.unpack('>4i', raw))


def _start_casualty_actions(raw):
    """Append engine-native pre-campaign casualty actions for authored pawns.

    The graph is append-only.  Each action uses a direct ``TGDTagUnitGroup``
    for the exact LevelDesign spawn GUID, then runs the stock
    ``TGDDescriptorAddCasualtiesToPawn`` action.  This is the shape used by
    BAOR/NORTHTAG itself.  In particular, AddCasualties does *not* consume an
    intermediate TGDVariableUnitGroup populated by
    AddUnitGroupListToUnitGroup; that non-native indirection was accepted by
    the parser but silently ignored by the runtime.
    """
    # Event reinforcements are compiled Pawn/Deck definitions but do not exist
    # at launch, so start-state actions must only target map-deployed pawns.
    authored = [row for row in CUSTOM_BATTALIONS
                if row['mode'] == 'authored' and 'map' in row]
    if not authored: return raw, {'casualty_actions': 0}
    doc, graph = decode(raw)
    if 'TGDDescriptorAddCasualtiesToPawn' in graph['classes']:
        raise ValueError('Unexpected existing casualty action class in pinned graph')
    required = ('TGDDescriptorSequential', 'TGDDescriptorSimultaneous', 'TGDTagUnitGroup',
                'TGDDescriptorCreateUnitOnPosition', 'TGDVariableUnitGroup', 'TGDTagPosition')
    class_id = {name: graph['classes'].index(name) for name in required}
    prop_id = {(p['class'], p['name']): p['id'] for p in graph['properties']}
    for key in (('TGDDescriptorSequential','SubActions'), ('TGDDescriptorSequential','NbExecutions'),
                ('TGDTagUnitGroup','GUID1'), ('TGDTagUnitGroup','GUID2'),
                ('TGDTagUnitGroup','GUID3'), ('TGDTagUnitGroup','GUID4')):
        if key not in prop_id: raise ValueError('Pinned GDScript schema lacks ' + '/'.join(key))
    spawn_guids = _authored_spawn_guids(); objects = copy.deepcopy(graph['objects'])
    initial = objects[290]
    if initial['class'] != 'TGDDescriptorSequential': raise ValueError('Pinned initial sequence changed')
    subactions = _property(initial, 'SubActions')
    if subactions['length'] != 11: raise ValueError('Pinned initial sequence shape changed')
    # CNDF stores the descriptor property name, which is TypeCasualties.  The
    # executable's SetCasualtiesType symbol is the C++ setter, not a serialised
    # property name.  These are deliberately treated as different schemas.
    casualty_class = len(graph['classes']); casualty_props = {name:len(graph['properties']) + i for i,name in
        enumerate(('Casualties','Group','RandomRange','TypeCasualties'))}
    def ref(object_id, cid): return {'type_id':3149642683, 'type':'obj_ref', 'reference_prefix':True, 'object_id':object_id, 'class_id':cid}
    def integer(value): return {'type_id':2, 'type':'int32', 'reference_prefix':False, 'value':value}
    def add(obj_class, properties):
        object_id=len(objects); objects.append({'id':object_id,'class':obj_class,'class_id':class_id.get(obj_class,casualty_class),'is_top_object':False,'properties':properties}); return object_id
    frozen_report=[]
    # A frozen formation is not an AP=0 pawn: Bruderkrieg's stock script
    # tags the exact spawn, clears its AP, displays a turn counter, and later
    # restores AP.  Keep that proven flow but set the restore value from config.
    casualty_actions=[]
    for row in authored:
        if not row['state']['frozen_turns']:
            continue
        words=_int32_words(spawn_guids[row['map']['spawn']])
        tags=[obj for obj in objects if obj['class']=='TGDTagUnitGroup' and
              [_property(obj,f'GUID{i}')['value'] for i in range(1,5)]==words]
        if len(tags)!=1: raise ValueError('Frozen spawn does not have one proven GDScript tag')
        tag_id=tags[0]['id']; groups=[]
        for obj in objects:
            if obj['class']!='TGDDescriptorAddUnitGroupListToUnitGroup': continue
            listed=_property(obj,'ListGroupSource')['items']
            if len(listed)==1 and listed[0].get('object_id')==tag_id:
                groups.append(_property(obj,'GroupDestination')['object_id'])
        if len(groups)!=1: raise ValueError('Frozen spawn does not have one proven unit group')
        changes=[obj for obj in objects if obj['class']=='TGDDescriptorChangePawnActionPoint' and
                 any(p['property_name']=='UnitsGroup' and p['value'].get('object_id')==groups[0]
                     for p in obj['properties'])]
        clear=[obj for obj in changes if not any(p['property_name']=='ActionPointNumber' for p in obj['properties'])]
        restore=[obj for obj in changes if any(p['property_name']=='ActionPointNumber' for p in obj['properties'])]
        if len(clear)!=1 or len(restore)!=1 or _property(restore[0],'ActionPointNumber')['value'] != 12.0:
            raise ValueError('Frozen spawn does not match the pinned clear/restore flow')
        _property(restore[0],'ActionPointNumber')['value']=float(row['state']['action_points']['recovery'])
        labels=[obj for obj in objects if obj['class']=='TGDDescriptorDrawLabelOnPosition' and
                any(p['property_name']=='Group' and p['value'].get('object_id')==groups[0]
                    for p in obj['properties'])]
        if len(labels)!=1: raise ValueError('Frozen spawn does not have one proven countdown label')
        variables=_property(labels[0],'ListVariablesForFoldedText')['items']
        if len(variables)!=1: raise ValueError('Frozen spawn countdown variable is ambiguous')
        counter=objects[variables[0]['object_id']]
        if counter['class']!='TGDVariableInteger' or _property(counter,'Value')['value']!=3:
            raise ValueError('Frozen spawn countdown schema changed')
        _property(counter,'Value')['value']=row['state']['frozen_turns']
        frozen_report.append({'spawn':row['map']['spawn'],'turns':row['state']['frozen_turns'],
                              'restore_action_points':row['state']['action_points']['recovery']})
    for row in authored:
        guid = spawn_guids.get(row['map']['spawn'])
        if guid is None: raise ValueError('Authored spawn GUID is unavailable: ' + row['map']['spawn'])
        # The engine registers the map's original tag instances at load time.
        # A structurally identical tag appended here parses correctly but is
        # not registered for Pawn lookup, so the casualty action becomes a
        # silent no-op.  Reuse the one immutable tag already wired to the
        # LevelDesign spawn, exactly as native campaigns do.
        words=_int32_words(guid)
        tags=[obj for obj in objects if obj['class']=='TGDTagUnitGroup' and
              [_property(obj,f'GUID{i}')['value'] for i in range(1,5)]==words]
        if len(tags)!=1:
            raise ValueError('Authored casualty spawn does not have one native group tag')
        tag=tags[0]['id']
        state=row['state']['casualties']
        casualty = add('TGDDescriptorAddCasualtiesToPawn', [
            {'property_id':casualty_props['Casualties'],'property_name':'Casualties','value':integer(state['count'])},
            {'property_id':casualty_props['Group'],'property_name':'Group','value':ref(tag,class_id['TGDTagUnitGroup'])},
            {'property_id':casualty_props['RandomRange'],'property_name':'RandomRange','value':integer(state['random_range'])},
            {'property_id':casualty_props['TypeCasualties'],'property_name':'TypeCasualties','value':integer(state['type'])}])
        casualty_actions.append(casualty)
    # Native campaigns apply all opening losses through one simultaneous
    # startup action.  These map Pawns become resolvable only after the
    # campaign's group-collection step, so serialising individual sequential
    # actions was structurally valid but could run at the wrong lifecycle
    # boundary and silently leave every deck intact.
    if casualty_actions:
        simultaneous_class='TGDDescriptorSimultaneous'
        if simultaneous_class not in graph['classes']:
            raise ValueError('Pinned GDScript lacks native casualty container')
        simultaneous=add(simultaneous_class, [
            {'property_id':prop_id[(simultaneous_class,'SubActions')],'property_name':'SubActions','value':{'type_id':17,'type':'list','reference_prefix':False,'length':len(casualty_actions),'items':[ref(action,casualty_class) for action in casualty_actions]}},
            {'property_id':prop_id[(simultaneous_class,'NbExecutions')],'property_name':'NbExecutions','value':{'type_id':3,'type':'uint32','reference_prefix':False,'value':1}}])
        # The main strategic loop is long-lived.  Insert the native-shaped
        # opening-loss block immediately before it, after all group collectors.
        main_index=next((index for index,item in enumerate(subactions['items'])
                         if item.get('object_id')==301), None)
        if main_index is None:
            raise ValueError('Pinned initial sequence lacks main strategic loop')
        subactions['items'].insert(main_index,ref(simultaneous,class_id[simultaneous_class]))
        subactions['length'] += 1
    base = {'classes':graph['classes'], 'properties':graph['properties'],
            'objects':objects[:len(graph['objects'])]}
    result = append_graph_objects(doc, base, objects[len(graph['objects']):],
                                  ('TGDDescriptorAddCasualtiesToPawn',),
                                  tuple((name,'TGDDescriptorAddCasualtiesToPawn') for name in casualty_props))
    _, after = decode(result)
    actions = [o for o in after['objects'] if o['class']=='TGDDescriptorAddCasualtiesToPawn']
    if len(actions) != len(authored):
        raise ValueError('Casualty action append verification failed')
    return result, {'casualty_actions':len(actions), 'casualties':[r['state']['casualties']['count'] for r in authored],
                    'frozen':frozen_report}


def _choice_events(raw):
    """Replace launch cutscenes with two native, side-gated choice events.

    The four event formations are not LevelDesign spawns.  Their private Pawn
    and Deck descriptors are compiled normally, then the selected branch uses
    the stock ``CreateUnitOnPosition`` descriptor to create exactly one at a
    pinned front-line tag.  Indices 1--4 are safe to repurpose: their vanilla
    create actions are removed and the old production list no longer uses them
    after ``_patch_reinforcements``.
    """
    choices=[row for row in CUSTOM_BATTALIONS if row.get('event_deployment')]
    if len(choices)!=4 or {(r['event_deployment']['event'],r['event_deployment']['choice']) for r in choices}!={('nato',0),('nato',1),('pact',0),('pact',1)}:
        raise ValueError('Expected two fully configured choices for each side')
    doc,graph=decode(raw); objects=copy.deepcopy(graph['objects'])
    prop_id={(p['class'],p['name']):p['id'] for p in graph['properties']}
    required=('TGDDescriptorSequential','TGDDescriptorSimultaneous','TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice',
              'TGDDescriptorCutsceneDialogWithMultipleChoice','TGDDescriptorCutsceneTextComponent',
              'TGDDescriptorCutsceneTextureComponent','TGDVariableInteger','TGDConditionVariable',
              'TGDOperatorIntegerCompare','TGDDescriptorIfThenElse','TGDDescriptorCreateUnitOnPosition',
              'TGDVariableUnitGroup','TGDTagPosition','TGDDescriptorStrategicDefend',
              'TGDConditionCutSceneIsCampControllableByLocalPlayer')
    cid={name:graph['classes'].index(name) for name in required}
    # Bruderkrieg does not itself use an advance mission, even though the
    # current engine supports it and other current campaigns serialize it.
    # Append the exact current schema rather than approximating an attack with
    # a defend order: PACT event formations must actively move on Alsfeld.
    move_class='TGDDescriptorStrategicMoveAndAttack'
    move_properties=('Blocking','Group','AttackEnemyInRadius',
                     'ExecuteOnlyOnIAActivated','Positions',
                     'UseOnlyUnitInMissionToAttack','WaypointReachedRadius')
    new_classes=()
    new_properties=()
    if move_class not in graph['classes']:
        cid[move_class]=len(graph['classes'])
        new_classes=(move_class,)
        new_properties=tuple((name,move_class) for name in move_properties)
        for offset,name in enumerate(move_properties):
            prop_id[(move_class,name)]=len(graph['properties'])+offset
    else:
        cid[move_class]=graph['classes'].index(move_class)
    if any((name,prop) not in prop_id for name,prop in (
        ('TGDDescriptorSequential','SubActions'),('TGDDescriptorSequential','NbExecutions'),
        ('TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice','DialogList'),
        ('TGDDescriptorCutsceneDialogWithMultipleChoice','SelectedButton'),
        ('TGDDescriptorCreateUnitOnPosition','TypeUnit'),('TGDTagPosition','GUID1'),
        ('TGDTagPosition','GUID2'),('TGDTagPosition','GUID3'),('TGDTagPosition','GUID4'))):
        raise ValueError('Pinned event schema is unavailable')
    def ref(oid, name): return {'type_id':3149642683,'type':'obj_ref','reference_prefix':True,'object_id':oid,'class_id':cid[name]}
    def integer(value): return {'type_id':2,'type':'int32','reference_prefix':False,'value':value}
    def boolean(value): return {'type_id':0,'type':'bool','reference_prefix':False,'value':value}
    def string(value):
        index=graph['strings'].index(value)
        return {'type_id':7,'type':'strg_ref','reference_prefix':False,'index':index,'value':value}
    def loc(value): return {'type_id':29,'type':'loc_hash','reference_prefix':False,'value_hex':value.hex()}
    def listref(values): return {'type_id':17,'type':'list','reference_prefix':False,'length':len(values),'items':values}
    def add(name, props):
        oid=len(objects); objects.append({'id':oid,'class':name,'class_id':cid[name],'is_top_object':False,'properties':props}); return oid
    def native_position(guid):
        words=_int32_words(guid)
        found=[obj['id'] for obj in objects if obj['class']=='TGDTagPosition' and
               [_property(obj,f'GUID{i}')['value'] for i in range(1,5)]==words]
        if len(found)!=1:
            raise ValueError('Configured strategic objective does not have one native position tag')
        return found[0]
    def property(name,key,value): return {'property_id':prop_id[(name,key)],'property_name':key,'value':value}
    initial=objects[290]
    actions=_property(initial,'SubActions')
    # 298--300 are Bruderkrieg's three launch cutscenes.  Keep 292--294 (the
    # initial aircraft) and, critically, 295--297: those three native
    # ChangePawnActionPoint actions are what actually clear the AP of the
    # delayed NATO groups.  Removing the whole 292--300 range left only the
    # countdown labels, so formations looked frozen while retaining full AP.
    actions['items']=[item for item in actions['items'] if item.get('object_id') not in {298,299,300}]
    actions['length']=len(actions['items'])

    # Do not merely hide Bruderkrieg's choices: their selected-button
    # branches retain live CreateUnitOnPosition actions and can therefore
    # grant the local player formations from the opposing camp.  The campaign
    # has five old choice sequences and two old scripted-production branches.
    # Remove those reachable roots while preserving the objective, victory and
    # ordinary reinforcement branches that are siblings in the same graph.
    def remove_children(parent_id, removed):
        parent=objects[parent_id]
        children=_property(parent,'SubActions')
        before=[item.get('object_id') for item in children['items']]
        if not set(removed).issubset(before):
            raise ValueError(f'Pinned legacy event root changed: {parent_id}')
        children['items']=[item for item in children['items'] if item.get('object_id') not in set(removed)]
        children['length']=len(children['items'])
    remove_children(388,(418,422))
    remove_children(389,(423,424))
    imports={index:path for index,path in graph['imports'].items()}
    # 1--3 are launch air units and 4--9 are NATO's turn-two production
    # roster.  The five imports 11--15 belong solely to the removed legacy
    # PACT event branches, so four of them can safely host our replacements.
    # Reusing 4/5 was the cause of PACT Pawns appearing as NATO reserves.
    for index,row in zip((11,12,13,14),sorted(choices,key=lambda r:(r['event_deployment']['event'],r['event_deployment']['choice']))):
        imports[index]='$/GFX/Pawn/'+row['unit_export']
    event_data={
        'nato': {'camp':284,'texture':'BH_otan_popup_1','title':'nato_title','body':'nato_body','buttons':('nato_iron','nato_jaguar')},
        'pact': {'camp':283,'texture':'BH_pact_popup_1','title':'pact_title','body':'pact_body','buttons':('pact_guard','pact_elbe')},
    }
    # Map-deployed custom Pawns inherit the vanilla group collectors.  Their
    # original goals are unrelated Bruderkrieg objectives, which made red
    # units wander toward Borken/Schwalmstadt.  Retask those actual groups,
    # not a newly invented group, before the long-lived strategic loop begins.
    alsfeld=native_position(next(row['event_deployment']['objective_guid'] for row in choices
                                 if row['event_deployment']['event']=='nato'))
    native_groups=_native_map_groups(objects)
    blue_groups=native_groups.get('Camp_1',set())
    red_groups=native_groups.get('Camp_0',set())
    if not blue_groups or not red_groups:
        raise ValueError('Configured map forces do not resolve to native strategic groups')
    for obj in objects:
        if obj['class']=='TGDDescriptorStrategicDefend' and _property(obj,'Group')['object_id'] in blue_groups:
            _property(obj,'Position').update(ref(alsfeld,'TGDTagPosition'))
            attack=[prop for prop in obj['properties'] if prop['property_name']=='AttackEnemyInRadius']
            if attack: attack[0]['value']['value']=2120
            else: obj['properties'].append(property('TGDDescriptorStrategicDefend','AttackEnemyInRadius',integer(2120)))
    # The two generic strategic-AI descriptors are the engine-side turn
    # controllers for PACT and NATO.  They must remain reachable: removing them
    # does not merely suppress a stock objective, it leaves the AI side unable
    # to finish its turn and the campaign hangs on the following transition.
    strategic_ai=[obj for obj in objects if obj['class']=='TGDDescriptorIAStrategicScripted']
    if len(strategic_ai)!=2:
        raise ValueError('Pinned generic strategic AI pair changed')
    generic_ai_ids={obj['id'] for obj in strategic_ai}
    generic_parent=[obj for obj in objects if obj['class']=='TGDDescriptorSequential'
                    and generic_ai_ids.issubset({item.get('object_id') for item in _property(obj,'SubActions')['items']})]
    if len(generic_parent)!=1:
        raise ValueError('Pinned generic strategic AI parent changed')
    initial=objects[290]; initial_actions=_property(initial,'SubActions')
    main_refs=[item for item in initial_actions['items'] if item.get('object_id')==301]
    if len(main_refs)!=1 or objects[301]['class']!='TGDDescriptorSimultaneous':
        raise ValueError('Pinned initial sequence lacks strategic loop')
    main_actions=_property(objects[301],'SubActions')
    red_missions=[]
    for group in sorted(red_groups):
        if objects[group]['class']!='TGDVariableUnitGroup':
            raise ValueError('Configured PACT group is not a unit-group variable')
        mission=add(move_class,[
            property(move_class,'Blocking',boolean(True)),
            property(move_class,'Group',ref(group,'TGDVariableUnitGroup')),
            property(move_class,'AttackEnemyInRadius',integer(2120)),
            property(move_class,'ExecuteOnlyOnIAActivated',boolean(True)),
            property(move_class,'Positions',listref([ref(alsfeld,'TGDTagPosition')])),
            property(move_class,'UseOnlyUnitInMissionToAttack',boolean(True)),
            property(move_class,'WaypointReachedRadius',integer(707))])
        red_missions.append(mission)
    # Keep all five PACT formations alive as concurrent mission handles inside
    # the campaign's long-lived simultaneous root.  Placing this blocking
    # mission block in the launch *sequence* before object 301 prevents the
    # main turn loop from starting whenever PACT is controlled by the AI.
    red_block=add('TGDDescriptorSimultaneous',[
        property('TGDDescriptorSimultaneous','SubActions',listref([ref(mission,move_class) for mission in red_missions])),
        property('TGDDescriptorSimultaneous','NbExecutions',{'type_id':3,'type':'uint32','reference_prefix':False,'value':1})])
    main_actions['items'].append(ref(red_block,'TGDDescriptorSimultaneous'))
    main_actions['length']+=1
    for event,data in event_data.items():
        pair=sorted((r for r in choices if r['event_deployment']['event']==event),key=lambda r:r['event_deployment']['choice'])
        variable=add('TGDVariableInteger',[])
        text=[]
        for component,key in zip(('Text1','Text2'),(data['title'],data['body'])):
            text.append(add('TGDDescriptorCutsceneTextComponent',[
                property('TGDDescriptorCutsceneTextComponent','UIComponentName',string(component)),
                property('TGDDescriptorCutsceneTextComponent','LocalizedText',loc(EVENT_TEXT[key][0]))]))
        texture=add('TGDDescriptorCutsceneTextureComponent',[
            property('TGDDescriptorCutsceneTextureComponent','UIComponentName',string('Texture1')),
            property('TGDDescriptorCutsceneTextureComponent','TextureFile',string(data['texture']))])
        dialog=add('TGDDescriptorCutsceneDialogWithMultipleChoice',[
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','AfficherBoutonPause',boolean(True)),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','AfficherDevantFlou',boolean(True)),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','ComponentName',string('ST_Popup_1Texture_5Text')),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','DureePause',{'type_id':5,'type':'float32','reference_prefix':False,'value':-1.0}),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','Pause',boolean(True)),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','TextComponentsToFill',listref([ref(x,'TGDDescriptorCutsceneTextComponent') for x in text])),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','TextureComponentsToFill',listref([ref(texture,'TGDDescriptorCutsceneTextureComponent')])),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','TokenBoutonChoix0',loc(EVENT_TEXT[data['buttons'][0]][0])),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','VisibleByAlliedOfSpecifiedCamp',boolean(True)),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','VisibleByCamp',ref(data['camp'],'TGDConditionCutSceneIsCampControllableByLocalPlayer').copy() | {'class_id':7}),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','SelectedButton',ref(variable,'TGDVariableInteger')),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','TokenBoutonChoix1',loc(EVENT_TEXT[data['buttons'][1]][0])),
            property('TGDDescriptorCutsceneDialogWithMultipleChoice','DefaultButtonChoice',integer(0))])
        wrap=add('TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice',[
            property('TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice','DialogList',listref([ref(dialog,'TGDDescriptorCutsceneDialogWithMultipleChoice')]))])
        creates=[]; missions=[]
        for row in pair:
            pos=native_position(row['event_deployment']['position_guid'])
            objective=native_position(row['event_deployment']['objective_guid'])
            group=add('TGDVariableUnitGroup',[])
            index=next(index for index,path in imports.items() if path=='$/GFX/Pawn/'+row['unit_export'])
            creates.append(add('TGDDescriptorCreateUnitOnPosition',[
                property('TGDDescriptorCreateUnitOnPosition','Camp',{'type_id':3149642683,'type':'obj_ref','reference_prefix':True,'object_id':data['camp'],'class_id':7}),
                property('TGDDescriptorCreateUnitOnPosition','Group',ref(group,'TGDVariableUnitGroup')),
                property('TGDDescriptorCreateUnitOnPosition','NbUnit',integer(1)),
                property('TGDDescriptorCreateUnitOnPosition','Position',ref(pos,'TGDTagPosition')),
                property('TGDDescriptorCreateUnitOnPosition','TypeUnit',{'type_id':2863311530,'type':'trans_ref','reference_prefix':True,'index':index,'value':imports[index]})]))
            # A Pawn created by an event is not automatically assigned to the
            # strategic AI. NATO holds/counterattacks around Alsfeld; PACT
            # receives the native move-and-attack order aimed at Alsfeld.
            if event=='nato':
                mission=add('TGDDescriptorStrategicDefend',[
                    property('TGDDescriptorStrategicDefend','Blocking',boolean(True)),
                    property('TGDDescriptorStrategicDefend','Group',ref(group,'TGDVariableUnitGroup')),
                    property('TGDDescriptorStrategicDefend','AttackEnemyInRadius',integer(2120)),
                    property('TGDDescriptorStrategicDefend','ExecuteOnlyOnIAActivated',boolean(True)),
                    property('TGDDescriptorStrategicDefend','Position',ref(objective,'TGDTagPosition')),
                    property('TGDDescriptorStrategicDefend','UseOnlyUnitInMissionToAttack',boolean(True)),
                    property('TGDDescriptorStrategicDefend','WaypointReachedRadius',integer(707))])
                missions.append((mission,'TGDDescriptorStrategicDefend'))
            else:
                mission=add(move_class,[
                    property(move_class,'Blocking',boolean(True)),
                    property(move_class,'Group',ref(group,'TGDVariableUnitGroup')),
                    property(move_class,'AttackEnemyInRadius',integer(2120)),
                    property(move_class,'ExecuteOnlyOnIAActivated',boolean(True)),
                    property(move_class,'Positions',listref([ref(objective,'TGDTagPosition')])),
                    property(move_class,'UseOnlyUnitInMissionToAttack',boolean(True)),
                    property(move_class,'WaypointReachedRadius',integer(707))])
                missions.append((mission,move_class))
        operator=add('TGDOperatorIntegerCompare',[property('TGDOperatorIntegerCompare','OperatorType',integer(3))])
        condition=add('TGDConditionVariable',[property('TGDConditionVariable','Operator',ref(operator,'TGDOperatorIntegerCompare')),property('TGDConditionVariable','Variable',ref(variable,'TGDVariableInteger'))])
        deployment=[]
        for create,(mission,mission_class) in zip(creates,missions):
            deployment.append(add('TGDDescriptorSequential',[
                property('TGDDescriptorSequential','SubActions',listref([
                    ref(create,'TGDDescriptorCreateUnitOnPosition'),
                    ref(mission,mission_class)])),
                property('TGDDescriptorSequential','NbExecutions',{'type_id':3,'type':'uint32','reference_prefix':False,'value':1})]))
        branch=add('TGDDescriptorIfThenElse',[property('TGDDescriptorIfThenElse','Condition',ref(condition,'TGDConditionVariable')),property('TGDDescriptorIfThenElse','EffetIfTrue',ref(deployment[0],'TGDDescriptorSequential')),property('TGDDescriptorIfThenElse','EffetIfFalse',ref(deployment[1],'TGDDescriptorSequential'))])
        sequence=add('TGDDescriptorSequential',[property('TGDDescriptorSequential','SubActions',listref([ref(wrap,'TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice'),ref(branch,'TGDDescriptorIfThenElse')])),property('TGDDescriptorSequential','NbExecutions',{'type_id':3,'type':'uint32','reference_prefix':False,'value':1})])
        gate=add('TGDConditionCutSceneIsCampControllableByLocalPlayer',[property('TGDConditionCutSceneIsCampControllableByLocalPlayer','Camp',{'type_id':3149642683,'type':'obj_ref','reference_prefix':True,'object_id':data['camp'],'class_id':7})])
        # The opposing AI does not receive a UI dialog.  It deliberately takes
        # choice 0 and receives the same mission-backed formation, rather than
        # silently getting nothing.
        gated=add('TGDDescriptorIfThenElse',[property('TGDDescriptorIfThenElse','Condition',ref(gate,'TGDConditionCutSceneIsCampControllableByLocalPlayer')),property('TGDDescriptorIfThenElse','EffetIfTrue',ref(sequence,'TGDDescriptorSequential')),property('TGDDescriptorIfThenElse','EffetIfFalse',ref(deployment[0],'TGDDescriptorSequential'))])
        # Run modal choice dialogs only after the launch sequence has
        # initialised the main strategic root.  Putting them inside object 301
        # races the intro-skip UI teardown with a new modal layer and crashes
        # WARNO in TModalLayerProperties.
        actions['items'].append(ref(gated,'TGDDescriptorIfThenElse'))
        actions['length']+=1
    base={'classes':graph['classes'],'properties':graph['properties'],'objects':objects[:len(graph['objects'])]}
    appended=append_graph_objects(doc,base,objects[len(graph['objects']):],new_classes,new_properties)
    after_doc,after=decode(appended)
    # TRAN stores path *segments*, while IMPR is a trie over their indices.
    # Rebuild that trie instead of overwriting existing segment strings: the
    # latter corrupts shared export paths even though the CNDF parser accepts
    # the raw string table.
    trans=[]
    for section in after_doc.sections:
        if section.name=='TRAN':
            from .binary_codec import read_len_prefixed_strings
            trans=read_len_prefixed_strings(after_doc.full_data,section)
            break
    if not trans: raise ValueError('Pinned GDScript has no TRAN table')
    segment_index={value:index for index,value in enumerate(trans)}
    def segment(value):
        if value not in segment_index:
            segment_index[value]=len(trans); trans.append(value)
        return segment_index[value]
    class Node:
        def __init__(self, name): self.name=name; self.index=0xFFFFFFFF; self.children={}
    roots={}
    for index,path in imports.items():
        node=None; children=roots
        for part in path.split('/'):
            node=children.setdefault(part,Node(segment(part))); children=node.children
        if node.index!=0xFFFFFFFF: raise ValueError('Duplicate rebuilt import path')
        node.index=index
    ordered=[]
    def visit(node):
        ordered.append(node)
        for child in node.children.values(): visit(child)
    for root in roots.values(): visit(root)
    offsets={}; offset=0
    for node in ordered: offsets[id(node)]=offset; offset+=12+4*len(node.children)
    impr=bytearray(offset)
    for node in ordered:
        children=list(node.children.values()); pos=offsets[id(node)]
        struct.pack_into('<III',impr,pos,node.name,node.index,len(children))
        for number,child in enumerate(children): struct.pack_into('<I',impr,pos+12+4*number,offsets[id(child)]-(pos+12))
    result=rebuild_sections(after_doc,{'TRAN':encode_strings(trans),'IMPR':bytes(impr)})
    _,check=decode(result)
    created=[o for o in check['objects'] if o['class']=='TGDDescriptorCreateUnitOnPosition' and o['id']>=len(graph['objects'])]
    if len(created)!=4 or any(_property(o,'TypeUnit')['value'] not in set(imports.values()) for o in created):
        raise ValueError('Choice event creation contract did not survive')
    return result, {'choice_events':2,'choice_branches':4,'old_launch_cutscenes_removed':3}


def _casualty_contract(definition_raw):
    _, _, payloads = _payloads(definition_raw)
    script = next(value for name,value in payloads.items() if name.endswith(f'GDScript/{SCENARIO}.ndfbin'))
    _, graph = decode(script)
    authored = [row for row in CUSTOM_BATTALIONS
                if row['mode'] == 'authored' and 'map' in row]
    actions = [obj for obj in graph['objects'] if obj['class']=='TGDDescriptorAddCasualtiesToPawn']
    required_properties={'Casualties','Group','RandomRange','TypeCasualties'}
    if any({prop['property_name'] for prop in action['properties']} != required_properties
           for action in actions):
        raise ValueError('Candidate casualty action does not use the native property schema')
    actual = sorted((_property(obj,'Casualties')['value'], _property(obj,'RandomRange')['value'],
                     _property(obj,'TypeCasualties')['value']) for obj in actions)
    expected = sorted((row['state']['casualties']['count'], row['state']['casualties']['random_range'],
                       row['state']['casualties']['type']) for row in authored)
    if actual != expected:
        raise ValueError('Candidate pre-campaign casualty action contract mismatch')
    spawn_guids = _authored_spawn_guids()
    expected_words = {tuple(_int32_words(spawn_guids[row['map']['spawn']])) for row in authored}
    action_words = set()
    for action in actions:
        group = _property(action, 'Group')
        if group.get('class_id') is None or group.get('object_id') is None:
            raise ValueError('Candidate casualty action has no direct tag group')
        tag = graph['objects'][group['object_id']]
        if tag['class'] != 'TGDTagUnitGroup':
            raise ValueError('Candidate casualty action does not use a direct tag group')
        action_words.add(tuple(_property(tag, f'GUID{i}')['value'] for i in range(1, 5)))
    if action_words != expected_words:
        raise ValueError('Candidate casualty action tag does not target every authored pawn exactly once')
    initial=graph['objects'][290]
    if initial['class']!='TGDDescriptorSequential':
        raise ValueError('Candidate initial casualty sequence changed')
    initial_actions={item.get('object_id') for item in _property(initial,'SubActions')['items']}
    parent_sequences=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorSimultaneous'
                      and {item.get('object_id') for item in _property(obj,'SubActions')['items']}
                         == {action['id'] for action in actions}]
    if len(parent_sequences)!=1 or parent_sequences[0]['id'] not in initial_actions:
        raise ValueError('Candidate casualties are not in one native startup block')
    main_index=next((index for index,item in enumerate(_property(initial,'SubActions')['items'])
                     if item.get('object_id')==301),None)
    if main_index is None or next(index for index,item in enumerate(_property(initial,'SubActions')['items'])
                                  if item.get('object_id')==parent_sequences[0]['id']) >= main_index:
        raise ValueError('Candidate casualties run after the main strategic loop')
    frozen=[row for row in authored if row['state']['frozen_turns']]
    expected_restore=[]
    for row in frozen:
        words=_int32_words(spawn_guids[row['map']['spawn']])
        tags=[obj for obj in graph['objects'] if obj['class']=='TGDTagUnitGroup' and
              [_property(obj,f'GUID{i}')['value'] for i in range(1,5)]==words]
        chains=[]
        for tag in tags:
            collectors=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorAddUnitGroupListToUnitGroup'
                        and len(_property(obj,'ListGroupSource')['items'])==1
                        and _property(obj,'ListGroupSource')['items'][0].get('object_id')==tag['id']]
            for collector in collectors:
                group=_property(collector,'GroupDestination')['object_id']
                labels=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorDrawLabelOnPosition' and
                        any(p['property_name']=='Group' and p['value'].get('object_id')==group for p in obj['properties'])]
                changes=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorChangePawnActionPoint' and
                         any(p['property_name']=='UnitsGroup' and p['value'].get('object_id')==group for p in obj['properties'])]
                restore=[obj for obj in changes if any(p['property_name']=='ActionPointNumber' for p in obj['properties'])]
                if len(labels)==1 and len(restore)==1:
                    chains.append((labels[0],restore[0]))
        if len(chains)!=1: raise ValueError('Candidate frozen-pawn chain mismatch')
        label,restore=chains[0]
        variables=_property(label,'ListVariablesForFoldedText')['items']
        counter=graph['objects'][variables[0]['object_id']] if len(variables)==1 else None
        expected_ap=float(row['state']['action_points']['recovery'])
        if (counter is None or _property(counter,'Value')['value']!=row['state']['frozen_turns']
                or _property(restore,'ActionPointNumber')['value']!=expected_ap):
            raise ValueError('Candidate frozen-pawn countdown/AP contract mismatch')
        expected_restore.append(expected_ap)
    return {'casualty_actions':len(actions), 'casualties':[x[0] for x in actual],
            'casualty_types':[x[2] for x in actual],
            'frozen_turns':[row['state']['frozen_turns'] for row in frozen],
            'frozen_restore_action_points':expected_restore}


def _choice_event_contract(definition_raw):
    """Prove old choices/spawns are unreachable and each new spawn has AI work."""
    _,_,payloads=_payloads(definition_raw)
    script=next(value for name,value in payloads.items() if name.endswith(f'GDScript/{SCENARIO}.ndfbin'))
    _,graph=decode(script)
    reachable=set(); pending=[282]
    while pending:
        object_id=pending.pop()
        if object_id in reachable: continue
        reachable.add(object_id)
        for prop in graph['objects'][object_id]['properties']:
            value=prop['value']; refs=[]
            if isinstance(value,dict) and 'object_id' in value: refs=[value['object_id']]
            elif isinstance(value,dict) and value.get('type')=='list':
                refs=[item['object_id'] for item in value['items'] if 'object_id' in item]
            pending.extend(refs)
    legacy_dialogs={597,602,607,641,646}
    legacy_creates={873,875,889,891,893}
    if reachable & (legacy_dialogs|legacy_creates):
        raise ValueError('Candidate retains a reachable Bruderkrieg choice or scripted spawn')
    event_exports={'$/GFX/Pawn/'+row['unit_export'] for row in CUSTOM_BATTALIONS if row.get('event_deployment')}
    custom_creates=[obj for obj in graph['objects'] if obj['id'] in reachable and obj['class']=='TGDDescriptorCreateUnitOnPosition'
                    and _property(obj,'TypeUnit')['value'] in event_exports]
    if len(custom_creates)!=4:
        raise ValueError('Candidate does not contain exactly four custom event branches')
    groups={_property(obj,'Group')['object_id'] for obj in custom_creates}
    ai_missions=[obj for obj in graph['objects']
                 if obj['class'] in {'TGDDescriptorStrategicDefend','TGDDescriptorStrategicMoveAndAttack'} and
               any(prop['property_name']=='ExecuteOnlyOnIAActivated' and prop['value']['value'] is True
                   for prop in obj['properties'])]
    ai_groups={_property(obj,'Group')['object_id'] for obj in ai_missions}
    if not groups <= ai_groups:
        raise ValueError('Candidate event formation has no strategic AI mission')
    move_groups={_property(obj,'Group')['object_id'] for obj in ai_missions
                 if obj['class']=='TGDDescriptorStrategicMoveAndAttack'}
    if len(move_groups & groups)!=2 or len(groups-move_groups)!=2:
        raise ValueError('Candidate does not give PACT attack and NATO defense missions')
    return {'legacy_choice_dialogs_removed':len(legacy_dialogs),
            'legacy_scripted_spawns_removed':len(legacy_creates),
            'event_branches':len(custom_creates), 'event_ai_missions':len(groups),
            'event_attack_missions':len(move_groups & groups)}


def _initial_ai_contract(definition_raw):
    """Prove map forces use Alsfeld without breaking the native turn loop."""
    _,_,payloads=_payloads(definition_raw)
    script=next(value for name,value in payloads.items() if name.endswith(f'GDScript/{SCENARIO}.ndfbin'))
    _,graph=decode(script)
    objective=next(row['event_deployment']['objective_guid'] for row in CUSTOM_BATTALIONS
                   if row.get('event_deployment',{}).get('event')=='nato')
    objective_words=tuple(_int32_words(objective))
    native_groups=_native_map_groups(graph['objects'])
    blue=native_groups.get('Camp_1',set())
    red=native_groups.get('Camp_0',set())
    def position_matches(reference):
        tag=graph['objects'][reference['object_id']]
        return tag['class']=='TGDTagPosition' and tuple(_property(tag,f'GUID{i}')['value'] for i in range(1,5))==objective_words
    defenders=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorStrategicDefend' and
               _property(obj,'Group')['object_id'] in blue and position_matches(_property(obj,'Position'))]
    attackers=[obj for obj in graph['objects'] if obj['class']=='TGDDescriptorStrategicMoveAndAttack' and
               _property(obj,'Group')['object_id'] in red and
               len(_property(obj,'Positions')['items'])==1 and position_matches(_property(obj,'Positions')['items'][0])]
    defended={_property(obj,'Group')['object_id'] for obj in defenders}
    attacked={_property(obj,'Group')['object_id'] for obj in attackers}
    if defended != blue or attacked != red:
        raise ValueError('Candidate map forces do not all have authored Alsfeld AI objectives')
    launch=graph['objects'][290]
    launch_ids=[item['object_id'] for item in _property(launch,'SubActions')['items']]
    if (not {292,293,294,295,296,297,301} <= set(launch_ids)
            or {298,299,300} & set(launch_ids)):
        raise ValueError('Candidate launch sequence removed aircraft/AP locks or retained old cutscenes')
    clears=[graph['objects'][object_id] for object_id in (295,296,297)]
    if (any(obj['class']!='TGDDescriptorChangePawnActionPoint' for obj in clears)
            or any(any(prop['property_name']=='ActionPointNumber' for prop in obj['properties'])
                   for obj in clears)):
        raise ValueError('Candidate no longer preserves the three native AP-clear actions')
    controllers=[graph['objects'][object_id] for object_id in (350,351)]
    controller_parent=graph['objects'][318]
    controller_children={item['object_id'] for item in _property(controller_parent,'SubActions')['items']}
    if (any(obj['class']!='TGDDescriptorIAStrategicScripted' for obj in controllers)
            or {350,351} - controller_children):
        raise ValueError('Candidate removed a native strategic-AI turn controller')
    main=graph['objects'][301]
    main_children={item['object_id'] for item in _property(main,'SubActions')['items']}
    attack_ids={obj['id'] for obj in attackers}
    attack_containers=[obj for obj in graph['objects']
                       if obj['class']=='TGDDescriptorSimultaneous'
                       and {item.get('object_id') for item in _property(obj,'SubActions')['items']}==attack_ids]
    if len(attack_containers)!=1 or attack_containers[0]['id'] not in main_children:
        raise ValueError('Candidate map attack missions can block the launch sequence')
    return {'initial_blue_defense_groups':len(defended),
            'initial_red_attack_groups':len(attacked),
            'strategic_ai_turn_controllers':len(controllers),
            'initial_ap_clear_groups':len(clears),
            'initial_aircraft_spawns':3,
            'map_attack_missions_parallel':True}


def _definition_contract(raw):
    header, entries, payloads = _payloads(raw)
    if header.version != 3 or len(entries) != 10:
        raise ValueError('Unexpected current Definition archive layout')
    graphs = {name: decode(data)[1] for name,data in payloads.items() if name.endswith('.ndfbin')}
    gd = next(graph for name,graph in graphs.items() if '/GDScript/' in name)
    def exported(path):
        ids = [i for i,name in gd['exports'].items() if name == path]
        if len(ids) != 1: raise ValueError(f'Missing current script export: {path}')
        return gd['objects'][ids[0]]
    tour = _property(exported('$/GDScript/intro/script/Variables/TourMax'), 'Value')['value']
    nato = _property(exported('$/GDScript/intro/script/Variables/score_toReach_OTAN'), 'Value')['value']
    pact = _property(exported('$/GDScript/intro/script/Variables/score_toReach_PACT'), 'Value')['value']
    production, = [obj for obj in gd['objects'] if obj['class'] == 'TGDDescriptorStrategicAddPossibleProduction']
    unlock = gd['objects'][_property(production, 'UnlockAtTurnVariable')['object_id']]
    unlock_turn = _property(unlock, 'Value')['value']
    pawns = _property(production, 'Pawns')['items']
    date, = [obj for obj in gd['objects'] if obj['class'] == 'TGDDescriptorSetInitialDate']
    date_props = {p['property_name']:p['value']['value'] for p in date['properties']}
    loader = next(graph for name,graph in graphs.items() if '/ScenarioLoader/' in name)
    mount, = [obj for obj in loader['objects'] if obj['class'] == 'TClusterMountAdditionalDatapack']
    info = next(graph for name,graph in graphs.items() if '/ScenarioInfo/' in name)
    load_info, = [obj for obj in info['objects'] if obj['class'] == 'TScenarioLoadInfo']
    dictionaries = sorted(
        _property(obj, 'FileName')['value']
        for graph in graphs.values() for obj in graph['objects']
        if obj['class'] == 'TLocalisationDicoResource')
    text_hashes=[]
    def collect(value):
        if isinstance(value,dict):
            if value.get('type')=='loc_hash': text_hashes.append(value['value_hex'])
            else:
                for nested in value.values(): collect(nested)
        elif isinstance(value,list):
            for nested in value: collect(nested)
    for graph in graphs.values():
        for obj in graph['objects']:
            for prop in obj['properties']:
                if prop['property_name']!='DicoToken': collect(prop['value'])
    isolated=[value for value in text_hashes if bytes.fromhex(value).startswith(b'RDLN')]
    return {'script_provider':'current Definition/GDScript', 'tour_limit':tour,
            'nato_score_to_reach':nato, 'pact_score_to_reach':pact,
            'reinforcement_unlock_turn':unlock_turn,
            'reinforcement_battalion_count':len(pawns),
            'reinforcements':[item['value'] for item in pawns],
            'initial_date':[date_props['Annee'],date_props['Mois'],date_props['Jour'],date_props['Periode']],
            'details':_property(mount,'DatapackFileName')['value'],
            'scenario_name':_property(load_info,'Name')['value'],
            'dictionary_sources':dictionaries,
            'isolated_text_hashes':sorted(set(isolated)),
            'isolated_text_references':len(isolated)}


def _generated_dictionary(source, language):
    """Mirror WARNO's ScenariosData -> ZZ localisation projection."""
    prefix = 'ScenariosData:/'
    if not source.startswith(prefix) or not source.endswith('.csv'):
        raise ValueError(f'Unsupported scenario dictionary source: {source}')
    return f'ZZ:/Localisation/{source[len(prefix):-4]}-{language}.dic'


@functools.lru_cache(maxsize=len(VANILLA_MAPS))
def _vanilla_maps(language):
    """Extract the last game-provided MAPS dictionary for one language."""
    if language not in VANILLA_MAPS:
        raise ValueError(f'Unsupported MAPS language: {language}')
    relative, digest = VANILLA_MAPS[language]
    pack = GAME_DATA/relative
    raw = pack.read_bytes()
    header, entries, _ = read_directory(raw)
    resource = f'AllPlatforms/Localisation/{language}/Localisation/Core/MAPS.dic'
    found = [entry for entry in entries if entry.path == resource]
    if len(found) != 1:
        raise ValueError(f'Missing or ambiguous vanilla MAPS resource: {resource}')
    entry = found[0]
    result = raw[header.file_offset+entry.offset:header.file_offset+entry.offset+entry.size]
    if sha256(result) != digest:
        raise ValueError(f'Vanilla MAPS fingerprint mismatch: {language}')
    # Parse it as part of the source contract, not only as an opaque blob.
    if not _trad_data(result):
        raise ValueError(f'Vanilla MAPS dictionary is empty: {language}')
    return result


def _dictionary_keys(root):
    root=Path(root)
    files=sorted((root/SCENARIO).rglob('*.dic'))
    if len(files)!=24:
        raise ValueError('Unexpected campaign dictionary inventory')
    keys=set()
    for path in files:
        keys.update(_trad(path))
    keys.discard(GLYPH_HASH)
    if not keys:
        raise ValueError('Campaign dictionaries contain no keys')
    return keys


def _isolated_hash(key):
    if not isinstance(key,bytes) or len(key)!=8:
        raise ValueError('Localisation hash must be eight bytes')
    return b'RDLN'+hashlib.sha256(b'WARNO-AGF-RedLine1989\0'+key).digest()[:4]


def _hash_mapping(keys):
    mapping={key:_isolated_hash(key) for key in keys}
    if (len(set(mapping.values()))!=len(mapping) or set(mapping)&set(mapping.values())
            or any(value==bytes(8) for value in mapping.values())):
        raise ValueError('Isolated localisation hash collision')
    return mapping


def _remap_trad(raw, mapping):
    values=_trad_data(raw); result={}
    for old,text in values.items():
        if old == GLYPH_HASH:
            new=old
        else:
            if old not in mapping:
                raise ValueError('TRAD key is absent from isolation map')
            new=mapping[old]
        if new in result:
            raise ValueError('Duplicate isolated TRAD key')
        result[new]=text
    return _pack_trad(result)


def _with_event_text(raw, language):
    """Add the choice-event strings without altering any generated entry."""
    values=_trad_data(raw)
    column=1 if language=='RU' else 2
    additions={entry[0]:entry[column] for entry in EVENT_TEXT.values()}
    if set(values)&set(additions):
        raise ValueError('Choice event localisation key collision')
    return _pack_trad({**values,**additions})


def _trad_uint64_sorted(raw):
    if len(raw)<8 or raw[:4]!=b'TRAD':
        return False
    count=struct.unpack_from('<I',raw,4)[0]
    if 8+count*16>len(raw):
        return False
    keys=[raw[8+index*16:16+index*16] for index in range(count)]
    return keys==sorted(keys,key=lambda key:int.from_bytes(key,'little'))


def _early_maps_keys(generated):
    """Recover the exact set needed before ScenarioLoader mounts its dicos."""
    generated=Path(generated)
    custom=_dictionary_keys(generated)
    ru=set(_trad(generated/'Core/MAPS-RU.dic'))
    us=set(_trad(generated/'Core/MAPS-US.dic'))
    keys=custom & ru & us
    digest=hashlib.sha256(b''.join(sorted(keys))).hexdigest()
    if len(keys)!=EARLY_MAPS_COUNT or digest!=EARLY_MAPS_SHA:
        raise ValueError('Early MAPS localisation boundary changed')
    return keys


def _campaign_language_values(generated, language, keys):
    """Select language values for early keys, with deterministic US fallback."""
    generated=Path(generated); result={}
    for name in ('TROPHIES','Scripting/Dialog','Scripting/Localization'):
        values=_trad(generated/f'{SCENARIO}/{name}-{language}.dic')
        for key in keys & set(values):
            if key in result and result[key]!=values[key]:
                raise ValueError(f'Conflicting early campaign text: {language}/{key.hex()}')
            result[key]=values[key]
    fallback=_trad(generated/'Core/MAPS-US.dic')
    for key in keys-result.keys():
        if key not in fallback:
            raise ValueError(f'Missing early campaign text fallback: {key.hex()}')
        result[key]=fallback[key]
    if set(result)!=set(keys):
        raise ValueError(f'Incomplete early campaign localisation: {language}')
    return result


def _runtime_maps(generated, language, mapping):
    """Preserve vanilla MAPS and add only isolated early campaign keys."""
    base=_trad_data(_vanilla_maps(language))
    early=_early_maps_keys(generated)
    values=_campaign_language_values(generated,language,early)
    additions={mapping[key]:values[key] for key in early}
    if set(base)&set(additions):
        raise ValueError(f'Isolated early MAPS collision: {language}')
    merged={**base,**additions}
    result=_pack_trad(merged)
    parsed=_trad_data(result)
    if any(parsed[key]!=value for key,value in base.items()):
        raise ValueError(f'Vanilla MAPS value changed: {language}')
    if set(parsed)-set(base)!=set(additions):
        raise ValueError(f'Unexpected early MAPS additions: {language}')
    return result


def _remap_definition_hashes(raw, mapping):
    doc,graph=decode(raw); expected=copy.deepcopy(graph); changed=0
    def visit(value):
        nonlocal changed
        if isinstance(value,dict):
            if value.get('type')=='loc_hash':
                old=bytes.fromhex(value['value_hex'])
                if old in mapping:
                    value['value_hex']=mapping[old].hex(); changed+=1
            else:
                for nested in value.values(): visit(nested)
        elif isinstance(value,list):
            for nested in value: visit(nested)
    for obj in expected['objects']:
        for prop in obj['properties']:
            if prop['property_name']!='DicoToken': visit(prop['value'])
    if not changed: return raw,0
    result=rebuild_objects(doc,expected); _,after=decode(result)
    if after['objects']!=expected['objects']:
        raise ValueError('Unexpected localisation hash rewrite')
    return result,changed


def build_current_definition(source, config_path, dictionary_keys):
    source, config_path = Path(source).resolve(), Path(config_path).resolve()
    raw = source.read_bytes()
    if sha256(raw) != DEFINITION_SHA:
        raise ValueError('Current Definition source fingerprint mismatch')
    config = json.loads(config_path.read_text(encoding='utf-8'))['campaign']
    mapping=_hash_mapping(set(dictionary_keys))
    header, entries, payloads = _payloads(raw)
    replacements = {}
    def resource(kind, suffix='ndfbin'):
        name = f'NDF/Scenarios/{kind}/{OLD}.{suffix}'
        return name, payloads[name]
    name, gd = resource('GDScript')
    gd, _ = patch_native(gd, {'source_sha256':sha256(gd), 'operations':[
        {'export':'$/GDScript/intro/script/Variables/TourMax','class':'TGDVariableInteger','property':'Value','expected':12,'value':8},
        {'export':'$/GDScript/intro/script/Variables/score_toReach_OTAN','class':'TGDVariableInteger','property':'Value','expected':50,'value':75},
        {'export':'$/GDScript/intro/script/Variables/score_toReach_PACT','class':'TGDVariableInteger','property':'Value','expected':60,'value':75},
        {'export':'$/GDScript/partie_OTAN/Script/Launch_Main_Script_Sequence','root_class':'TGDDescriptorSimultaneous',
         'traverse':[{'property':'SubActions','index':4,'class':'TGDDescriptorSimultaneous'},
                     {'property':'SubActions','index':3,'class':'TGDDescriptorSequential'},
                     {'property':'SubActions','index':2,'class':'TGDDescriptorStrategicAddPossibleProduction'},
                     {'property':'UnlockAtTurnVariable','class':'TGDVariableInteger'}],
         'class':'TGDVariableInteger','property':'Value','expected':9,'value':2},
    ]})
    gd = _patch_reinforcements(gd)
    gd, casualty_report = _start_casualty_actions(gd)
    gd, event_report = _choice_events(gd)
    replacements[name] = gd
    name, value = resource('MapConfiguration')
    # Bruderkrieg here is the existing environment-settings import, not the
    # campaign identity. Retaining it deliberately shares the vanilla map art.
    replacements[name] = _identity(value, properties=[
        {'class':'TStrategicMapInfo','property':'GUID','expected':config['old_scenario_guid_hex'],'value':GUID},
        {'class':'TStrategicMapInfo','property':'OrderToChainMission','expected':10,'value':config['order_to_chain_mission']}])
    name, value = resource('ScenarioInfo')
    replacements[name] = _identity(value, strings=[
        (OLD,SCENARIO),(f'$/ClusterMap/{OLD}/Load',f'$/ClusterMap/{SCENARIO}/Load'),
        (f'Scenarios/ScenarioLoader/{OLD}',f'Scenarios/ScenarioLoader/{SCENARIO}')],
        translations=[(OLD,SCENARIO)], properties=[
        {'class':'TScenarioLoadInfo','property':'GUID','expected':config['old_scenario_guid_hex'],'value':GUID}])
    name, value = resource('ScenarioLoader')
    replacements[name] = _identity(value, strings=[
        (f'Scenarios/{OLD}_Details.dat',f'Scenarios/{SCENARIO}_Details.dat'),
        (f'ScenariosData:/{OLD}/Scripting/Localization.csv',f'{SCENARIO_LOCALISATION}/Scripting/Localization.csv'),
        (f'ScenariosData:/{OLD}/Scripting/Dialog.csv',f'{SCENARIO_LOCALISATION}/Scripting/Dialog.csv')],
        translations=[(OLD,SCENARIO)])
    name, value = resource('Trophy')
    replacements[name] = _identity(value, strings=[
        (f'ScenariosData:/{OLD}/TROPHIES.csv',f'{SCENARIO_LOCALISATION}/TROPHIES.csv')], properties=[
        {'class':'TTrophy','property':'Id','expected':50,'value':9350},
        {'class':'TTrophyUnlockerOnObjectiveCompleted','property':'ObjectiveId','expected':50,'value':9350},
        {'class':'TTrophy','property':'Id','expected':51,'value':9351},
        {'class':'TTrophyUnlockerOnObjectiveCompleted','property':'ObjectiveId','expected':51,'value':9351}])
    for kind in ('GDScript','MapConfiguration','ScenarioInfo','ScenarioLoader','Trophy'):
        name, value = resource(kind, 'tag')
        replacements[name] = _identity(value, strings=[
            (f'Scenarios/{kind}/{OLD}',f'Scenarios/{kind}/{SCENARIO}')])
    remapped=0
    for name in list(replacements):
        if name.endswith('.ndfbin'):
            replacements[name],count=_remap_definition_hashes(replacements[name],mapping)
            remapped+=count
    if remapped<8:
        raise ValueError('Campaign localisation isolation did not reach all menu fields')
    renames = {entry.path:entry.path.replace(OLD,SCENARIO) for entry in entries}
    output = clone_v3(raw, replacements, renames)
    contract = _definition_contract(output)
    expected = {'tour_limit':8,'nato_score_to_reach':75,'pact_score_to_reach':75,
                'reinforcement_unlock_turn':2,'reinforcement_battalion_count':6,
                'reinforcements':list(NEW_REINFORCEMENTS),
                'initial_date':[1989,6,20,2],
                'details':f'Scenarios/{SCENARIO}_Details.dat','scenario_name':SCENARIO,
                'dictionary_sources':sorted([
                    f'{SCENARIO_LOCALISATION}/TROPHIES.csv',
                    f'{SCENARIO_LOCALISATION}/Scripting/Dialog.csv',
                    f'{SCENARIO_LOCALISATION}/Scripting/Localization.csv'])}
    for key,val in expected.items():
        if contract[key] != val: raise ValueError(f'Current Definition contract mismatch: {key}')
    if contract['isolated_text_references']!=remapped + len(EVENT_TEXT):
        raise ValueError('Campaign localisation isolation count mismatch')
    contract.update(casualty_report)
    contract.update(event_report)
    return output, contract


def build_current_details(source, config_path):
    source, config_path = Path(source).resolve(), Path(config_path).resolve()
    raw = source.read_bytes()
    if sha256(raw) != DETAILS_SHA:
        raise ValueError('Current Details source fingerprint mismatch')
    config = json.loads(config_path.read_text(encoding='utf-8'))['campaign']
    data_root=source.parents[3]
    payloads={}
    expected_layers={
        DETAILS_LAYERS[0][0]:{
            'out/CommandZone.ndfbin','out/DeploymentZone.ndfbin',
            'out/IAStratZone.ndfbin','out/LevelDesign.ndfbin',
            'out/MapStrategies.ndfbin','out/PlayableZone.ndfbin'},
        DETAILS_LAYERS[1][0]:{'CamPaths_LevelDesign.ndfbin'},
        DETAILS_LAYERS[2][0]:{'Items.sav','out/LevelDesign.ndfbin'}}
    for relative,digest in DETAILS_LAYERS:
        layer=data_root/relative; layer_raw=layer.read_bytes()
        if sha256(layer_raw)!=digest:
            raise ValueError(f'Current Details layer fingerprint mismatch: {relative}')
        _,entries,current=_payloads(layer_raw)
        if {entry.path for entry in entries}!=expected_layers[relative]:
            raise ValueError(f'Unexpected current Details layer resources: {relative}')
        payloads.update(current)
    if set(payloads)!=DETAILS_RESOURCES:
        raise ValueError('Incomplete current Details overlay composition')
    def patch_spawn_graph(name):
        raw=payloads[name]
        spec={'source_sha256':sha256(raw),'keep':config['spawn_keep'],
              'disable_auto_spawn':True,
              'disabled_position_base':config['disabled_position_base'],
              'disabled_position_step':config['disabled_position_step']}
        return patch_items(raw,spec)
    items, editor_report=patch_spawn_graph('Items.sav')
    level_design, runtime_report=patch_spawn_graph('out/LevelDesign.ndfbin')
    payloads['Items.sav']=items
    payloads['out/LevelDesign.ndfbin']=level_design
    output = pack_v3(payloads)
    out_header,out_entries,_=read_directory(output)
    if out_header.version!=3 or {entry.path for entry in out_entries}!=DETAILS_RESOURCES:
        raise ValueError('Current Details output is not self-contained')
    rows = spawn_inventory(level_design); keep={x['name'] for x in config['spawn_keep']}
    active=[x for x in rows if x['name'] in keep]
    red=[x for x in active if any(t in x['name'] for t in ('_RDA_','_SOV_'))]
    red_aa=[x for x in red if any(token in x['class_name']
                                  for token in ('SAM','FlaK','AirDefence'))]
    red_tanks=[x for x in red if x not in red_aa and
               any(token in x['class_name'] for token in ('PzR','Tk','Tank'))]
    contract = {**runtime_report,
                'editor_output_sha256':editor_report['output_sha256'],
                'runtime_resource':'out/LevelDesign.ndfbin',
                'red_tanks':len(red_tanks),
                'red_air_defence':len(red_aa)}
    if (contract['active_battalions'],contract['red_tanks'],contract['red_air_defence']) != (9,2,2):
        raise ValueError('Current Details force contract mismatch')
    return output, contract


def assemble_current_candidate(modgen_output, localisation_source, destination, config_path,
                               validate=True):
    paths = [Path(p).resolve() for p in (modgen_output,localisation_source,destination,config_path)]
    modgen_output, localisation_source, destination, config_path = paths
    if destination.exists(): raise FileExistsError(f'Refusing to replace candidate: {destination}')
    # The full Gen tree is essential: it contains ModGen's resource registry,
    # which mounts the compiled dictionaries into the game's ZZ: namespace.
    def ignore_generator_state(directory, names):
        ignored = set()
        for name in names:
            if name.startswith('Gen.stale-') or name.endswith('.partial'):
                ignored.add(name)
            if name in {'base.zip', 'CreateModBackup.bat', 'RetrieveModBackup.bat',
                        'GenerateMod.bat', 'LaunchGameDevMode.bat', 'UpdateMod.bat',
                        'UploadMod.bat'}:
                ignored.add(name)
        return ignored
    shutil.copytree(modgen_output, destination, ignore=ignore_generator_state)
    config=scenario_config((modgen_output/'Config.ini').read_bytes(), DISPLAY_NAME)
    (destination/'Config.ini').write_bytes(config)
    generated=localisation_source/'Gen/Localisation/Localisation'
    if not generated.is_dir(): raise ValueError('Compiled localisation source is missing')
    mapping=_hash_mapping(_dictionary_keys(generated))
    definition,_=build_current_definition(Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC\201602\Scenarios\CampagneStrat_Bruderkrieg_Definition.dat'),config_path,mapping.keys())
    details,_=build_current_details(Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC\197351\201602\Scenarios\CampagneStrat_Bruderkrieg_Details.dat'),config_path)
    scenarios=destination/'Scenarios';scenarios.mkdir(exist_ok=True)
    (scenarios/f'{SCENARIO}_Definition.dat').write_bytes(definition)
    (scenarios/f'{SCENARIO}_Details.dat').write_bytes(details)
    runtime=destination/'Gen/Localisation/Localisation'
    for language in ('DEV','FR','GER','POL','RU','SC','SPA','US'):
        for name in ('TROPHIES','Scripting/Dialog','Scripting/Localization'):
            source=generated/f'{SCENARIO}/{name}-{language}.dic'
            target=runtime/f'{SCENARIO}/{name}-{language}.dic'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(_with_event_text(_remap_trad(source.read_bytes(),mapping),language))
    # The out-game campaign menu resolves part of Definition before
    # ScenarioLoader mounts its scenario dictionaries. Publish only those early
    # strings under isolated RDLN keys while preserving every vanilla MAPS pair.
    core=runtime/'Core'; core.mkdir(parents=True,exist_ok=True)
    for language in VANILLA_MAPS:
        content=_with_event_text(_runtime_maps(generated,language,mapping),language)
        targets=(core/f'MAPS-{language}.dic',
                 destination/f'Gen/AllPlatforms/Localisation/Localisation/Core/MAPS-{language}.dic',
                 destination/f'Gen/AllPlatforms/Localisation/{language}/Localisation/Core/MAPS.dic')
        for target in targets:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(content)
    declared_path=destination/'Gen/DeclaredFiles.txt'
    declared=declared_path.read_text(encoding='utf-8').splitlines()
    map_resources=[f'ZZ:/Localisation/Localisation/Core/MAPS-{language}.dic'
                   for language in VANILLA_MAPS if language!='DEV']
    if any('/Core/MAPS-' in line for line in declared):
        raise ValueError('ModGen output unexpectedly already declares Core/MAPS')
    declared_path.write_text('\n'.join(declared+map_resources)+'\n',encoding='utf-8',newline='\n')
    return (validate_current_candidate(destination,config_path)
            if validate else {'validated': False, 'purpose': 'authored-base'})


def validate_current_candidate(root, config_path):
    root,config_path=Path(root).resolve(),Path(config_path).resolve()
    config=json.loads(config_path.read_text(encoding='utf-8'))
    config_raw=(root/'Config.ini').read_bytes()
    validate_scenario_config(config_raw, DISPLAY_NAME)
    archives={'Definition':root/f'Scenarios/{SCENARIO}_Definition.dat',
              'Details':root/f'Scenarios/{SCENARIO}_Details.dat'}
    if set(p.name for p in (root/'Scenarios').glob('*.dat')) != {p.name for p in archives.values()}:
        raise ValueError('Candidate contains legacy or unexpected scenario archives')
    if (root/'ScenariosData').exists(): raise ValueError('Current candidate must share vanilla media/map assets')
    versions={name:read_directory(path.read_bytes())[0].version for name,path in archives.items()}
    if versions != {'Definition':3,'Details':3}: raise ValueError('Candidate archive generation mismatch')
    definition=_definition_contract(archives['Definition'].read_bytes())
    required_definition={'tour_limit':8,'nato_score_to_reach':75,
                         'pact_score_to_reach':75,'reinforcement_unlock_turn':2,
                         'reinforcement_battalion_count':6,
                         'reinforcements':list(NEW_REINFORCEMENTS),
                         'initial_date':[1989,6,20,2],
                         'details':f'Scenarios/{SCENARIO}_Details.dat',
                         'scenario_name':SCENARIO}
    if any(definition.get(key)!=value for key,value in required_definition.items()):
        raise ValueError('Candidate Definition differs from current semantic contract')
    casualty_state = _casualty_contract(archives['Definition'].read_bytes())
    choice_state = _choice_event_contract(archives['Definition'].read_bytes())
    initial_ai_state = _initial_ai_contract(archives['Definition'].read_bytes())
    pawn_path=root/'Gen/NDF/GFX/Pawn.ndfbin'
    if not pawn_path.is_file():
        raise ValueError('Candidate lacks the strategic pawn registry')
    _,pawn_graph=decode(pawn_path.read_bytes(),str(pawn_path))
    pawn_exports=set(pawn_graph['exports'].values())
    required_pawns={row['class_name'] for row in config['campaign']['spawn_keep']}
    required_pawns.update(NEW_REINFORCEMENTS)
    missing_pawns=required_pawns-pawn_exports
    if missing_pawns:
        raise ValueError(f'Candidate lacks a referenced strategic pawn: {sorted(missing_pawns)[0]}')
    custom_battalions = _custom_battalion_contract(root)
    declared = set((root/'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines())
    for source in definition['dictionary_sources']:
        for language in ('FR','GER','POL','RU','SC','SPA','US'):
            generated = _generated_dictionary(source, language)
            if generated not in declared:
                raise ValueError(f'Runtime dictionary is not declared: {generated}')
            disk = root/'Gen'/generated.removeprefix('ZZ:/')
            if not disk.is_file():
                raise ValueError(f'Declared runtime dictionary is missing: {disk}')
    expected_maps={f'ZZ:/Localisation/Localisation/Core/MAPS-{language}.dic'
                   for language in VANILLA_MAPS if language!='DEV'}
    actual_maps={line for line in declared if '/Core/MAPS-' in line}
    if actual_maps!=expected_maps:
        raise ValueError('Runtime Core/MAPS dictionaries are not exactly declared')
    details_source=Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC\197351\201602\Scenarios\CampagneStrat_Bruderkrieg_Details.dat')
    _,details=build_current_details(details_source,config_path)
    actual=archives['Details'].read_bytes(); expected=build_current_details(details_source,config_path)[0]
    if actual != expected: raise ValueError('Candidate Details differs from deterministic build')
    _,detail_entries,_=read_directory(actual)
    if {entry.path for entry in detail_entries}!=DETAILS_RESOURCES:
        raise ValueError('Candidate Details lacks current scenario resources')
    # The mapping must be emitted by WARNO's ModGen rather than improvised in
    # Config.ini. It is the engine's proof that this package is mountable.
    if not authored_registry_path(root).is_file():
        raise ValueError('Candidate lacks the ModGen localisation registry')
    core=root/'Gen/Localisation/Localisation/Core'
    maps={path.stem.removeprefix('MAPS-'):path for path in core.glob('MAPS-*.dic')}
    if set(maps)!=set(VANILLA_MAPS):
        raise ValueError('Candidate lacks the complete vanilla MAPS inventory')
    early_keys=None
    for language,path in maps.items():
        projections=(root/f'Gen/AllPlatforms/Localisation/Localisation/Core/MAPS-{language}.dic',
                     root/f'Gen/AllPlatforms/Localisation/{language}/Localisation/Core/MAPS.dic')
        if any(not projection.is_file() or projection.read_bytes()!=path.read_bytes()
               for projection in projections):
            raise ValueError(f'Runtime MAPS language projection is missing or differs: {language}')
        if not _trad_uint64_sorted(path.read_bytes()):
            raise ValueError(f'Runtime MAPS dictionary is not uint64-sorted: {language}')
        vanilla=_trad_data(_vanilla_maps(language)); actual_maps=_trad(path)
        if any(actual_maps.get(key)!=value for key,value in vanilla.items()):
            raise ValueError(f'Candidate changes a vanilla MAPS entry: {language}')
        additions=set(actual_maps)-set(vanilla)
        event_keys={entry[0] for entry in EVENT_TEXT.values()}
        early_additions=additions-event_keys
        digest=hashlib.sha256(b''.join(sorted(early_additions))).hexdigest()
        if (event_keys-additions or len(early_additions)!=EARLY_MAPS_COUNT
                or digest!=EARLY_ISOLATED_SHA):
            raise ValueError(f'Candidate has an invalid early MAPS overlay: {language}')
        if early_keys is None: early_keys=additions
        elif additions!=early_keys:
            raise ValueError('Candidate early MAPS keys differ between languages')
    custom=root/f'Gen/Localisation/Localisation/{SCENARIO}'
    custom_paths=sorted(custom.rglob('*.dic'))
    if any(not _trad_uint64_sorted(path.read_bytes()) for path in custom_paths):
        raise ValueError('Candidate scenario dictionary is not uint64-sorted')
    dictionaries=[_trad(path) for path in custom_paths]
    if not dictionaries or any(any(key!=GLYPH_HASH and not key.startswith(b'RDLN')
                                   for key in dico) for dico in dictionaries):
        raise ValueError('Candidate localisation is not isolated from vanilla hashes')
    custom_keys=set().union(*(set(dico) for dico in dictionaries))
    custom_keys.discard(GLYPH_HASH)
    maps_keys=set().union(*(_trad(path).keys() for path in maps.values()))
    vanilla_keys=set().union(*(_trad_data(_vanilla_maps(language)).keys()
                               for language in VANILLA_MAPS))
    if custom_keys & vanilla_keys:
        raise ValueError('Candidate localisation collides with vanilla MAPS hashes')
    if not early_keys <= custom_keys or maps_keys-vanilla_keys != early_keys:
        raise ValueError('Candidate early localisation is not consistently isolated')
    ru=_trad(custom/'TROPHIES-RU.dic')
    us=_trad(custom/'TROPHIES-US.dic')
    loc=config['campaign']['localisation']
    if (ru.get(_isolated_hash(TITLE_HASH))!=loc['ru']['title']
            or ru.get(_isolated_hash(SUBTITLE_HASH))!=loc['ru']['subtitle']
            or us.get(_isolated_hash(TITLE_HASH))!=loc['us']['title']):
        raise ValueError('Current candidate title localisation mismatch')
    ru_dialog=_trad(custom/'Scripting/Dialog-RU.dic')
    if (ru_dialog.get(_isolated_hash(BRIEF_HASH))!=loc['ru']['brief']
            or ru_dialog.get(_isolated_hash(OBJECTIVES_HASH))!=loc['ru']['objectives_text']):
        raise ValueError('Current candidate dialog localisation mismatch')
    files=sorted(path for path in root.rglob('*') if path.is_file())
    return {**definition, **casualty_state, **choice_state, **initial_ai_state,
            **{k:v for k,v in details.items() if k!='spec'},
            **custom_battalions,
            'strategic_descriptor_count':len(required_pawns),'archive_versions':versions,
            'details_resources':sorted(DETAILS_RESOURCES),
            'localisation_languages':['RU','US'],
            'vanilla_maps_languages':sorted(VANILLA_MAPS),
            'early_maps_additions':len(early_keys),
            'vanilla_maps_preserved':True,
            'files':{path.relative_to(root).as_posix():sha256(path.read_bytes()) for path in files}}
