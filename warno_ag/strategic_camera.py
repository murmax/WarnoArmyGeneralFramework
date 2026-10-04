"""Retarget stock camera path names to an independent authored map.

The inherited scenario graph still addresses these paths by name. Keeping
their names and changing only float32 coordinates lets the stock camera code
focus on authored formations instead of the old Bruderkrieg geography.
"""
import math

from .cndf import decode, rebuild_objects


def retarget_camera_paths(raw, compiled):
    document, graph = decode(raw)
    objects = graph['objects']
    positions = {row['side']: row['position'] for row in reversed(compiled['deployments'])}
    if set(positions) != {'nato', 'pact'}:
        raise ValueError('An authored strategic camera needs both starting sides')
    nato = positions['nato']
    pact = positions['pact']
    objectives = [row['position'] for row in compiled['map']['flags']]
    if not objectives:
        raise ValueError('An authored strategic camera needs at least one objective')
    default = objectives[1] if len(objectives) > 1 else pact
    bounds = compiled['adapter']['strategic_map']['bounds']
    overview = compiled.get('cinematics', {}).get('start_camera')
    overview_focus = (next(row['position'] for row in compiled['map']['flags']
                           if row['id'] == overview['focus']) if overview else None)
    count = 0
    for path in objects:
        if path['class'] != 'TCameraPath':
            continue
        properties = {item['property_name']: item['value'] for item in path['properties']}
        name = properties['Name']['value'].lower()
        is_overview = overview is not None and ('intro' in name or name == 'camera' or name.startswith('main_'))
        if is_overview:
            focus = overview_focus
        elif 'otan' in name or 'nato' in name or name == 'main_otan':
            focus = nato
        elif 'pact' in name or 'pacte' in name:
            focus = pact
        elif 'event_1' in name:
            focus = objectives[min(1,len(objectives)-1)]
        elif 'event_2' in name:
            focus = objectives[min(2,len(objectives)-1)]
        elif 'event_3' in name:
            focus = objectives[min(3,len(objectives)-1)]
        else:
            focus = default
        positions_ref = properties['PositionKeyVector']['items']
        directions_ref = properties['DirectionKeyVector']['items']
        if len(positions_ref) != len(directions_ref) or not positions_ref:
            raise ValueError('Unexpected strategic camera path key inventory')
        for index, (position_ref, direction_ref) in enumerate(zip(positions_ref,directions_ref)):
            altitude = float(overview['altitude']) if is_overview else (
                320000.0 if len(positions_ref) > 1 and index == 0 else 195000.0)
            # Keep an oblique WARNO-style view while looking at the chosen land
            # position. Stock cameras are also high above native strategic maps.
            north_up=compiled.get('cinematics',{}).get('start_camera',{}).get('north_up',False)
            x = max(bounds[0],min(bounds[2], focus[0] if north_up else focus[0]-altitude*.27))
            y = max(bounds[1],min(bounds[3], focus[1]+altitude*(-.4 if north_up else .24)))
            z = altitude
            dx,dy,dz = focus[0]-x,focus[1]-y,-z
            length = math.sqrt(dx*dx+dy*dy+dz*dz)
            for ref, vector in ((position_ref,[x,y,z]),
                                (direction_ref,[dx/length,dy/length,dz/length])):
                child = objects[ref['object_id']]
                if child['class'] != 'TCameraPathKey':
                    raise ValueError('Unexpected strategic camera path key class')
                coord = next(item['value'] for item in child['properties']
                             if item['property_name'] == 'Coord')
                coord['value'] = vector
        count += 1
    result = rebuild_objects(document, graph)
    _, check = decode(result)
    if count == 0 or len(check['objects']) != len(objects):
        raise ValueError('Authored camera paths did not survive binary readback')
    return result
