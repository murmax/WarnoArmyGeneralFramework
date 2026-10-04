"""Explicit strategic pawn schema; visual assets do not supply gameplay modules."""
from __future__ import annotations

import math
import re
import struct
import uuid


VISUALS = {
    'west_german_infantry': ('mechanized', 'pion_RFA_TKSud_Jag711', 'apc'),
    'east_german_infantry': ('mechanized', 'pion_RDA_4MSD_22MSR_1', 'apc'),
    'west_german_armor': ('mechanized', 'pion_RFA_10PzD_281MxPz', 'Armor_heavy'),
    'east_german_armor': ('mechanized', 'pion_RDA_7PzD_14PzR_1', 'Armor'),
    'soviet_armor': ('mechanized', 'pion_SOV_10GTkD_61GTk_1', 'Armor_heavy'),
    'us_helicopter': ('helicopter', 'pion_US_11ACR_4', 'hel'),
}
ROLES = {'fighter': 'Fighter', 'ground_support': 'GroundSupport',
         'auxiliary_support': 'AuxiliarySupport', 'air_support': 'AirSupport'}
AIR_ICONS = {'fighter': 'AA_air', 'bomber': 'Support_air', 'sead': 'SEAD_air'}
STRATEGIC_ICONS = {'Infantry', 'apc', 'ifv', 'Armor', 'Armor_heavy', 'HQ',
                   'reco', 'AA', 'AT', 'hel', 'howitzer', 'mlrs', 'assault'}


def unit_visual(visual):
    from .visual_catalog import current_visual_catalog

    if (not isinstance(visual, dict) or set(visual) != {'unit'}
            or not isinstance(visual['unit'], str)
            or not re.fullmatch(r'[A-Za-z0-9_]+', visual['unit'])):
        raise ValueError('Invalid strategic unit visual definition')
    catalog = current_visual_catalog()
    if visual['unit'] not in catalog:
        raise ValueError('Unknown strategic visual unit: ' + visual['unit'])
    return catalog[visual['unit']]


def pawn_visual(row):
    visual = row['strategic']['visual']
    if isinstance(visual, str):
        _, name, icon = VISUALS[visual]
        return name, icon, 'Texture_Button_Pawn_' + name
    resolved = unit_visual(visual)
    icon = ('hel' if row['strategic']['type'] == 'helicopter'
            else 'Infantry' if resolved['category'] == 'infantry' else 'Armor')
    if row['strategic']['type'] == 'airplane':
        icon = AIR_ICONS[row['strategic']['aircraft_role']]
    else:
        icon = row['strategic'].get('icon', icon)
    return 'AGFW_Visual_' + row['id'], icon, resolved['texture']


def authored_depiction(row):
    visual = unit_visual(row['strategic']['visual'])
    name, _, _ = pawn_visual(row)
    template = {'vehicle': 'GroundVehicle', 'infantry': 'Infantry',
                'helicopter': 'Helicopter', 'airplane': 'Airplane'}[visual['category']]
    base = visual_base(row)
    return ('Depiction_' + name + ' is Strategic' + template + 'PawnDepictionDesc\n(\n'
            '    MeshDescriptorPawn = $/GFX/DepictionResources/' + visual['mesh'] + '\n'
            '    MeshSocle = $/GFX/DepictionResources/' + base + '\n)\n'
            'export Gfx_' + name + ' is TTimelyDepictionReceiverFactory('
            ' DepictionDescriptor = Depiction_' + name + ')\n')


def visual_base(row):
    country = {'RDA': 'DDR'}.get(row['country'], row['country'])
    if country not in {'US', 'RFA', 'SOV', 'DDR', 'UK', 'BEL', 'NL', 'POL',
                       'CAN', 'ESP', 'FR', 'TCH', 'CUB'}:
        raise ValueError('Unsupported strategic visual base country: ' + country)
    return 'MeshModele_Socle_' + country


def validate_strategy(strategy):
    fields = {'type', 'battle_role', 'visual'}
    if isinstance(strategy, dict) and 'icon' in strategy:
        fields.add('icon')
        if not isinstance(strategy['icon'], str) or strategy['icon'] not in STRATEGIC_ICONS or strategy.get('type') == 'airplane':
            raise ValueError('Invalid explicit strategic icon')
    if isinstance(strategy, dict) and 'support' in strategy:
        fields.add('support')
    if isinstance(strategy, dict) and strategy.get('type') == 'airplane':
        fields.add('aircraft_role')
    if (not isinstance(strategy, dict)
            or set(strategy) != fields
            or any(not isinstance(strategy[field], str) for field in ('type', 'battle_role'))
            or strategy['type'] not in {'mechanized', 'helicopter', 'airplane'}
            or strategy['battle_role'] not in ROLES):
        raise ValueError('Invalid strategic pawn definition')
    airplane = strategy['type'] == 'airplane'
    if airplane != (strategy['battle_role'] == 'air_support'):
        raise ValueError('Incompatible strategic airplane battle role')
    if airplane and (not isinstance(strategy['aircraft_role'], str)
                     or strategy['aircraft_role'] not in AIR_ICONS):
        raise ValueError('Invalid strategic aircraft_role')
    if isinstance(strategy['visual'], str):
        if strategy['visual'] not in VISUALS:
            raise ValueError('Unknown strategic pawn visual')
        if VISUALS[strategy['visual']][0] != strategy['type']:
            raise ValueError('Incompatible strategic pawn type and visual')
    else:
        unit_visual(strategy['visual'])
    if 'support' in strategy:
        support = strategy['support']
        if (not isinstance(support, dict) or set(support) != {'kind', 'radius_ap'}
                or not isinstance(support['kind'], str)
                or support['kind'] not in {'air_defence', 'artillery'}
                or type(support['radius_ap']) not in (int, float)
                or not 0 < support['radius_ap'] <= 1000
                or not math.isfinite(support['radius_ap'])):
            raise ValueError('Invalid strategic support kind or radius_ap (0 < radius <= 1000)')
        expected_role = 'auxiliary_support' if support['kind'] == 'air_defence' else 'ground_support'
        if strategy['type'] != 'mechanized' or strategy['battle_role'] != expected_role:
            raise ValueError('Incompatible strategic support type or battle role')


def authored_pawn(row, namespace):
    strategy = row['strategic']
    validate_strategy(strategy)
    visual, icon, texture = pawn_visual(row)
    ground = strategy['type'] == 'mechanized'
    airplane = strategy['type'] == 'airplane'
    tags = ['AllUnits'] + (['SM_combat_btn'] if ground and strategy['battle_role'] == 'fighter'
                           else ['Helicopter'] if strategy['type'] == 'helicopter' else [])
    movement = 'mecanized' if ground else 'aerial' if airplane else 'helico'
    support = strategy.get('support')
    orders = ['EOrderType/Move']
    support_field = 'BattleSupportRadiusInAPCase = -1.0 ' if airplane else ''
    if support:
        if support['kind'] == 'air_defence':
            tags.append('AntiAir')
            orders.append('EOrderType/FortifyAntiAir')
            icon = 'AA'
            support_field = 'AirDenyRadiusInAPCase'
        else:
            movement, icon = 'howitzer', 'howitzer'
            support_field = 'BattleSupportRadiusInAPCase'
        support_field += ' = ' + str(float(support['radius_ap'])) + ' '
    guid = str(uuid.uuid5(namespace, row['unit_export']))
    modules = [
        'TTypeUnitModuleDescriptor(' + 'Coalition = TWargameCoalition/' + row['coalition']
        + " MotherCountry = '" + row['country'] + "')",
        'AirplaneFlagsModuleDescriptor' if airplane else 'DefaultFlagsModuleDescriptor',
        '~/PawnPositionModuleDescriptor', '~/LinkTeamModuleDescriptor',
        'TTagsModuleDescriptor(TagSet = [' + ', '.join('"' + tag + '"' for tag in tags + row.get('runtime_tags',[])) + '])',
        'TApparenceModuleDescriptor(PickableObject = True Depiction = $/GFX/Depiction/Gfx_'
        + visual + ' ReferenceMesh = $/GFX/DepictionResources/MeshModele_Socle_US'
        + ' BlackHoleKey = "' + row['id'] + '")',
    ]
    if ground:
        modules.append('TInfluenceMapModuleDescriptor(InfluenceStrength = 1.0 '
                       'MinimumInfluenceStrength = 0.0 StrengthDecayPerSecond = 0.3 '
                       'PreventsDecayInZone = False)')
    modules.extend([
        *([] if airplane else ['~/InfluencePositionModuleDescriptor', '~/InfluenceDataModuleDescriptor']),
        '~/StrategicStateEngineModuleDescriptor', '~/StrategicSelectionModuleDescriptor',
        *([] if airplane else ['~/StrategicIdleStatusModuleDescriptor']), '~/EffectApplierModuleDescriptor',
        'TStrategicLabelModuleDescriptor(BackgroundTexture = '
        'TBUCKToolAlternativeValues_TUIValueTextureNameFromTEugBMutableInteger('
        'CommandNameTrigger = ~/SpecificCommandName/UpdateGUIFromStrategicIconType '
        'Alterator = $/GUIOption/StrategicIconType Values = ["Texture_STRATEGIC_RTS_H_'
        + icon + '", "Texture_STRATEGIC_' + icon + '"]))',
        ('~/PawnAirplaneOrderConfigModuleDescriptor' if airplane else
         'TOrderableModuleDescriptor(UnlockableOrders = [' + ', '.join(orders) + '])'),
        "TDeckModuleDescriptor(DeckIdentifier = '" + row['deck_id'] + "' Score = 1)",
        'TStrategicBattleModuleDescriptor(CanBeInitialTarget = ' + str(not airplane)
        + ' HasZoneOfControl = ' + str(not airplane) + ' '
        + support_field + 'BattleRole = ~/EStrategicBattleRole/' + ROLES[strategy['battle_role']] + ')',
        'TVisibilityModuleDescriptor(UnitConcealmentBonus = 1.0)',
        'TReverseScannerWithIdentificationDescriptor(IdentifyBaseProbability = 0.0 '
        'TimeBetweenEachIdentifyRoll = 0.0 '
        'VisibilityRuleDescriptor = $/GFX/VisionRules/StandardWargameVisibilityRollRule)',
        'TActionPointsModuleDescriptor(InitialActionPoint = ' + str(row['state']['action_points']['initial'])
        + ' ActionPointRecoveryPerTurn = ' + str(row['state']['action_points']['recovery'])
        + ' NbInitialActionsPointsForProducedPawn = ' + str(row['state']['action_points']['recovery']) + ')',
        *([] if airplane else ['~/ActionPointsReachModuleDescriptor']),
        '~/StrategicMovementDescriptor_' + movement,
        *(['~/StrategicAerialModuleDescriptor'] if airplane else []),
        "StrategicUIModuleDescriptor(NameToken ='" + row['name_token']
        + "' ProdMenuTexture = '" + texture + "')",
        *([] if airplane else ['~/IALinkToGroupModuleDescriptor']), '~/StrategicPositionModuleDescriptor',
        '~/StrategicSequenceModuleDescriptor',
        'StrategicFatigueModuleDescriptor( InitialFatigue  = ' + str(row['state']['fatigue']) + ' )',
        '~/IAStratZoneIndexModuleDescriptor',
    ])
    block = '\n'.join([
        'export ' + row['unit_export'] + ' is TEntityDescriptor', '(',
        '    DescriptorId = GUID:{' + guid + '}',
        "    ClassNameForDebug = 'Pawn_" + row['id'] + "'", '    ModulesDescriptors = [',
        *('        ' + module + ',' for module in modules), '    ]', ')',
    ])
    return block, guid


def ghost_mimetic_contract(raw, compiled):
    from .cndf import decode
    from .current_campaign import _property

    _, graph = decode(raw)
    objects = graph['objects']
    registrations = {}
    for obj in objects:
        if obj['class'] != 'TGhostMimeticRegistration' or not obj['is_top_object']:
            continue
        for entry in _property(obj, 'GhostMimetics')['items']:
            registrations.setdefault(entry['key']['value'], []).append(entry['value'])
    report = {}
    for row in compiled['battalions']:
        oob = row.get('oob')
        if oob is None:
            continue
        visual = (pawn_visual(oob)[0] if 'strategic' in oob
                  else oob['base_unit'].removeprefix('Descriptor_Unit_'))
        receivers = [objects[index] for index, path in graph['exports'].items()
                     if path == '$/GFX/Depiction/Gfx_' + visual]
        matches = registrations.get(oob['id'], [])
        if len(receivers) != 1 or len(matches) != 1:
            raise ValueError('Missing or ambiguous ghost mimetic: ' + row['id'])
        expected = _property(receivers[0], 'DepictionDescriptor')
        if matches[0] != expected:
            raise ValueError('Wrong ghost mimetic visual: ' + row['id'])
        report[row['id']] = {'key': oob['id'], 'visual': visual}
        if isinstance(oob.get('strategic', {}).get('visual'), dict):
            resolved = unit_visual(oob['strategic']['visual'])
            base = visual_base(oob)
            stem = ('moyenne' if resolved['category'] in ('airplane', 'helicopter')
                    else 'courte')
            expected_meshes = [base, 'MeshModele_Tige_' + stem, resolved['mesh']]
            meshes, visited = [], set()

            def walk(reference):
                index = reference['object_id']
                if index in visited:
                    raise ValueError('Cyclic or shared strategic visual tree: ' + row['id'])
                visited.add(index)
                for prop in objects[index]['properties']:
                    name, field = prop['property_name'], prop['value']
                    if name == 'MeshDescriptor':
                        meshes.append(field.get('value'))
                    elif name in ('SubDepictions', 'DepictionAlternatives'):
                        for item in field['items']:
                            walk(item)
                    elif name == 'Depiction':
                        walk(field)

            walk(expected)
            if meshes != ['$/GFX/DepictionResources/' + mesh for mesh in expected_meshes]:
                raise ValueError('Wrong strategic visual mesh or base: ' + row['id'])
            report[row['id']].update(mesh=resolved['mesh'], base=base)
    return report


def pawn_strategy_contract(raw, compiled):
    from .cndf import decode
    from .current_campaign import _property

    _, graph = decode(raw)
    objects = graph['objects']
    report = {}
    for row in compiled['battalions']:
        strategy = row.get('oob', {}).get('strategic')
        if strategy is None:
            continue
        validate_strategy(strategy)
        path = '$/GFX/Pawn/' + row['unit_export']
        found = [key for key, value in graph['exports'].items() if value == path]
        if len(found) != 1:
            raise ValueError('Missing strategic pawn export: ' + row['id'])
        modules = [objects[item['object_id']] for item in
                   _property(objects[found[0]], 'ModulesDescriptors')['items']]

        def single(class_name):
            matches = [module for module in modules if module['class'] == class_name]
            if len(matches) != 1:
                raise ValueError('Invalid strategic pawn module: ' + row['id'] + ': ' + class_name)
            return matches[0]

        def value(module, name):
            return _property(module, name)['value']

        ground = strategy['type'] == 'mechanized'
        airplane = strategy['type'] == 'airplane'
        tags = [item['value'] for item in _property(single('TTagsModuleDescriptor'), 'TagSet')['items']]
        expected_tags = ['AllUnits'] + (['SM_combat_btn'] if ground and strategy['battle_role'] == 'fighter'
                                       else ['Helicopter'] if strategy['type'] == 'helicopter' else [])
        expected_tags += row['oob'].get('runtime_tags',[])
        visual, icon, texture_name = pawn_visual(row['oob'])
        support = strategy.get('support')
        expected_movement = 'mecanized' if ground else 'aerial' if airplane else 'helico'
        expected_orders = [23]
        expected_radii = {'BattleSupportRadiusInAPCase': -1.0} if airplane else {}
        if support:
            radius = struct.unpack('<f', struct.pack('<f', float(support['radius_ap'])))[0]
            if support['kind'] == 'air_defence':
                expected_tags.append('AntiAir')
                expected_orders.append(15)
                icon = 'AA'
                expected_radii = {'AirDenyRadiusInAPCase': radius}
            else:
                expected_movement, icon = 'howitzer', 'howitzer'
                expected_radii = {'BattleSupportRadiusInAPCase': radius}
        movement = value(single('TStrategicMovementModuleDescriptor'), '_ShortDatabaseName')
        battle = single('TStrategicBattleModuleDescriptor')
        radii = {prop['property_name']: prop['value']['value'] for prop in battle['properties']
                 if prop['property_name'] in ('AirDenyRadiusInAPCase', 'BattleSupportRadiusInAPCase')}
        if airplane:
            forbidden = {'TOrderableModuleDescriptor', 'TInfluenceMapModuleDescriptor',
                         'TInfluencePositionModuleDescriptor', 'TInfluenceDataModuleDescriptor',
                         'TActionPointsReachModuleDescriptor', 'TIALinkToGroupModuleDescriptor',
                         'TStrategicIdleStatusModuleDescriptor'}
            if any(module['class'] in forbidden for module in modules):
                raise ValueError('Ground-only module on strategic airplane: ' + row['id'])
            single('TStrategicAerialModuleDescriptor')
            action_points = single('TActionPointsModuleDescriptor')
            flags = single('TFlagsModuleDescriptor')
            if (value(single('TOrderConfigModuleDescriptor'), '_ShortDatabaseName') != 'PawnAirplaneOrderConfigModuleDescriptor'
                    or value(flags, '_ShortDatabaseName') != 'AirplaneFlagsModuleDescriptor'
                    or [item['value'] for item in _property(flags, 'InitialFlagSet')['items']] != [5, 0]
                    or any(value(action_points, name) != 4 for name in
                           ('InitialActionPoint', 'ActionPointRecoveryPerTurn', 'NbInitialActionsPointsForProducedPawn'))):
                raise ValueError('Wrong strategic airplane flags, orders or action points: ' + row['id'])
            orders = expected_orders
        else:
            orders = [item['value'] for item in _property(single('TOrderableModuleDescriptor'), 'UnlockableOrders')['items']]
        role = next((item['value']['value'] for item in battle['properties']
                     if item['property_name'] == 'BattleRole'), 0)
        appearance = single('TApparenceModuleDescriptor')
        label = single('TStrategicLabelModuleDescriptor')
        texture = objects[_property(label, 'BackgroundTexture')['object_id']]
        icons = [item['value'] for item in _property(texture, 'Values')['items']]
        influences = [module for module in modules if module['class'] == 'TInfluenceMapModuleDescriptor']
        expected_role = {'fighter': 0, 'auxiliary_support': 1, 'ground_support': 3, 'air_support': 2}[strategy['battle_role']]
        target = next((prop['value']['value'] for prop in battle['properties']
                       if prop['property_name'] == 'CanBeInitialTarget'), False)
        zone = next((prop['value']['value'] for prop in battle['properties']
                     if prop['property_name'] == 'HasZoneOfControl'), False)
        if (tags != expected_tags
                or movement != 'StrategicMovementDescriptor_' + expected_movement
                or orders != expected_orders or radii != expected_radii
                or target is not (not airplane)
                or zone is not (not airplane)
                or role != expected_role or len(influences) != int(ground)
                or value(appearance, 'Depiction') != '$/GFX/Depiction/Gfx_' + visual
                or value(appearance, 'BlackHoleKey') != row['oob']['id']
                or icons != ['Texture_STRATEGIC_RTS_H_' + icon, 'Texture_STRATEGIC_' + icon]
                or value(single('TPawnUIModuleDescriptor'), 'ProdMenuTexture')
                    != texture_name):
            raise ValueError('Mismatched strategic pawn behavior or visual: ' + row['id'])
        report[row['id']] = dict(strategy)
    return report
