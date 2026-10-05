"""Native reserve authoring: divisions, scheduled regiments and deployment points."""
from __future__ import annotations

import copy
import hashlib


def compile_production(document, campaign, battalions, bounds):
    from .authoring import _exact, _guid, _identifier, _point, _side

    _exact(document, {'schema', 'deployment_points', 'divisions', 'groups'}, 'production')
    if type(document['schema']) is not int or document['schema'] != 1:
        raise ValueError('Unsupported production schema')

    def rows(section, fields, optional=frozenset()):
        if not isinstance(document[section], list):
            raise ValueError('production.' + section + ' must be a list')
        seen = set()
        for row in document[section]:
            _exact(row, fields, 'production.' + section, optional=optional)
            item_id = _identifier(row['id'], section + '.id')
            if item_id in seen:
                raise ValueError('Duplicate production ' + section + ' id: ' + item_id)
            seen.add(item_id)
            yield copy.deepcopy(row)

    def text(value, where):
        _exact(value, {'ru', 'en'}, where)
        if any(not isinstance(item, str) or not item.strip() for item in value.values()):
            raise ValueError(where + ' must contain nonempty localized text')

    def references(values, lookup, where):
        if (not isinstance(values, list) or not values
                or any(not isinstance(item, str) or item not in lookup for item in values)
                or len(values) != len(set(values))):
            raise ValueError(where + ' contains missing, unknown or duplicate references')

    points = {}
    for row in rows('deployment_points', {'id', 'side', 'position', 'name'}):
        _side(row['side'], 'deployment_point.side')
        text(row['name'], 'deployment_point.name')
        row['position'] = _point(row['position'], 'deployment_point.position', bounds)
        row['guid'] = _guid('production_point', campaign['id'], row['id'])
        points[row['id']] = row

    divisions = {}
    used_points = set()
    for row in rows('divisions', {'id', 'side', 'name', 'short_name', 'deployment_points'}, {'required_flag'}):
        if 'required_flag' in row:
            _identifier(row['required_flag'], 'division.required_flag')
        _side(row['side'], 'division.side')
        text(row['name'], 'division.name')
        text(row['short_name'], 'division.short_name')
        references(row['deployment_points'], points, 'division.deployment_points')
        if any(points[item]['side'] != row['side'] for item in row['deployment_points']):
            raise ValueError('Division deployment points belong to another coalition')
        used_points.update(row['deployment_points'])
        row['identity'] = _guid('production_division', campaign['id'], row['id'])
        row['availability_policy'] = 'native_safe_rear_chain'
        row['ai_placement_policy'] = 'first_available'
        divisions[row['id']] = row

    groups = []
    used_battalions = set()
    used_divisions = set()
    for row in rows('groups', {'id', 'division', 'name', 'turn', 'battalions'},
                    {'ai', 'member_ai', 'when'}):
        if 'when' in row:
            from .choice_conditions import validate_requirements
            row['when'] = validate_requirements(row['when'], 'production.' + row['id'] + '.when')
        if not isinstance(row['division'], str) or row['division'] not in divisions:
            raise ValueError('Unknown reserve division')
        division = divisions[row['division']]
        text(row['name'], 'regiment.name')
        if type(row['turn']) is not int or not 1 <= row['turn'] <= campaign['turns']:
            raise ValueError('Reserve turn must be within the campaign')
        references(row['battalions'], battalions, 'regiment.battalions')
        if any(battalions[item]['side'] != division['side'] for item in row['battalions']):
            raise ValueError('Reserve battalion belongs to another coalition')
        if any(battalions[item].get('oob', {}).get('strategic', {}).get('type') == 'airplane'
               for item in row['battalions']):
            raise ValueError('Ground production cannot contain air wings; use airfield availability')
        if used_battalions.intersection(row['battalions']):
            raise ValueError('Reserve battalion instantiated more than once')
        if 'member_ai' in row and (not isinstance(row['member_ai'], dict)
                or not row['member_ai']
                or any(item not in row['battalions'] for item in row['member_ai'])):
            raise ValueError('member_ai must map battalions from its production card')
        used_battalions.update(row['battalions'])
        used_divisions.add(row['division'])
        row['side'] = division['side']
        if 'required_flag' in division:
            row['required_flag'] = division['required_flag']
        row['identity'] = _guid('production_regiment', campaign['id'], row['id'])
        row['unit_exports'] = [battalions[item]['unit_export'] for item in row['battalions']]
        groups.append(row)
    if set(points) != used_points or set(divisions) != used_divisions:
        raise ValueError('Production contains unused deployment points or divisions')
    return {'deployment_points': list(points.values()), 'divisions': list(divisions.values()),
            'groups': groups}


def production_script_contract(graph, compiled, reachable):
    from .bruderkrieg import _capture_deadline_contract
    deadline_variable = _capture_deadline_contract(graph, compiled)
    from .bruderkrieg import authored_text_key
    from .current_campaign import _int32_words

    production = compiled.get('production', {'divisions': [], 'groups': [], 'deployment_points': []})
    objects = graph['objects']
    campaign_id = compiled['campaign']['id']
    register_class = 'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction'
    add_class = 'TGDDescriptorStrategicAddPossibleProduction'
    division_class = 'TGDStrategicReinforcementGroup'

    def require(condition, detail):
        if not condition:
            raise ValueError('Authored production ' + detail)

    def field(obj, name, default=None):
        values = [row['value'] for row in obj['properties'] if row['property_name'] == name]
        if not values and default is not None:
            return default
        require(len(values) == 1, 'missing or duplicate field: ' + name)
        return values[0]

    def target(value, class_name):
        object_id = value.get('object_id', -1)
        require(type(object_id) is int and 0 <= object_id < len(objects), 'invalid reference')
        obj = objects[object_id]
        require(obj['class'] == class_name, 'wrong descriptor class: ' + class_name)
        return obj

    def actions(obj):
        require(field(obj, 'NbExecutions').get('value') == 1, 'registration must execute once')
        return field(obj, 'SubActions')['items']

    def localized(obj, field_name, *parts):
        require(field(obj, field_name).get('value_hex') == authored_text_key(campaign_id, *parts).hex(),
                'localization key mismatch')

    native = {kind: {item for item in reachable if objects[item]['class'] == kind}
              for kind in (register_class, add_class, division_class)}
    if not production['groups']:
        require(not any(native.values()), 'unexpected native reserve content')
        return {'groups': 0, 'divisions': 0, 'deployment_points': 0}
    sides = [side for side in ('nato', 'pact')
             if any(row['side'] == side for row in production['divisions'])]
    version = compiled['adapter'].get('production_ai_version', 1)
    require(version in (1, 2), 'unknown AI production version')
    require(version == 1 or all('ai' in group for group in production['groups']),
            'directed production needs every group AI plan')
    require(len(native[register_class]) == len(sides)
            and len(native[add_class]) == len(production['groups'])
            and len(native[division_class]) == len(production['divisions']), 'native inventory mismatch')
    content = objects[compiled['adapter']['script']['campaign_content']]
    if version == 1:
        container = target(actions(content)[-1], 'TGDDescriptorSequential')
        steps = actions(container)
    else:
        container = target(actions(content)[-1], 'TGDDescriptorSimultaneous')
        branches = actions(container)
        require(len(branches) == len(sides), 'side branch count mismatch')
        registrations = []
        groups_by_id = {}

        def verify_ai_spawn(value, group, point_ids):
            if len(point_ids) > 1:
                branch = target(value, 'TGDDescriptorIfThenElse')
                owner = target(field(branch, 'Condition'), 'TGDConditionPositionInInfluenceMap')
                point_id = point_ids[0]
                point = next(item for item in production['deployment_points'] if item['id'] == point_id)
                marker = target(field(owner, 'Position'), 'TGDTagPosition')
                require([field(marker, 'GUID' + str(i))['value'] for i in range(1, 5)]
                        == list(_int32_words(point['guid'])), 'AI spawn priority marker mismatch')
                alliances = [row for row in owner['properties'] if row['property_name'] == 'Alliance']
                require((len(alliances) == 1 and alliances[0]['value'].get('value') == 1)
                        if group['side'] == 'nato' else not alliances,
                        'AI spawn influence coalition mismatch')
                verify_ai_spawn(field(branch, 'EffetIfTrue'), group, [point_id])
                verify_ai_spawn(field(branch, 'EffetIfFalse'), group, point_ids[1:])
                return
            sequence = target(value, 'TGDDescriptorSequential')
            creates = [target(item, 'TGDDescriptorCreateUnitOnPosition') for item in actions(sequence)]
            require([field(item, 'TypeUnit').get('value') for item in creates]
                    == ['$/GFX/Pawn/' + export for export in group['unit_exports']],
                    'AI spawn battalion order mismatch')
            point = next(item for item in production['deployment_points'] if item['id'] == point_ids[0])
            for create in creates:
                marker = target(field(create, 'Position'), 'TGDTagPosition')
                require([field(marker, 'GUID' + str(i))['value'] for i in range(1, 5)]
                        == list(_int32_words(point['guid'])), 'AI spawn location mismatch')
                require(field(create, 'Camp').get('object_id') ==
                        (284 if group['side'] == 'nato' else 283), 'AI spawn coalition mismatch')

        def verify_ai_schedule(value, group, points):
            if group.get('when'):
                from .choice_conditions import unwrap_action
                value = unwrap_action(graph, value, group['when'])
            sequence = target(value, 'TGDDescriptorSequential')
            scheduled = actions(sequence)
            require(len(scheduled) == 2, 'AI production turn sequence differs')
            wait = target(scheduled[0], 'TGDDescriptorWaitCondition')
            condition = target(field(wait, 'Condition'), 'TGDConditionAnd')
            conditions = field(condition, 'SousConditions')['items']
            require(len(conditions) == 2, 'AI production turn condition differs')
            number = target(conditions[0], 'TGDConditionVariable')
            compare = target(field(number, 'Operator'), 'TGDOperatorIntegerCompare')
            require(field(compare, 'Value').get('value') == group['turn'],
                    'AI production turn mismatch')
            side_turn = target(conditions[1], 'TGDConditionStrategicIsPlayerTurn')
            require(field(side_turn, 'Camp').get('object_id') ==
                    (284 if group['side'] == 'nato' else 283), 'AI production turn coalition mismatch')
            effect = target(scheduled[1], 'TGDDescriptorSequential')
            effect_steps = actions(effect)
            rule=compiled['campaign'].get('capture_deadline')
            if rule and group['division']==rule['division']:
                owner_wait=target(effect_steps[0],'TGDDescriptorWaitCondition')
                status=target(field(owner_wait,'Condition'),'TGDConditionVariable')
                compare=target(field(status,'Operator'),'TGDOperatorIntegerCompare')
                require(field(compare,'Value').get('value')==0
                        and field(compare,'OperatorType',{'value':0}).get('value')==0
                        and field(status,'Variable').get('object_id')==deadline_variable,
                        'Blocked division must wait for an open deadline result')
                effect_steps=effect_steps[1:]
            if group.get('required_flag'):
                require(len(effect_steps) == 3, 'Conditional production must wait before spawning')
                owner_wait = target(effect_steps[0], 'TGDDescriptorWaitCondition')
                owner = target(field(owner_wait, 'Condition'), 'TGDConditionPositionInInfluenceMap')
                flag = next(row for row in compiled['map']['flags'] if row['id'] == group['required_flag'])
                marker = target(field(owner, 'Position'), 'TGDTagPosition')
                require([field(marker, 'GUID'+str(i))['value'] for i in range(1,5)] == list(_int32_words(flag['guid'])), 'Production ownership gate targets another flag')
                effect_steps = effect_steps[1:]
            require(len(effect_steps) == 2, 'AI production must spawn before mission')
            verify_ai_spawn(effect_steps[0], group, points)
            mission = target(effect_steps[1], objects[effect_steps[1]['object_id']]['class'])
            if compiled['adapter'].get('ai_mission_version',1) >= 3 and mission['class']=='TGDDescriptorIfThenElse':
                local = target(field(mission,'Condition'),'TGDConditionCutSceneIsCampControllableByLocalPlayer')
                require(field(local,'Camp')['object_id']==(284 if group['side']=='nato' else 283),'AI mission human gate owns the wrong coalition')
                value=field(mission,'EffetIfFalse')
                mission=target(value,objects[value['object_id']]['class'])
            if group.get('member_ai'):
                require(mission['class'] == 'TGDDescriptorSimultaneous'
                        and len(actions(mission)) == len(group['battalions']),
                        'AI production must issue one mission per member')
            else:
                require(mission['class'] in {'TGDDescriptorSimultaneous','TGDDescriptorSequential', 'TGDDescriptorStrategicDefend',
                                             'TGDDescriptorStrategicMoveAndAttack'},
                        'AI production mission class differs')

        for branch_value, side in zip(branches, sides):
            branch = target(branch_value, 'TGDDescriptorIfThenElse')
            local = target(field(branch, 'Condition'),
                           'TGDConditionCutSceneIsCampControllableByLocalPlayer')
            require(field(local, 'Camp').get('object_id') == (284 if side == 'nato' else 283),
                    'human/AI production side selection mismatch')
            human = target(field(branch, 'EffetIfTrue'), 'TGDDescriptorSequential')
            human_actions = actions(human)
            expected_groups = [group for group in production['groups'] if group['side'] == side]
            require(len(human_actions) == len(expected_groups) + 1,
                    'human production side inventory mismatch')
            registrations.append(human_actions[0])
            for action, group in zip(human_actions[1:], expected_groups):
                if group.get('when'):
                    from .choice_conditions import unwrap_action
                    action = unwrap_action(graph, action, group['when'])
                rule=compiled['campaign'].get('capture_deadline')
                if rule and group['division']==rule['division']:
                    delayed=target(action,'TGDDescriptorSequential')
                    wait,gate=actions(delayed)
                    condition=target(field(target(wait,'TGDDescriptorWaitCondition'),'Condition'),'TGDConditionAnd')
                    number,side_turn=field(condition,'SousConditions')['items']
                    number=target(number,'TGDConditionVariable')
                    timing=target(field(number,'Operator'),'TGDOperatorIntegerCompare')
                    require(field(number,'Variable').get('object_id')==381
                            and field(timing,'Value').get('value')==rule['before_turn']
                            and field(timing,'OperatorType',{'value':0}).get('value')==0
                            and field(target(side_turn,'TGDConditionStrategicIsPlayerTurn'),'Camp').get('object_id')
                            ==(284 if group['side']=='nato' else 283),
                            'Human division registration must wait for the deadline turn')
                    gate=target(gate,'TGDDescriptorIfThenElse')
                    status=target(field(gate,'Condition'),'TGDConditionVariable')
                    compare=target(field(status,'Operator'),'TGDOperatorIntegerCompare')
                    require(field(compare,'Value').get('value')==0
                            and field(compare,'OperatorType',{'value':0}).get('value')==0
                            and field(status,'Variable').get('object_id')==deadline_variable,
                            'Human division registration must obey the capture deadline')
                    idle=target(field(gate,'EffetIfFalse'),'TGDDescriptorWaitDuration')
                    require(field(idle,'Duree').get('value')==0,'Blocked human division must register no cards')
                    action=field(gate,'EffetIfTrue')
                groups_by_id[group['id']] = action
            ai = target(field(branch, 'EffetIfFalse'), 'TGDDescriptorSimultaneous')
            ai_actions = actions(ai)
            require(len(ai_actions) == len(expected_groups), 'AI production schedule count mismatch')
            for action, group in zip(ai_actions, expected_groups):
                division = next(row for row in production['divisions']
                                if row['id'] == group['division'])
                verify_ai_schedule(action, group, division['deployment_points'])
        require(set(groups_by_id) == {group['id'] for group in production['groups']},
                'human production group mapping differs')
        steps = registrations + [groups_by_id[group['id']] for group in production['groups']]
    require(len(steps) == len(sides) + len(production['groups']), 'registration action count mismatch')
    division_ids = {}
    turn_ids = set()
    pawn_exports = []
    for value, group in zip(steps[len(sides):], production['groups']):
        action = target(value, add_class)
        require(field(action, 'Camp').get('object_id') == (284 if group['side'] == 'nato' else 283),
                'regiment coalition mismatch')
        localized(action, 'DisplayName', 'regiment', group['id'])
        actual = [item.get('value') for item in field(action, 'Pawns')['items']]
        expected = ['$/GFX/Pawn/' + export for export in group['unit_exports']]
        require(actual == expected, 'regiment battalion membership mismatch')
        pawn_exports.extend(actual)
        turn = target(field(action, 'UnlockAtTurnVariable'), 'TGDVariableInteger')
        require(field(turn, 'Value').get('value') == group['turn'], 'unlock turn mismatch')
        require(turn['id'] not in turn_ids, 'regiments share a mutable unlock variable')
        turn_ids.add(turn['id'])
        division = target(field(action, 'ReinforcementGroup'), division_class)
        previous = division_ids.setdefault(group['division'], division['id'])
        require(previous == division['id'], 'regiments disagree on division identity')
    require(len(set(division_ids.values())) == len(production['divisions']), 'division identity alias')
    require(len(pawn_exports) == len(set(pawn_exports)), 'mutable battalion alias')
    points = {row['id']: row for row in production['deployment_points']}
    for row in production['divisions']:
        division = objects[division_ids[row['id']]]
        localized(division, 'DisplayName', 'division', row['id'], 'name')
        localized(division, 'ShortDisplayName', 'division', row['id'], 'short_name')
        positions = field(division, 'SpawnPositionsSortedByPriority')['items']
        require(len(positions) == len(row['deployment_points']), 'deployment point count mismatch')
        for position_ref, point_id in zip(positions, row['deployment_points']):
            tag = target(position_ref, 'TGDTagPosition')
            point = points[point_id]
            path = '$/GDScript/GdItems/Tags/' + point['adapter_slot']['name']
            require(graph['exports'].get(tag['id']) == path, 'deployment point priority or tag mismatch')
            require([field(tag, 'GUID' + str(index))['value'] for index in range(1, 5)]
                    == list(_int32_words(point['guid'])), 'deployment point GUID mismatch')
    for value, side in zip(steps, sides):
        action = target(value, register_class)
        require(field(action, 'Camp').get('object_id') == (284 if side == 'nato' else 283),
                'point registration coalition mismatch')
        expected = [division_ids[row['id']] for row in production['divisions'] if row['side'] == side]
        actual = [target(item, division_class)['id'] for item in field(action, 'ReinforcementGroups')['items']]
        require(actual == expected, 'coalition division registry mismatch')
    require({item['object_id'] for item in steps} == native[register_class] | native[add_class],
            'duplicate registration scheduling')

    def references(value):
        if isinstance(value, dict):
            if 'object_id' in value:
                yield value['object_id']
            for nested in value.values():
                yield from references(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from references(nested)

    incoming = {}
    for item in reachable:
        for reference in references(objects[item]['properties']):
            incoming[reference] = incoming.get(reference, 0) + 1
        if version == 1 and objects[item]['class'] == 'TGDDescriptorCreateUnitOnPosition':
            require(field(objects[item], 'TypeUnit').get('value') not in pawn_exports,
                    'reserve battalion also has a direct spawn')
    require(all(incoming.get(item) == 1 for item in
                native[register_class] | native[add_class] | turn_ids | {container['id']}),
            'repeated registration or mutable unlock alias')
    return {'groups': len(production['groups']), 'divisions': len(production['divisions']),
            'deployment_points': len(points),
            **({'ai_directed_groups': len(production['groups'])} if version == 2 else {})}


def bind_production_divisions(production, battalions):
    from .modgen import _ui_text

    divisions = {row['id']: row for row in production['divisions']}

    def token(identity, kind):
        return 'AG' + hashlib.sha256((identity + ':' + kind).encode()).hexdigest()[:8].upper()

    for group in production['groups']:
        division = divisions[group['division']]
        if not _ui_text(division['name']['ru']) or not _ui_text(group['name']['ru']):
            raise ValueError('Production division and regiment names must fit 30 UTF-16 units')
        identity = 'AGF_' + division['identity']
        name_token = token(identity, 'division')
        command = {'export': identity + '_Command', 'name': division['name']['ru'],
                   'name_token': name_token, 'superior': None, 'texture': 'UIBackgroundTexture_division'}
        regiment_id = 'AGF_' + group['identity']
        organization = {'export': regiment_id + '_Subordination', 'name': group['name']['ru'],
                        'name_token': token(regiment_id, 'regiment'), 'superior': command['export'],
                        'texture': 'UIBackgroundTexture_regiment'}
        definition = {'id': identity, 'name': division['name']['ru'], 'name_token': name_token,
                      'coalition': group['side'].upper(),
                      'emblem': ('Texture_Division_Emblem_RFA_TerrKdo_Sud' if group['side'] == 'nato'
                                 else 'Texture_Division_Emblem_RDA_KDA_Erfurt')}
        for member in group['battalions']:
            if 'oob' not in battalions[member]:
                raise ValueError('Native production requires fully authored battalions')
            oob = battalions[member]['oob']
            if oob.get('formation'):
                # The scheduling card does not change a unit's actual command
                # hierarchy, division emblem or regiment affiliation.
                continue
            oob['division'] = 'Descriptor_Deck_Division_' + identity
            oob['division_definition'] = copy.deepcopy(definition)
            oob['organization'] = copy.deepcopy(organization)
            oob['command'] = copy.deepcopy(command)
