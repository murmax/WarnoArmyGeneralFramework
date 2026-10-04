"""Bound native ticket-valued startup casualties using the authored roster."""
from functools import lru_cache
from pathlib import Path
import re


def bounded_loss_budget(costs, max_percent):
    if (type(max_percent) is not int or not 0 <= max_percent < 100
            or not costs or any(type(cost) is not int or cost < 0 for cost in costs)):
        raise ValueError('Invalid initial_losses percentage or ticket costs')
    if max_percent == 0:
        return 0
    limit = len(costs) * max_percent // 100
    budget = sum(sorted(costs)[:limit])
    if not budget:
        raise ValueError('Positive initial_losses bound is not representable by native ticket budget')
    return budget


@lru_cache(maxsize=1)
def unit_ticket_costs():
    source = Path(__file__).resolve().parents[1] / 'artifacts/modgen-201602-template/GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf'
    text = source.read_text(encoding='utf-8')
    result = {}
    for match in re.finditer(r'(?ms)^export (Descriptor_Unit_\w+) is TEntityDescriptor\s*\(.*?(?=^export |\Z)', text):
        prices = re.findall(r'Resource_Tickets,\s*(\d+)', match[0])
        if len(prices) > 1 or 'TProductionModuleDescriptor' not in match[0]:
            raise ValueError('Ambiguous initial_losses ticket cost: ' + match[1])
        result['$/GFX/Unit/' + match[1]] = int(prices[0]) if prices else 0
    if not result:
        raise ValueError('Missing initial_losses ticket catalog')
    return result


def roster_ticket_costs(oob):
    costs, catalog = [], unit_ticket_costs()
    for company in oob['companies']:
        for platoon in company['platoons']:
            for pack in platoon['packs']:
                signature = pack['signature']
                try:
                    cost = sum(catalog[signature[field]] for field in ('unit', 'transport')
                               if signature[field])
                except KeyError as exc:
                    raise ValueError('Unknown initial_losses ticket cost: ' + str(exc)) from exc
                costs.extend([cost] * (pack['count'] * signature['number']))
    return costs


def loss_severity(costs, budget):
    if not costs or budget < 0:
        raise ValueError('Invalid initial_losses severity inputs')
    counts = []
    for ordered in (sorted(costs, reverse=True), sorted(costs)):
        remaining, count = budget, 0
        for cost in ordered:
            if remaining <= 0:
                break
            remaining -= cost
            count += 1
        counts.append(count)
    return {'slots': len(costs), 'tickets': sum(costs),
            'minimum_destroyed': counts[0], 'maximum_destroyed': counts[1]}
