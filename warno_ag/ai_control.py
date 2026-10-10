"""Choose stock strategic control or an explicit campaign exception."""
def mission_cooperates(compiled, side):
    policy = compiled['campaign'].get('ai_policy', {})
    return policy.get('cooperate_by_side', {}).get(side, policy.get('cooperate', False))


def native_controlled(compiled,side,members):
    policy=compiled['campaign'].get('ai_policy',{})
    return (side in policy.get('native_controller_sides',[]) and
            not any(member in policy.get('scripted_exceptions',[]) for member in members))
