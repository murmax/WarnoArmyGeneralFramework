"""Authored airports and aircraft availability, separate from ground production."""
import copy
import hashlib
import re


def compile_aviation(document, campaign, battalions, events, bounds):
    from .authoring import _exact, _guid, _identifier, _point, _side
    from .pawn import visual_base

    _exact(document, {'schema', 'airfields', 'wings'}, 'aviation')
    if type(document['schema']) is not int or document['schema'] != 1:
        raise ValueError('Unsupported aviation schema')
    if not isinstance(document['airfields'], list) or not isinstance(document['wings'], list):
        raise ValueError('Aviation airfields and wings must be lists')
    airfields = {}
    for original in document['airfields']:
        _exact(original, {'id', 'side', 'country', 'position', 'name'}, 'airfield')
        row = copy.deepcopy(original)
        identifier = _identifier(row['id'], 'airfield.id')
        if identifier in airfields:
            raise ValueError('Duplicate airfield: ' + identifier)
        _side(row['side'], 'airfield.side')
        if not isinstance(row['country'], str) or not re.fullmatch('[A-Z]{2,3}', row['country']):
            raise ValueError('Invalid airfield country')
        visual_base(row)
        _exact(row['name'], {'ru', 'en'}, 'airfield.name')
        if any(not isinstance(value, str) or not value.strip() for value in row['name'].values()):
            raise ValueError('Airfield requires localized names')
        row['position'] = _point(row['position'], 'airfield.position', bounds)
        digest = hashlib.sha256((campaign['id'] + ':airfield:' + identifier).encode()).hexdigest()[:16]
        row['unit_export'] = 'Descriptor_Unit_AGF_Airfield_' + digest
        row['descriptor_guid'] = _guid('airfield_descriptor', campaign['id'], identifier)
        row['guid'] = _guid('airfield_position', campaign['id'], identifier)
        airfields[identifier] = row
    event_by_id = {event['id']: event for event in events}
    wings, used = [], set()
    for original in document['wings']:
        _exact(original, {'battalion', 'airfield', 'available'}, 'air wing',optional={'withdraw_turn','initial_losses'})
        row = copy.deepcopy(original)
        identifier = row['battalion']
        if not isinstance(identifier, str) or identifier not in battalions or identifier in used:
            raise ValueError('Unknown or duplicate air wing battalion')
        battalion = battalions[identifier]
        if battalion.get('oob', {}).get('strategic', {}).get('type') != 'airplane':
            raise ValueError('Air wing requires an authored airplane battalion')
        if 'withdraw_turn' in row and (type(row['withdraw_turn']) is not int or not 1<=row['withdraw_turn']<=campaign['turns']):
            raise ValueError('Air wing withdrawal turn is outside the campaign')
        if 'initial_losses' in row:
            from .losses import bounded_loss_budget,roster_ticket_costs
            specification=row['initial_losses']
            _exact(specification,{'max_percent'},'air wing.initial_losses')
            row['loss_budget']=bounded_loss_budget(roster_ticket_costs(battalion['oob']),specification['max_percent'])
        if not isinstance(row['airfield'], str) or row['airfield'] not in airfields:
            raise ValueError('Air wing references unknown airfield')
        field = airfields[row['airfield']]
        if field['side'] != battalion['side']:
            raise ValueError('Air wing cannot bind to an enemy airfield')
        available = row['available']
        if not isinstance(available, dict) or set(available) not in ({'turn'}, {'event', 'choice'}):
            raise ValueError('Air wing availability must use turn or event+choice')
        if 'turn' in available:
            if type(available['turn']) is not int or not 1 <= available['turn'] <= campaign['turns']:
                raise ValueError('Air wing turn is outside the campaign')
        else:
            event_id = available['event']
            if not isinstance(event_id, str) or event_id not in event_by_id:
                raise ValueError('Air wing availability references unknown event')
            event = event_by_id[event_id]
            if (event['side'] != battalion['side'] or type(available['choice']) is not int
                    or not 0 <= available['choice'] < len(event['choices'])):
                raise ValueError('Air wing availability references wrong side or choice')
        if 'withdraw_turn' in row:
            arrival = available.get('turn') if 'turn' in available else event['trigger'].get('turn')
            if arrival is None or row['withdraw_turn'] <= arrival:
                raise ValueError('Air wing withdrawal needs a dated arrival before its withdrawal')
        used.add(identifier)
        row.update(side=battalion['side'], unit_export=battalion['unit_export'],
                   position=list(field['position']))
        if 'withdraw_turn' in row:
            row['tracking_tag'] = 'AGF_AirWing_' + battalion['unit_export'].removeprefix('Descriptor_Unit_')
            battalion['oob']['runtime_tags'] = [row['tracking_tag']]
        wings.append(row)
    unbound = sorted(identifier for identifier, row in battalions.items()
                     if row.get('oob', {}).get('strategic', {}).get('type') == 'airplane'
                     and identifier not in used)
    if unbound:
        raise ValueError('Aviation contains unbound aircraft: ' + ', '.join(unbound))
    return {'airfields': list(airfields.values()), 'wings': wings,
            **({'withdrawal_version':2} if any('withdraw_turn' in w for w in wings) else {})}


def authored_airfield(row):
    from uuid import UUID

    modules = [
        'TTypeUnitModuleDescriptor(Coalition = TWargameCoalition/' + row['side'].upper()
        + " MotherCountry = '" + row['country'] + "')",
        'DefaultFlagsModuleDescriptor', '~/BuildingPositionModuleDescriptor', '~/LinkTeamModuleDescriptor',
        'TInfluenceMapModuleDescriptor(InfluenceStrength = 1.0 MinimumInfluenceStrength = 1.0 '
        'StrengthDecayPerSecond = 0.0 PreventsDecayInZone = True)',
        '~/InfluencePositionModuleDescriptor', '~/InfluenceDataModuleDescriptor',
        'TTagsModuleDescriptor(TagSet = ["AllUnits"])',
        'TIAStratModuleDescriptor(DatabaseId = 0 GameplayBehavior = EGameplayBehavior/Nothing)',
        '~/EffectApplierModuleDescriptor', 'TVisibilityModuleDescriptor(UnitConcealmentBonus = 1.0)',
        '~/PawnBuildingScannerConfigurationDescriptor',
        'TReverseScannerWithIdentificationDescriptor(IdentifyBaseProbability = 1.0 '
        'TimeBetweenEachIdentifyRoll = 0.0 '
        'VisibilityRuleDescriptor = $/GFX/VisionRules/StandardWargameVisibilityRollRule)',
        '~/StrategicBuildingModuleDescriptor', 'TStrategicAirportModuleDescriptor()',
        'TStrategicPositionModuleDescriptor(KernelRadius = 1)',
    ]
    return '\n'.join([
        'export ' + row['unit_export'] + ' is TEntityDescriptor', '(',
        '    DescriptorId = GUID:{' + str(UUID(row['descriptor_guid'])) + '}',
        "    ClassNameForDebug = '" + row['unit_export'] + "'", '    ModulesDescriptors = [',
        *('        ' + module + ',' for module in modules), '    ]', ')',
    ])


def airfield_descriptor_contract(raw, compiled):
    from uuid import UUID
    from .cndf import decode
    from .current_campaign import _property

    fields = compiled.get('aviation', {}).get('airfields', [])
    if not fields:
        return {}
    _, graph = decode(raw)
    objects = graph['objects']
    expected_classes = {
        'TTypeUnitModuleDescriptor', 'TFlagsModuleDescriptor', 'TPositionModuleDescriptor',
        'TLinkTeamModuleDescriptor', 'TInfluenceMapModuleDescriptor',
        'TInfluencePositionModuleDescriptor', 'TInfluenceDataModuleDescriptor',
        'TTagsModuleDescriptor', 'TIAStratModuleDescriptor', 'TEffectApplierModuleDescriptor',
        'TVisibilityModuleDescriptor', 'TScannerConfigurationDescriptor',
        'TReverseScannerWithIdentificationDescriptor', 'TWargameBuildingModuleDescriptor',
        'TStrategicAirportModuleDescriptor', 'TStrategicPositionModuleDescriptor',
    }
    report = {}
    for field in fields:
        identifiers = [index for index, path in graph['exports'].items()
                       if path == '$/GFX/Pawn/' + field['unit_export']]
        if len(identifiers) != 1:
            raise ValueError('Airfield export missing or ambiguous: ' + field['id'])
        pawn = objects[identifiers[0]]
        if (pawn['class'] != 'TEntityDescriptor'
                or _property(pawn, 'DescriptorId')['value_hex'] != UUID(field['descriptor_guid']).hex):
            raise ValueError('Airfield identity mismatch: ' + field['id'])
        modules = [objects[item['object_id']] for item in _property(pawn, 'ModulesDescriptors')['items']]
        if len(modules) != len(expected_classes) or {module['class'] for module in modules} != expected_classes:
            raise ValueError('Airfield module inventory mismatch: ' + field['id'])
        by_class = {module['class']: module for module in modules}

        def value(kind, name, default=None):
            return next((prop['value'].get('value') for prop in by_class[kind]['properties']
                         if prop['property_name'] == name), default)

        expected = (
            ('TTypeUnitModuleDescriptor', 'MotherCountry', field['country'], None),
            ('TTypeUnitModuleDescriptor', 'Coalition', 0 if field['side'] == 'nato' else 1, 0),
            ('TPositionModuleDescriptor', '_ShortDatabaseName', 'BuildingPositionModuleDescriptor', None),
            ('TLinkTeamModuleDescriptor', '_ShortDatabaseName', 'LinkTeamModuleDescriptor', None),
            ('TInfluenceMapModuleDescriptor', 'InfluenceStrength', 1.0, None),
            ('TInfluenceMapModuleDescriptor', 'MinimumInfluenceStrength', 1.0, None),
            ('TInfluenceMapModuleDescriptor', 'StrengthDecayPerSecond', 0.0, 0.0),
            ('TInfluenceMapModuleDescriptor', 'PreventsDecayInZone', True, False),
            ('TWargameBuildingModuleDescriptor', '_ShortDatabaseName', 'StrategicBuildingModuleDescriptor', None),
            ('TStrategicPositionModuleDescriptor', 'KernelRadius', 1, None),
        )
        for kind, name, wanted, default in expected:
            if value(kind, name, default) != wanted:
                raise ValueError('Airfield property mismatch: ' + field['id'] + ': ' + name)
        report[field['id']] = {'country': field['country'], 'side': field['side'],
                              'unit_export': field['unit_export'], 'native_airport': True}
    return report
