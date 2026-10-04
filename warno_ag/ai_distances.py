"""Convert native strategic AP-cell radii to GRU descriptor integers."""
from functools import lru_cache
import math

FIELDS={'attack_radius_cells','transit_radius_cells','support_radius_cells','waypoint_radius_cells'}


@lru_cache(maxsize=1)
def native_conversion():
    from .game_resources import GameResources
    from .current_campaign import GAME_DATA
    from .cndf import decode
    from .storage import sha256
    raw=GameResources(GAME_DATA.parents[1]).definitions().read('NDF/InitialisationGameDistanceUnits.ndfbin')
    _,graph=decode(raw)
    units=[o for o in graph['objects'] if o['class']=='TInitialisationGameDistanceUnits']
    if len(units)!=1:raise ValueError('Missing native distance conversion')
    values=[p['value']['value'] for p in units[0]['properties'] if p['property_name']=='LBUToGRUConversionFactor']
    if len(values)!=1 or not math.isfinite(values[0]) or values[0]<=0:
        raise ValueError('Invalid native LBU/GRU conversion')
    return values[0],sha256(raw)


def compile_distance_units(compiled):
    from .strategic_map_package import NATIVE_ACTION_POINT_STEP
    from .world_source import GAME_UNITS_PER_LBU
    factor,digest=native_conversion()
    return {'format':'agf-ai-distance-units/v1','native_cell_gu':NATIVE_ACTION_POINT_STEP,
            'gu_per_lbu':GAME_UNITS_PER_LBU,'lbu_to_gru':factor,
            'native_cell_gru':NATIVE_ACTION_POINT_STEP/GAME_UNITS_PER_LBU*factor,
            'source_sha256':digest}


def mission_radii(compiled,*,defensive,target,final_target,support=False):
    policy=compiled['campaign']['ai_policy']
    if 'attack_radius_cells' not in policy:
        return policy['attack_radius'],707
    units=compiled['adapter']['ai_distance_units']
    if units!=compile_distance_units(compiled):
        raise ValueError('Native AI distance conversion differs from compiled provenance')
    if support:cells=policy['support_radius_cells']
    elif (not defensive and target!=final_target and target in policy.get('transit_waypoints',[])):
        cells=policy['transit_radius_cells']
    else:cells=policy['attack_radius_cells']
    convert=lambda value:max(1,round(value*units['native_cell_gru']))
    return convert(cells),convert(policy['waypoint_radius_cells'])
