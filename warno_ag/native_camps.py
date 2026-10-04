"""Derive coalition-to-Camp indices from the captured source scenario."""
import re


def source_camp_by_side(projection, baseline, bindings):
    names = {row['id']: row['export'] for row in bindings
             if row['kind'] == 'placement' and row.get('export')}
    placements = {}
    for row in projection['placements']:
        placements.setdefault(row['name'], []).append(row)
    camps = {'nato': set(), 'pact': set()}
    for deployment in baseline['campaign']['deployments']:
        name = names.get(deployment['id'])
        source = placements.get(name, [])
        if len(source) != 1:
            raise ValueError('Native deployment has no unique source map camp: ' + deployment['id'])
        ranking = source[0]['ranking']
        if re.fullmatch(r'Camp_[01]', ranking) is None:
            raise ValueError('Native source spawn ranking is not a coalition camp')
        side = deployment['side']
        if side not in camps:
            raise ValueError('Native deployment has an unsupported coalition side')
        camps[side].add(int(ranking[-1]))
    if any(len(values) != 1 for values in camps.values()):
        raise ValueError('Native source has no unique camp index for each coalition')
    result = {side: next(iter(values)) for side, values in camps.items()}
    if set(result.values()) != {0, 1}:
        raise ValueError('Native source maps both coalitions to one camp index')
    return result
