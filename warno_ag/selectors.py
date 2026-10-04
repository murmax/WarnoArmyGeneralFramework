"""Typed CNDF paths from named exports; never accept raw object ids as selectors."""


def property_named(obj, name):
    found = [p for p in obj['properties'] if p['property_name'] == name]
    if len(found) != 1:
        raise ValueError('Native path property is missing or ambiguous')
    return found[0]['value']


def native_target(graph, operation):
    matches = [key for key, path in graph['exports'].items() if path == operation['export']]
    if len(matches) != 1:
        raise ValueError('Module export selector is not unique')
    obj = graph['objects'][matches[0]]
    if 'traverse' in operation:
        steps = operation['traverse']
        if not isinstance(steps, list) or not 1 <= len(steps) <= 32:
            raise ValueError('Native path requires 1..32 steps')
        if obj['class'] != operation['root_class']:
            raise ValueError('Native root class precondition failed')
        for step in steps:
            if not isinstance(step, dict) or set(step) not in (
                    {'property', 'class'}, {'property', 'class', 'index'}):
                raise ValueError('Unknown or missing native path step fields')
            value = property_named(obj, step['property'])
            if 'index' in step:
                index = step['index']
                # CNDF list (17), not a map or arbitrary nested Python value.
                if value['type_id'] != 17 or type(index) is not int or not 0 <= index < len(value['items']):
                    raise ValueError('Native path list/index precondition failed')
                value = value['items'][index]
            if value['type_id'] != 0xbbbbbbbb:
                raise ValueError('Native path must follow a local object reference')
            obj = graph['objects'][value['object_id']]
            if obj['class'] != step['class']:
                raise ValueError('Native path class precondition failed')
    if obj['class'] != operation['class']:
        raise ValueError('Module class precondition failed')
    return obj
