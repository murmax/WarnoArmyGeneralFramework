"""Choose stock strategic control or an explicit campaign exception."""
def native_controlled(compiled,side,members):
    policy=compiled['campaign'].get('ai_policy',{})
    return (side in policy.get('native_controller_sides',[]) and
            not any(member in policy.get('scripted_exceptions',[]) for member in members))
