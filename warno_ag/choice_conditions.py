"""Persistent event decisions used by later events and reinforcement cards."""
import copy

# Installed native IntegerCompare compares configured Value to the input:
# enum 5 is Value > input, i.e. input < Value. Enum 2 is input >= Value.
# Evidence: WARNO executor RVA 0x60e3c0, jump table RVA 0x22c0f00.
COMPARE_EQUAL = 0
COMPARE_INPUT_LESS = 5
CHOICE_COUNT = 2
CHOICE_PENDING = 99

def choice_export(event_id):
    return '$/GDScript/CampaignChoices/' + event_id


def validate_requirements(value, where):
    if not isinstance(value, list) or not value:
        raise ValueError(where + ' must be a nonempty list of event/choice requirements')
    seen = set()
    for row in value:
        if (not isinstance(row, dict) or set(row) != {'event', 'choice'}
                or not isinstance(row['event'], str) or not row['event']
                or type(row['choice']) is not int or row['choice'] not in (0, 1)
                or row['event'] in seen):
            raise ValueError(where + ' requires distinct event IDs and choice 0 or 1')
        seen.add(row['event'])
    return copy.deepcopy(value)


def bind_requirements(production, events):
    lookup = {event['id']: event for event in events}
    consumers = {}
    for row in [*production['groups'], *events]:
        requirements = row.get('when', row.get('trigger', {}).get('when', []))
        for requirement in requirements:
            source = lookup.get(requirement['event'])
            if source is None or len(source['choices']) != 2:
                raise ValueError('Decision condition refers to a missing two-choice event: ' + requirement['event'])
            # Same-turn decisions may be awaited; later decisions must not be
            # used to register already-overdue reinforcements or notifications.
            source_turn = source['trigger'].get('turn')
            consumer_turn = row.get('turn', row.get('trigger', {}).get('turn'))
            if source_turn is None or consumer_turn is None or source_turn > consumer_turn:
                raise ValueError('Decision condition needs a preceding dated decision')
            consumers.setdefault(requirement['event'], set()).add(requirement['choice'])
    # Decision cycles would strand native WaitCondition sequences forever.
    def visit(event_id, visiting):
        if event_id in visiting:
            raise ValueError('Cyclic event decision dependency: ' + event_id)
        for row in lookup[event_id]['trigger'].get('when', []):
            visit(row['event'], visiting | {event_id})
    for event_id in consumers:
        visit(event_id, set())
    return consumers


def verify_condition(graph, value, requirements, *, ready=False):
    """Read back every variable/compare link in an authored decision gate."""
    objects = graph['objects']
    def prop(obj, name):
        values = [p['value'] for p in obj['properties'] if p['property_name'] == name]
        if len(values) != 1:
            raise ValueError('Decision condition lacks unique property ' + name)
        return values[0]
    def obj(ref, kind):
        result = objects[ref['object_id']]
        if result['class'] != kind:
            raise ValueError('Decision gate class differs: ' + kind)
        return result
    gate = obj(value, 'TGDConditionAnd')
    parts = prop(gate, 'SousConditions')['items']
    if len(parts) != len(requirements):
        raise ValueError('Decision gate requirement count differs')
    for part, requirement in zip(parts, requirements):
        condition = obj(part, 'TGDConditionVariable')
        variable = obj(prop(condition, 'Variable'), 'TGDVariableInteger')
        if (graph['exports'].get(variable['id']) != choice_export(requirement['event'])
                or not variable['is_top_object']):
            raise ValueError('Decision gate reads another event state')
        compare = obj(prop(condition, 'Operator'), 'TGDOperatorIntegerCompare')
        if (prop(compare, 'OperatorType')['value'] != (COMPARE_INPUT_LESS if ready else COMPARE_EQUAL)
                or prop(compare, 'Value')['value'] != (CHOICE_COUNT if ready else requirement['choice'])):
            raise ValueError('Decision gate comparison differs')


def unwrap_action(graph, value, requirements):
    """Verify wait-for-decision, matched branch, and zero-effect skipped branch."""
    objects = graph['objects']
    def prop(obj, name):
        return next(p['value'] for p in obj['properties'] if p['property_name'] == name)
    sequence = objects[value['object_id']]
    if sequence['class'] != 'TGDDescriptorSequential':
        raise ValueError('Decision-gated action must be sequential')
    actions = prop(sequence, 'SubActions')['items']
    if len(actions) != 2:
        raise ValueError('Decision gate must wait before selecting')
    wait, branch = [objects[a['object_id']] for a in actions]
    if wait['class'] != 'TGDDescriptorWaitCondition' or branch['class'] != 'TGDDescriptorIfThenElse':
        raise ValueError('Decision gate scheduling differs')
    verify_condition(graph, prop(wait, 'Condition'), requirements, ready=True)
    verify_condition(graph, prop(branch, 'Condition'), requirements)
    skipped = objects[prop(branch, 'EffetIfFalse')['object_id']]
    if skipped['class'] != 'TGDDescriptorWaitDuration' or prop(skipped, 'Duree')['value'] != 0:
        raise ValueError('An unselected reinforcement must have no effects')
    return prop(branch, 'EffetIfTrue')
