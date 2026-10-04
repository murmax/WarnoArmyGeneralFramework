"""Read source reinforcement-group spawn-point pools without changing them."""


def production_position_pool(graph):
    objects = graph['objects']
    exports = graph['exports']
    group_sides = {}
    for action in objects:
        if action['class'] != 'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction':
            continue
        props = {prop['property_name']: prop['value'] for prop in action['properties']}
        camp = props.get('Camp')
        groups = props.get('ReinforcementGroups')
        if (camp is None or camp['type'] != 'obj_ref'
                or groups is None or groups['type'] != 'list'):
            continue
        side = exports.get(camp['object_id'], '').rsplit('/', 1)[-1].lower()
        if side not in {'nato', 'pact'}:
            continue
        for item in groups['items']:
            index = item.get('object_id') if item.get('type') == 'obj_ref' else None
            if (index is not None and 0 <= index < len(objects)
                    and objects[index]['class'] == 'TGDStrategicReinforcementGroup'):
                group_sides.setdefault(index, set()).add(side)
    pool = {'nato': set(), 'pact': set()}
    for index, sides in group_sides.items():
        if len(sides) != 1:
            continue
        group = objects[index]
        positions = [prop['value'] for prop in group['properties']
                     if prop['property_name'] == 'SpawnPositionsSortedByPriority']
        if len(positions) != 1 or positions[0]['type'] != 'list':
            continue
        for item in positions[0]['items']:
            target = item.get('object_id') if item.get('type') == 'obj_ref' else None
            if (target is not None and 0 <= target < len(objects)
                    and objects[target]['class'] == 'TGDTagPosition'):
                pool[next(iter(sides))].add(target)
    return group_sides, pool
