"""Separate reachable authored gameplay from retained adapter dependencies."""


def prototype_dependency_contract(graph, compiled):
    from .bruderkrieg import _reachable_objects
    reachable = _reachable_objects(graph, compiled['adapter']['script']['root'])
    authored = {'$/GFX/Pawn/' + row['unit_export'] for row in compiled['battalions']}

    def imports(value):
        if isinstance(value, dict):
            if value.get('type') == 'trans_ref':
                yield value['value']
            for nested in value.values():
                yield from imports(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from imports(nested)

    live = set()
    for object_id in reachable:
        live.update(imports(graph['objects'][object_id]['properties']))
    prototype = sorted(path for path in live if path.startswith('$/GFX/Pawn/') and path not in authored)
    if prototype:
        raise ValueError('Reachable prototype Pawn dependency: ' + prototype[0])
    dormant = sorted(path for path in graph['imports'].values()
                     if path.startswith('$/GFX/Pawn/') and path not in authored and path not in live)
    explicit = [row for row in compiled['battalions']
                if 'oob' in row and 'strategic' in row['oob'] and 'division_definition' in row['oob']]
    return {
        'reachable_objects': len(reachable),
        'dormant_objects': len(graph['objects']) - len(reachable),
        'reachable_prototype_pawns': prototype,
        'dormant_prototype_pawn_imports': dormant,
        'reachable_shared_imports': sorted(live - authored),
        'explicit_battalions': len(explicit),
        'catalog_compatibility_battalions': len(compiled['battalions']) - len(explicit),
        'retained_geographic_tags': sum(obj['class'].startswith('TGDTag') for obj in graph['objects']),
        'runtime_verified': False,
    }
