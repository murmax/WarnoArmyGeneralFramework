"""Deterministic large authored campaign fixture used by scale tests."""
import copy
from pathlib import Path

import yaml

def write_stress_campaign(destination, count=128):
    if type(count) is not int or count < 4 or count % 2:
        raise ValueError('Stress battalion count must be an even integer >= 4')
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    (destination / 'battalions').mkdir(parents=True)
    forces_path = destination / 'battalions/forces.yaml'
    forces = {'schema': 1}
    originals = {}
    for side, country, command, tank in (
            ('nato', 'RFA', 'M577_RFA_1', 'Leopard_2A4_RFA'),
            ('pact', 'RDA', 'UAZ_469_CMD_DDR_0', 'T72B1_SOV')):
        originals[side] = {'definition': {
            'country': country,
            'strategic': {'type': 'mechanized', 'battle_role': 'fighter',
                          'visual': {'unit': tank}},
            'companies': [
                {'id': 'hq', 'name': 'Headquarters', 'hq': True, 'platoons': [
                    {'id': 'command', 'name': 'Command', 'hq': True,
                     'units': [{'type': command, 'count': 1}]}]},
                {'id': 'armor', 'name': 'Tank company', 'hq': False, 'platoons': [
                    {'id': 'tanks', 'name': 'Tank platoon', 'hq': False,
                     'units': [{'type': tank + '_1', 'count': 3}]}]}]}}
    battalions = []
    for number in range(count):
        side = 'nato' if number < count // 2 else 'pact'
        row = copy.deepcopy(originals[side])
        row['id'] = f'stress_{side}_{number:03d}'
        row['side'] = side
        row['definition']['name'] = f'Scale {side} battalion {number:03d}'
        row['definition']['organization'] = f'Scale {side} regiment {number:03d}'
        battalions.append(row)
    forces['battalions'] = battalions
    deployments = []
    orders = []
    for number, row in enumerate(battalions):
        side = row['side']
        x = 260000 + (number % 8) * 50000 if side == 'nato' else 930000 + (number % 8) * 40000
        local_number = number % (count // 2)
        grid_rows = (count // 2 + 7) // 8
        y = 820000 + (local_number // 8) * 380000 // max(1, grid_rows - 1)
        battalion_id = row['id']
        deployments.append({'id': battalion_id, 'battalion': battalion_id, 'side': side,
                            'position': [x, y], 'fatigue': 0, 'action_points': 12, 'frozen_turns': 0})
        lane = (local_number // 8) % 4
        target = 'western_crossroads' if lane == 0 else 'stress_flag_' + str(lane * 2 - 2)
        orders.append({'unit': battalion_id, 'type': 'defend' if side == 'nato' else 'attack',
                       'target': target,
                       'start_turn': 1})
    (destination / 'deployments.yaml').write_text(yaml.safe_dump({'schema': 1, 'deployments': deployments}, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (destination / 'ai.yaml').write_text(yaml.safe_dump({'schema': 1, 'orders': orders}, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (destination / 'events.yaml').write_text(yaml.safe_dump({'schema': 1, 'events': []}, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (destination / 'reinforcements.yaml').write_text(yaml.safe_dump({'schema': 1, 'reinforcements': []}), encoding='utf-8')
    (destination / 'aviation.yaml').write_text(yaml.safe_dump({'schema': 1, 'airfields': [], 'wings': []}, allow_unicode=True, sort_keys=False), encoding='utf-8')
    campaign_path = destination / 'campaign.yaml'
    campaign = {'schema': 1, 'template': 'bruderkrieg_map', 'turns': 8,
                'date': [1989, 6, 20, 2], 'sides': {
                    'nato': {'countries': ['RFA', 'US'], 'playable': True},
                    'pact': {'countries': ['RDA', 'SOV'], 'playable': True}}}
    campaign['id'] = 'framework_scale_stress'
    campaign['title'] = {'ru': 'Framework — масштабный тест', 'en': 'Framework Scale Stress'}
    campaign['summary'] = {'ru': 'Массовая проверка кастомных батальонов и ИИ.', 'en': 'Large custom battalion and AI stress test.'}
    campaign['score_to_win'] = 1000
    campaign_path.write_text(yaml.safe_dump(campaign, allow_unicode=True, sort_keys=False), encoding='utf-8')
    map_path = destination / 'map.yaml'
    map_doc = {'schema': 1}
    flag_names = ['western_crossroads', 'eastern_crossroads'] + [f'stress_flag_{number}' for number in range(6)]
    map_doc['flags'] = [dict(capture_score=25, hold_score=0,
                             name={'ru': f'Рубеж {number + 1}', 'en': f'Objective {number + 1}'},
                             id=flag_names[number],
                             position=[450000 if number % 2 == 0 else 1000000, 850000 + (number // 2) * 100000],
                             initial_owner='nato' if number % 2 == 0 else 'pact') for number in range(8)]
    map_doc['influence_sources'] = [{'side': 'nato' if number % 2 == 0 else 'pact', 'value': 0.5,
                                   'position': [250000 if number % 2 == 0 else 1250000,
                                                850000 + (number // 2) * 100000]} for number in range(8)]
    map_doc['labels'] = [dict(size='small', id=f'stress_label_{number}',
                              position=[350000 + (number % 8) * 110000, 970000 + (number // 8) * 15000],
                              text={'ru': f'Тест {number}', 'en': f'Test {number}'}) for number in range(18)]
    map_path.write_text(yaml.safe_dump(map_doc, allow_unicode=True, sort_keys=False), encoding='utf-8')
    reserves = []
    points = []
    divisions = []
    groups = []
    for side in ('nato', 'pact'):
        row = copy.deepcopy(next(row for row in battalions if row['side'] == side))
        row['id'] = 'stress_reserve_' + side
        row['definition']['name'] = 'Scale reserve ' + side
        reserves.append(row)
        point_ids = []
        for number in range(6):
            identifier = f'stress_{side}_depot_{number}'
            point_ids.append(identifier)
            points.append({'id': identifier, 'side': side,
                           'position': [500000 - number * 35000 if side == 'nato' else 950000 + number * 35000, 1200000],
                           'name': {'ru': identifier, 'en': identifier}})
        division_id = 'stress_division_' + side
        divisions.append({'id': division_id, 'side': side, 'name': {'ru': division_id, 'en': division_id},
                          'short_name': {'ru': side, 'en': side}, 'deployment_points': point_ids})
        groups.append({'id': 'stress_regiment_' + side, 'division': division_id,
                       'name': {'ru': side, 'en': side}, 'turn': 3, 'battalions': [row['id']]})
    forces['battalions'].extend(reserves)
    forces_path.write_text(yaml.safe_dump(forces, allow_unicode=True, sort_keys=False), encoding='utf-8')
    production = {'schema': 1, 'deployment_points': points, 'divisions': divisions, 'groups': groups}
    (destination / 'production.yaml').write_text(yaml.safe_dump(production, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return destination
