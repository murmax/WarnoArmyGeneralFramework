"""Release guard for the recovered WARNO 201602 battleground restriction."""

from .campaign_identity import campaign_identity


AUTHORIZED_SCENARIO = 'CampagneStrat_Airborne'
AUTHORIZED_CENTER = (25, 17)
AUTHORIZED_RADIUS = 2


def specific_battleground_authorized(scenario, cell):
    """Evaluate native authorization in engine tile coordinates, not world units."""
    if (not isinstance(scenario, str) or not isinstance(cell, (tuple, list))
            or len(cell) != 2 or any(type(value) is not int for value in cell)):
        raise ValueError('Expected a scenario name and two integer engine tile coordinates')
    distance_squared = sum((value - center) ** 2
                           for value, center in zip(cell, AUTHORIZED_CENTER))
    return scenario == AUTHORIZED_SCENARIO and distance_squared <= AUTHORIZED_RADIUS ** 2


def validate_authored_battleground_policy(compiled):
    """Reject the known-invalid private-campaign marker strategy before release."""
    strategic_map = compiled.get('adapter', {}).get('strategic_map')
    if strategic_map is None:
        return
    scenario = campaign_identity(compiled)['scenario']
    policy = strategic_map.get('tactical_policy')
    if policy == 'terrain_pool':
        from .map_registration import campaign_map_items
        if any(row['kind'] == 'battleground' for row in campaign_map_items(compiled)):
            raise ValueError('terrain_pool tactical policy generated specific battleground markers')
        return
    if policy not in ('specific', None):
        raise ValueError('strategic map tactical policy must be terrain_pool or specific')
    if scenario != AUTHORIZED_SCENARIO:
        raise ValueError(
            'SpecificStrategicBattleground is not authorized for independent scenario '
            + scenario + '; WARNO 201602 restricts it to CampagneStrat_Airborne '
            'within two engine tiles of (25, 17). A verified alternative tactical-map '
            'policy is required; adding GDScript exports does not remove this restriction.')
