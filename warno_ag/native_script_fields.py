"""Bounded, inspectable scalar properties of stock strategic scripts."""
import math


# Native classes outside this list remain visible in the advanced graph browser.
# Each binding is checked against the captured class, property, type and value.
DIRECT_FIELDS = {
    'TGDDescriptorSetFatigueToPawn': {'Fatigue': ('int32', 0, 8)},
    'TGDDescriptorAddCasualtiesToPawn': {
        'Casualties': ('int32', 0, 10000),
        'RandomRange': ('int32', 0, 1000)},
    'TGDDescriptorIAStrategicScripted': {'Strategy': ('int32', 1, 2)},
    'TGDDescriptorStrategicMoveAndAttack': {
        'Blocking': ('bool', None, None),
        'AttackEnemyInRadius': ('int32', 0, 100000),
        'ExecuteOnlyOnIAActivated': ('bool', None, None),
        'UseOnlyUnitInMissionToAttack': ('bool', None, None),
        'WaypointReachedRadius': ('int32', 1, 100000)},
    'TGDDescriptorStrategicDefend': {
        'Blocking': ('bool', None, None),
        'AttackEnemyInRadius': ('int32', 0, 100000),
        'ExecuteOnlyOnIAActivated': ('bool', None, None),
        'UseOnlyUnitInMissionToAttack': ('bool', None, None),
        'WaypointReachedRadius': ('int32', 1, 100000)},
    'TGDDescriptorGereObjectifWithVariableOwner': {
        'BonusScoreIncomeMission': ('int32', 0, 10000),
        'BonusScoreMission': ('int32', 0, 10000),
        'ShowEtiquette': ('bool', None, None)},
    'TGDDescriptorGereObjectif': {'BonusScoreMission': ('int32', 0, 10000)},
    'TGDDescriptorCutsceneDialog': {
        'DureePause': ('float32', -1, 120),
        'CanBeSkippedWithEscape': ('bool', None, None)},
    'TGDDescriptorCutsceneDialogWithMultipleChoice': {
        'DureePause': ('float32', -1, 120),
        'Pause': ('bool', None, None)},
    'TGDDescriptorEncapsuleCutscene': {'BlockPlayerActions': ('bool', None, None)},
    'TGDDescriptorWaitDuration': {'Duree': ('float32', 0, 3600)},
    'TGDDescriptorCreateUnitOnPosition': {'NbUnit': ('int32', 1, 100)},
}

VARIABLE_FIELDS = {'TGDVariableInteger': 'int32', 'TGDVariableFloat': 'float32',
                   'TGDVariableBoolean': 'bool'}

# These forms verify the selected source node and its links before accepting an
# edit. A class appearing here does not make every instance of it editable.
QUALIFIED_WORKFLOWS = {
    'TGDDescriptorStrategicMoveAndAttack': ('ai_target', 'startup_ai_order'),
    'TGDDescriptorStrategicDefend': ('ai_target', 'startup_ai_order'),
    'TGDDescriptorCutsceneTextComponent': ('event_text', 'turn_dialog'),
    'TGDDescriptorCutsceneDialogWithMultipleChoice': ('existing_choice_caption',),
    'TGDDescriptorStrategicAddPossibleProduction': ('production_members', 'production_group'),
    'TGDStrategicReinforcementGroup': ('spawn_priority', 'reinforcement_division'),
    'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction': ('spawn_priority',),
    'TGDTagPosition': ('map_target_or_marker',),
}


def editable_fields(obj):
    bindings = DIRECT_FIELDS.get(obj['class'], {})
    if obj['class'] in VARIABLE_FIELDS:
        bindings = {'Value': (VARIABLE_FIELDS[obj['class']], None, None)}
    return [name for name, (kind, _, _) in bindings.items()
            if any(prop['property_name'] == name and prop['value']['type'] == kind
                   for prop in obj['properties'])]


def native_capability_inventory(graph, scenario, script_sha256):
    """Versioned, source-specific account of visible versus editable classes."""
    from .native_ai_creation import AI_CREATION_ADAPTERS
    from .native_frozen import INITIAL_READINESS_SOURCES, SOURCE_ADAPTERS
    from .native_turn_events import TURN_EVENT_ADAPTERS

    def pinned(adapters):
        spec = adapters.get(scenario)
        return spec is not None and spec['sha256'] == script_sha256

    grouped = {}
    for obj in graph['objects']:
        name = obj['class']
        row = grouped.setdefault(name, {'class': name, 'count': 0,
                                        'direct_editable_nodes': 0, 'direct_fields': set()})
        row['count'] += 1
        fields = editable_fields(obj)
        if fields:
            row['direct_editable_nodes'] += 1
            row['direct_fields'].update(fields)
    classes = []
    for name, row in sorted(grouped.items()):
        hints = list(QUALIFIED_WORKFLOWS.get(name, ()))
        classes.append({'class': name, 'count': row['count'],
                        'direct_editable_nodes': row['direct_editable_nodes'],
                        'direct_fields': sorted(row['direct_fields']),
                        'qualified_workflows': hints,
                        'mode': ('bounded_fields' if row['direct_editable_nodes']
                                 else 'qualified_workflow' if hints else 'preserved_only')})
    frozen = pinned(SOURCE_ADAPTERS)
    return {'format': 'agf-native-capabilities/v1', 'scenario': scenario,
            'script_sha256': script_sha256,
            'classes': classes,
            'source_adapters': {
                'startup_ai_order': pinned(AI_CREATION_ADAPTERS),
                'turn_dialog': pinned(TURN_EVENT_ADAPTERS),
                'frozen_new_deployment': frozen,
                'initial_readiness': frozen and scenario in INITIAL_READINESS_SOURCES,
            },
            'qualified_workflows_require_per_node_verification': True,
            'runtime_verified': False}


def validate_script_field(obj, name, after):
    bindings = DIRECT_FIELDS.get(obj['class'], {})
    if obj['class'] in VARIABLE_FIELDS:
        bindings = {'Value': (VARIABLE_FIELDS[obj['class']], None, None)}
    if name not in bindings:
        raise ValueError('Native script property has no bounded editor binding')
    kind, minimum, maximum = bindings[name]
    props = [prop for prop in obj['properties'] if prop['property_name'] == name]
    if len(props) != 1 or props[0]['value']['type'] != kind:
        raise ValueError('Native script property type differs from the verified binding')
    if kind == 'bool':
        valid = type(after) is bool
    elif kind == 'float32':
        valid = type(after) in (int, float) and math.isfinite(after) and abs(after) <= 3.4028235e38
    else:
        valid = type(after) is int and -(1 << 31) <= after < (1 << 31)
    if valid and minimum is not None:
        valid = minimum <= after <= maximum
    if not valid:
        raise ValueError('Native script property value is outside the verified bounds')
    return props[0]['value']
