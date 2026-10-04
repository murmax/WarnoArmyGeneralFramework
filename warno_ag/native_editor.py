"""Compile the editor's native campaign YAML into explicit, auditable native edits."""
import copy
import hashlib
import json
from pathlib import Path
import re
import math
import struct

from PIL import Image

from .editor_source import read_editor_source, _confined
from .label_tokens import label_token_key, private_label_token
from .storage import sha256
from .cndf import decode
from .native_script_fields import validate_script_field
from .native_frozen import INITIAL_READINESS_SOURCES


COUNTRY_SIDE = {**{country: 'nato' for country in ('US', 'RFA', 'UK', 'BEL', 'NL', 'CAN', 'ESP', 'FR')},
                **{country: 'pact' for country in ('SOV', 'RDA', 'POL', 'TCH', 'CUB')}}


def _fields(value, expected, where):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('Unknown or missing native source fields: ' + where)


def _differences(before, after, path=()):
    if isinstance(before, dict) and isinstance(after, dict) and set(before) == set(after):
        for key in before:
            yield from _differences(before[key], after[key], path + (key,))
    elif isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        for index, (old, new) in enumerate(zip(before, after)):
            yield from _differences(old, new, path + (index,))
    elif type(before) is not type(after) or before != after:
        # Integral JSON values may legitimately be formatted as real numbers by
        # YAML writers. Their numeric value is the source contract.
        if type(before) in (int, float) and type(after) in (int, float) and before == after:
            return
        yield {'path': list(path), 'before': before, 'after': after}


def _image_equal(first, second, mode):
    with Image.open(first) as a, Image.open(second) as b:
        return a.size == b.size and a.convert(mode).tobytes() == b.convert(mode).tobytes()


def _check_native_deployment_owner(identifier, battalion_id, baseline, battalions, owners):
    if battalion_id not in battalions:
        raise ValueError('Native deployment references an unknown formation')
    # Stock scenarios may start the same formation template more than once.
    # Only new placements need a distinct formation copy.
    if identifier not in baseline and battalion_id in owners:
        raise ValueError('New native formations require distinct initial deployments')
    owners.add(battalion_id)


def native_identity(project_id, title):
    if not isinstance(project_id, str) or re.fullmatch(r'[a-z][a-z0-9_]*', project_id) is None:
        raise ValueError('Native campaign id must be a lowercase source identifier')
    digest = hashlib.sha256(project_id.encode()).hexdigest()
    local_digest = hashlib.sha256(('agf-native-mod/v1:' + project_id).encode()).digest()
    return {'scenario': 'CampagneStrat_AGF' + digest[:12], 'mod_name': 'WarnoAGF_' + project_id,
            'local_mod_id': (1 << 52) | (int.from_bytes(local_digest[:8], 'big') & ((1 << 52) - 1)),
            'display_name': 'AGF — ' + title['en']}


def compile_native_source(source, profile_path=None, destination=None):
    source = Path(source).resolve()
    transport = read_editor_source(source, profile_path)
    docs, profile = transport['documents'], transport['profile']
    if set(docs) != {'campaign.yaml', 'content.yaml', 'world.yaml'}:
        raise ValueError('Native campaign requires campaign.yaml, content.yaml and world.yaml')
    campaign, content, world = (docs[name] for name in ('campaign.yaml', 'content.yaml', 'world.yaml'))
    _fields(campaign, ('schema', 'id', 'map_name', 'title', 'rules'), 'campaign')
    _fields(content, ('schema', 'campaign'), 'content')
    _fields(world, ('schema', 'world', 'grid', 'playable_polygons'), 'world')
    _fields(profile, ('schema', 'nativeSource', 'unitCatalog', 'baseline'), 'profile')
    for doc, schema in ((campaign, 'agf-native-campaign/v1'), (content, 'agf-native-content/v1'),
                        (world, 'agf-native-world/v1'), (profile, 'agf-native-profile/v1')):
        if doc['schema'] != schema:
            raise ValueError('Unsupported native editor schema')
    native = profile['nativeSource']
    identity = native_identity(campaign['id'], campaign['title'])
    if identity['scenario'] != native['targetScenario'] or identity['scenario'] == native['originalScenario']:
        raise ValueError('Native campaign identity differs from its source adapter')
    baseline = profile['baseline']
    state = {'id': campaign['id'], 'map_name': campaign['map_name'], 'title': campaign['title'],
             'rules': campaign['rules'], 'campaign': content['campaign'], 'world': world['world'],
             'grid': world['grid'], 'playable_polygons': world['playable_polygons']}
    if set(state) != set(baseline):
        raise ValueError('Native editor baseline shape changed')
    baseline['campaign'].setdefault('nativeScriptEdits', [])
    state['campaign'].setdefault('nativeScriptEdits', [])
    baseline['campaign'].setdefault('nativeProductionEdits', [])
    state['campaign'].setdefault('nativeProductionEdits', [])
    baseline['campaign'].setdefault('nativeProductionPositionEdits', [])
    state['campaign'].setdefault('nativeProductionPositionEdits', [])
    baseline['campaign'].setdefault('nativeReinforcementGroupCreations', [])
    state['campaign'].setdefault('nativeReinforcementGroupCreations', [])
    baseline['campaign'].setdefault('nativeProductionCreations', [])
    state['campaign'].setdefault('nativeProductionCreations', [])
    baseline['campaign'].setdefault('nativeEventTextEdits', [])
    state['campaign'].setdefault('nativeEventTextEdits', [])
    baseline['campaign'].setdefault('nativeTurnEventCreations', [])
    state['campaign'].setdefault('nativeTurnEventCreations', [])
    baseline['campaign'].setdefault('nativeAiTargetEdits', [])
    state['campaign'].setdefault('nativeAiTargetEdits', [])
    baseline['campaign'].setdefault('nativeAiOrderCreations', [])
    state['campaign'].setdefault('nativeAiOrderCreations', [])
    if state['playable_polygons'] != baseline['playable_polygons']:
        from .native_playable import contains_point, validate_playable_polygons

        points = validate_playable_polygons(baseline['playable_polygons'], state['playable_polygons'],
                                            state['world']['nativeField']['bounds'])
        for section in ('deployments', 'airfields'):
            for placement in state['campaign'][section]:
                position = placement['position']
                if not contains_point(points, [position['x'], position['y']]):
                    raise ValueError('Native playable polygon excludes an initial placement')
    changes = list(_differences(baseline, state))
    unsupported = []
    for change in changes:
        path = change['path']
        allowed = (path[0] in {'id', 'title', 'rules', 'grid', 'playable_polygons'}
                   or path[0] == 'world'
                   or path[0] == 'map_name'
                   or path[:2] in (['campaign', 'deployments'], ['campaign', 'battalions'],
                                   ['campaign', 'nativeScriptEdits'],
                                   ['campaign', 'nativeProductionEdits'])
                   or path[:2] == ['campaign', 'nativeProductionPositionEdits']
                   or path[:2] == ['campaign', 'nativeReinforcementGroupCreations']
                   or path[:2] == ['campaign', 'nativeProductionCreations']
                   or path[:2] == ['campaign', 'nativeEventTextEdits']
                   or path[:2] == ['campaign', 'nativeTurnEventCreations']
                   or path[:2] == ['campaign', 'nativeAiTargetEdits']
                   or path[:2] == ['campaign', 'nativeAiOrderCreations']
                   or path[:2] == ['campaign', 'airfields'] and len(path) >= 4 and path[3] == 'position')
        if not allowed:
            unsupported.append('.'.join(map(str, path)))
    if unsupported:
        raise ValueError('Native edit has no supported source binding: ' + ', '.join(unsupported))
    rule_bindings = {row['id']: row for row in native['rules']}
    if len(rule_bindings) != len(native['rules']) or {row['id'] for row in state['rules']} != set(rule_bindings):
        raise ValueError('Native rule binding inventory changed')
    rule_edits = []
    baseline_rules = {row['id']: row['value'] for row in baseline['rules']}
    for row in state['rules']:
        _fields(row, ('id', 'value'), 'rule')
        binding = rule_bindings[row['id']]
        expected_type = {'TGDVariableInteger': int, 'TGDVariableFloat': float, 'TGDVariableBoolean': bool}.get(binding['nativeClass'])
        if expected_type is None or (type(row['value']) is not expected_type and not (expected_type is float and type(row['value']) is int)):
            raise ValueError('Native rule value type changed: ' + row['id'])
        if expected_type is int and not -(2**31) <= row['value'] < 2**31:
            raise ValueError('Native integer rule is out of range')
        if row['value'] != baseline_rules[row['id']]:
            rule_edits.append({**binding, 'before': baseline_rules[row['id']], 'value': row['value']})
    bindings = {(row['kind'], row['id']): row for row in native['entityBindings']}
    map_feature_edits = []
    before_features = {row['id']: row for row in baseline['world'].get('mapFeatures', [])}
    after_features = {row['id']: row for row in state['world'].get('mapFeatures', [])}
    if (len(before_features) != len(baseline['world'].get('mapFeatures', []))
            or len(after_features) != len(state['world'].get('mapFeatures', []))
            or not set(before_features) <= set(after_features)):
        raise ValueError('Native map feature inventory changed')
    added_map_labels = []
    for identifier in sorted(set(after_features) - set(before_features)):
        feature = after_features[identifier]
        text = feature.get('displayText')
        position = feature.get('position')
        bounds = state['world']['nativeField']['bounds']
        if (feature.get('kind') != 'TGameDesignAddOn_LabelOnMap' or feature.get('token') is not None
                or not isinstance(feature.get('name'), str) or re.fullmatch(r'AGFLabel_[A-Za-z0-9_]+', feature['name']) is None
                or not isinstance(feature.get('guid'), str) or re.fullmatch(r'[0-9a-f]{32}', feature['guid']) is None
                or feature.get('component') not in {'LabelVille_01', 'LabelVille_02', 'LabelVille_03', 'LabelVille_04',
                                                    'autoroute_low', 'autoroute_high'}
                or not isinstance(position, dict) or set(position) != {'x', 'y'}
                or any(type(position[k]) not in (int, float) or not math.isfinite(position[k]) for k in ('x', 'y'))
                or not bounds['minX'] <= position['x'] <= bounds['maxX']
                or not bounds['minY'] <= position['y'] <= bounds['maxY']
                or not isinstance(text, dict) or set(text) != {'ru', 'en'}
                or any(not isinstance(text[language], str) or not text[language].strip()
                       or len(text[language]) > 120 or any(ord(char) < 32 for char in text[language])
                       for language in ('ru', 'en'))):
            raise ValueError('New native map label has invalid identity, style, position or text')
        token = private_label_token(identity['scenario'], feature['guid'])
        added_map_labels.append({'id': identifier, 'name': feature['name'], 'guid': feature['guid'],
                                 'position': [position['x'], position['y']], 'component': feature['component'],
                                 'token': token, 'label_key': label_token_key(token), 'label_text': text})
    for identifier, feature in after_features.items():
        if identifier not in before_features:
            continue
        previous = before_features[identifier]
        allowed = {'position', 'displayText'} if feature['kind'] == 'TGameDesignAddOn_LabelOnMap' else {'position'}
        if any(previous.get(key) != feature.get(key) for key in set(previous) | set(feature) if key not in allowed):
            raise ValueError('Native map feature identity or behavior changed: ' + identifier)
        position_changed = feature['position'] != previous['position']
        text_changed = feature.get('displayText') != previous.get('displayText')
        if position_changed or text_changed:
            binding = bindings.get(('map_feature', identifier))
            if binding is None:
                raise ValueError('Native map feature binding is missing: ' + identifier)
            edit = {**binding, 'guid': previous['guid'], 'before': previous['position'],
                    'position': feature['position']}
            if text_changed:
                text = feature.get('displayText')
                if (not isinstance(text, dict) or set(text) != {'ru', 'en'}
                        or any(not isinstance(text[language], str) or not text[language].strip()
                               or len(text[language]) > 120 or any(ord(char) < 32 for char in text[language])
                               for language in ('ru', 'en'))):
                    raise ValueError('Map label requires short, nonempty RU and EN text')
                before_token = previous.get('token')
                if before_token and previous.get('localizationKey') not in (None, label_token_key(before_token)):
                    raise ValueError('Original map label token key changed')
                private_token = private_label_token(identity['scenario'], previous['guid'])
                edit.update(label_before=before_token, label_token=private_token,
                            label_key=label_token_key(private_token), label_text=text)
            map_feature_edits.append(edit)
    private_keys = ([row['label_key'] for row in map_feature_edits if 'label_key' in row]
                    + [row['label_key'] for row in added_map_labels])
    if len(private_keys) != len(set(private_keys)):
        raise ValueError('Private map label tokens collided')
    before_battalions = {row['id']: row for row in baseline['campaign']['battalions']}
    after_battalions = {row['id']: row for row in state['campaign']['battalions']}
    if len(after_battalions) != len(state['campaign']['battalions']):
        raise ValueError('Duplicate native battalion id')
    if not set(before_battalions) <= set(after_battalions):
        raise ValueError('Remove initial deployments instead of deleting a stock formation referenced by native scripts')
    battalion_edits = []
    for identifier, row in after_battalions.items():
        is_new = identifier not in before_battalions
        prototype = row.get('nativePrototypeId') if is_new else identifier
        if prototype not in before_battalions:
            raise ValueError('New native formations require an imported formation template')
        before = before_battalions[prototype]
        allowed_fields = {'name', 'localizedName', 'localizedOrganization',
                          'companies', 'strategicVisualUnitId'} | (
            {'id', 'nativePrototypeId', 'parentFormationId', 'country', 'side',
             'organization', 'supportRadiusAp'}
            if is_new else set())
        if any(before.get(field) != row.get(field) for field in set(before) | set(row) if field not in allowed_fields):
            raise ValueError('Native formation edit changed fields outside its template bindings: ' + identifier)
        for field in ('localizedName', 'localizedOrganization'):
            localized = row.get(field)
            if localized is not None and (not isinstance(localized, dict)
                    or set(localized) != {'ru', 'en'}
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value.encode('utf-16-le')) // 2 > 60
                           for value in localized.values())):
                raise ValueError('Native formation localized name requires short RU/EN text')
        if row.get('localizedName') is not None and row['name'] != row['localizedName']['ru']:
            raise ValueError('Native formation display name differs from its Russian localization')
        if (row.get('localizedOrganization') is not None
                and row.get('organization') != row['localizedOrganization']['ru']):
            raise ValueError('Native formation organization differs from its Russian localization')
        if is_new:
            if (row.get('organization') != before.get('organization')
                    and row.get('parentFormationId') is None):
                raise ValueError('Private native organization name requires a map-command parent')
            if (row.get('localizedOrganization') != before.get('localizedOrganization')
                    and row.get('parentFormationId') is None and row['country'] == before['country']):
                raise ValueError('Private native organization translation has no mapped command or division')
            if COUNTRY_SIDE.get(row['country']) != row['side']:
                raise ValueError('Native formation country and coalition are incompatible')
            if row['country'] != before['country'] and row['strategicVisualUnitId'] == before['strategicVisualUnitId']:
                raise ValueError('Native country change requires a verified matching strategic visual')
            if row.get('supportRadiusAp') != before.get('supportRadiusAp'):
                radius = row.get('supportRadiusAp')
                if (before.get('supportKind') not in {'air_defence', 'artillery'}
                        or type(radius) not in (int, float) or not math.isfinite(radius)
                        or not 0 < radius <= 1000):
                    raise ValueError('Native private support radius requires a support template and 0 < radius <= 1000')
        if row['strategicVisualUnitId'] != before['strategicVisualUnitId']:
            from .visual_catalog import current_visual_catalog
            visual_id = row['strategicVisualUnitId']
            visual = current_visual_catalog().get(visual_id)
            if visual is None or visual['category'] not in {'infantry', 'vehicle', 'helicopter', 'airplane'}:
                raise ValueError('Native strategic visual is absent from the verified game catalog')
            country = 'DDR' if row['country'] == 'RDA' else row['country']
            if not visual_id.endswith('_' + country):
                raise ValueError('Native strategic visual country differs from its formation')
        parent_id = row.get('parentFormationId')
        if parent_id is not None:
            if (not is_new or not isinstance(parent_id, str) or parent_id == identifier
                    or parent_id not in before_battalions):
                raise ValueError('Native parent formation must be an existing stock formation')
            if before_battalions[parent_id]['side'] != row['side']:
                raise ValueError('Native parent formation belongs to another coalition')
        if is_new or row != before:
            binding = bindings.get(('battalion', prototype))
            if binding is None:
                raise ValueError('Native battalion binding is missing')
            battalion_edits.append({'binding': binding, 'before': before, 'after': row, 'is_new': is_new})
    placements = []
    added_placements = []
    frozen_deployments = []
    action_point_deployments = []
    initial_readiness_deployments = []
    deployment_owners = set()
    for section in ('deployments', 'airfields'):
        before = {row['id']: row for row in baseline['campaign'][section]}
        after = {row['id']: row for row in state['campaign'][section]}
        if len(after) != len(state['campaign'][section]):
            raise ValueError('Duplicate native placement id')
        if section == 'airfields' and set(before) != set(after):
            raise ValueError('Native airfield creation/removal requires an explicit airport adapter')
        for removed in set(before) - set(after):
            placements.append({**bindings['placement', removed], 'remove': True,
                               'before': before[removed]['position'], 'position': before[removed]['position']})
        for identifier, row in after.items():
            position = row['position']
            limits = state['world']['playableSubfield']['bounds']
            if (set(position) != {'x', 'y'} or any(type(position[k]) not in (int, float) or not math.isfinite(position[k]) for k in ('x', 'y'))
                    or not limits['minX'] <= position['x'] <= limits['maxX'] or not limits['minY'] <= position['y'] <= limits['maxY']):
                raise ValueError('Native placement is outside playable bounds')
            if section == 'deployments':
                _check_native_deployment_owner(identifier, row['battalionId'], before,
                                               after_battalions, deployment_owners)
                frozen_turns = row.get('frozenTurns', 0)
                if type(frozen_turns) is not int or not 0 <= frozen_turns <= 30:
                    raise ValueError('Native frozen turns must be an integer in 0..30')
            if identifier not in before:
                formation = after_battalions[row['battalionId']]
                if row['battalionId'] in before_battalions:
                    raise ValueError('New deployments require a new formation copy so native script references remain isolated')
                if row['side'] != formation['side']:
                    raise ValueError('New native deployment side differs from its formation')
                action_points = row.get('actionPoints', 12)
                if type(action_points) is not int or not 0 <= action_points <= 12:
                    raise ValueError('New native deployment action points must be an integer in 0..12')
                fatigue = row.get('fatigue', 0)
                losses = row.get('initialLossBudget', 0)
                spread = row.get('initialLossRandomRange', 0)
                if (type(fatigue) is not int or not 0 <= fatigue <= 8
                        or type(losses) is not int or not 0 <= losses <= 10000
                        or type(spread) is not int or not 0 <= spread <= 1000
                        or spread > losses or row.get('initialLossMaxPercent') is not None):
                    raise ValueError('Native private fatigue/losses require bounded count and range values')
                if fatigue or losses or spread:
                    if (formation['strategicType'] == 'airplane'
                            or native['originalScenario'] not in INITIAL_READINESS_SOURCES):
                        raise ValueError('Native private fatigue/losses require a verified ground or helicopter source adapter')
                    initial_readiness_deployments.append(copy.deepcopy(row))
                if row.get('frozenTurns', 0):
                    if formation['strategicType'] == 'airplane':
                        raise ValueError('Native frozen adapter currently supports ground and helicopter formations')
                    frozen_deployments.append(copy.deepcopy(row))
                elif action_points != 12:
                    if formation['strategicType'] == 'airplane':
                        raise ValueError('Native custom initial AP currently supports ground and helicopter formations')
                    action_point_deployments.append(copy.deepcopy(row))
                added_placements.append(copy.deepcopy(row))
                continue
            if any(row.get(field) != before[identifier].get(field) for field in set(row) | set(before[identifier]) if field != 'position'):
                raise ValueError('Native deployment edit changed fields outside its position binding')
            if row['position'] != before[identifier]['position']:
                binding = bindings.get(('placement', identifier))
                if binding is None:
                    raise ValueError('Native placement binding is missing')
                placements.append({**binding, 'before': before[identifier]['position'], 'position': row['position']})
    manifest_path = _confined(source, native['manifestPath'])
    snapshot = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    resources = {(row['scope'], row['path']): row for row in manifest['resources']}
    def resource(scope, path):
        return _confined(snapshot, resources[scope, path]['file'])
    camp_by_side = None
    if added_placements or state['campaign']['nativeAiOrderCreations']:
        from .native_camps import source_camp_by_side

        projection_path = _confined(snapshot, manifest['projection_file'])
        if sha256(projection_path.read_bytes()) != manifest['projection_sha256']:
            raise ValueError('Native source camp mapping projection changed')
        camp_by_side = source_camp_by_side(
            json.loads(projection_path.read_text(encoding='utf-8')), baseline,
            native['entityBindings'])
    if baseline['campaign']['nativeScriptEdits']:
        raise ValueError('Native source baseline must not contain authored script edits')
    if baseline['campaign']['nativeProductionEdits']:
        raise ValueError('Native source baseline must not contain authored production edits')
    if baseline['campaign']['nativeProductionPositionEdits']:
        raise ValueError('Native source baseline must not contain authored production position edits')
    if baseline['campaign']['nativeReinforcementGroupCreations']:
        raise ValueError('Native source baseline must not contain authored reinforcement group creations')
    if baseline['campaign']['nativeProductionCreations']:
        raise ValueError('Native source baseline must not contain authored production creations')
    if baseline['campaign']['nativeEventTextEdits']:
        raise ValueError('Native source baseline must not contain authored event text edits')
    if baseline['campaign']['nativeAiTargetEdits']:
        raise ValueError('Native source baseline must not contain authored AI target edits')
    if baseline['campaign']['nativeAiOrderCreations']:
        raise ValueError('Native source baseline must not contain authored AI order creations')
    script_edits = []
    production_edits = []
    script_graph = None
    requested_script_edits = state['campaign']['nativeScriptEdits']
    if not isinstance(requested_script_edits, list):
        raise ValueError('Native script edits must be a list')
    if requested_script_edits:
        script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
        _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        visited = set()
        for row in requested_script_edits:
            _fields(row, ('objectId', 'nativeClass', 'propertyName', 'before', 'after', 'export'), 'native script edit')
            object_id = row['objectId']
            if type(object_id) is not int or not 0 <= object_id < len(script_graph['objects']):
                raise ValueError('Native script edit object id is invalid')
            obj = script_graph['objects'][object_id]
            if (obj['class'] != row['nativeClass']
                    or script_graph['exports'].get(object_id) != row['export']):
                raise ValueError('Native script scalar edit changed its source binding')
            property_name = row['propertyName']
            wire = validate_script_field(obj, property_name, row['after'])
            if (wire.get('value') != row['before']
                    or type(wire.get('value')) is not type(row['before'])):
                raise ValueError('Native script property no longer matches its captured value')
            if ((object_id, property_name) in visited or row['after'] == row['before']):
                raise ValueError('Native script scalar edit is invalid, duplicated or unchanged')
            visited.add((object_id, property_name))
            if property_name == 'Value' and any(binding['objectId'] == object_id for binding in native['rules']):
                raise ValueError('Native script scalar edit belongs to a named scenario rule')
            script_edits.append(copy.deepcopy(row))
    requested_production_edits = state['campaign']['nativeProductionEdits']
    if not isinstance(requested_production_edits, list):
        raise ValueError('Native production group edits must be a list')
    if requested_production_edits:
        if script_graph is None:
            script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
            _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        source_bindings = {row['export']: row['id'] for row in native['entityBindings']
                           if row['kind'] == 'battalion' and row.get('export')}
        seen_groups = set()
        for row in requested_production_edits:
            _fields(row, ('objectId', 'export', 'beforeBattalionIds', 'afterBattalionIds'),
                    'native production group edit')
            object_id = row['objectId']
            if type(object_id) is not int or not 0 <= object_id < len(script_graph['objects']):
                raise ValueError('Native production group object id is invalid')
            obj = script_graph['objects'][object_id]
            if (obj['class'] != 'TGDDescriptorStrategicAddPossibleProduction'
                    or script_graph['exports'].get(object_id) != row['export']
                    or object_id in seen_groups):
                raise ValueError('Native production group source binding changed or is duplicated')
            seen_groups.add(object_id)
            props = {prop['property_name']: prop['value'] for prop in obj['properties']}
            pawns, camp = props.get('Pawns'), props.get('Camp')
            if (pawns is None or pawns['type'] != 'list' or not pawns['items']
                    or camp is None or camp['type'] != 'obj_ref'
                    or any(item['type'] != 'trans_ref' for item in pawns['items'])):
                raise ValueError('Native production group has an unsupported membership binding')
            camp_path = script_graph['exports'].get(camp['object_id'], '').rsplit('/', 1)[-1].lower()
            if camp_path not in ('nato', 'pact'):
                raise ValueError('Native production group has no unambiguous coalition')
            before = [source_bindings.get(item['value']) for item in pawns['items']]
            after = row['afterBattalionIds']
            if (None in before or row['beforeBattalionIds'] != before
                    or not isinstance(after, list) or not 1 <= len(after) <= 32
                    or any(type(identifier) is not str for identifier in after)
                    or len(set(after)) != len(after) or after == before
                    or any(identifier not in before_battalions
                           or before_battalions[identifier]['side'] != camp_path for identifier in after)):
                raise ValueError('Native production group membership or coalition is invalid')
            production_edits.append(copy.deepcopy(row))
    production_position_edits = []
    requested_production_positions = state['campaign']['nativeProductionPositionEdits']
    if not isinstance(requested_production_positions, list):
        raise ValueError('Native production position edits must be a list')
    reinforcement_creations = []
    requested_reinforcement_creations = state['campaign']['nativeReinforcementGroupCreations']
    if not isinstance(requested_reinforcement_creations, list):
        raise ValueError('Native reinforcement group creations must be a list')
    if requested_production_positions or requested_reinforcement_creations:
        from .native_production_positions import production_position_pool

        if script_graph is None:
            script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
            _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        group_sides, position_pool = production_position_pool(script_graph)
        projection_path = _confined(snapshot, manifest['projection_file'])
        if sha256(projection_path.read_bytes()) != manifest['projection_sha256']:
            raise ValueError('Native production source map projection changed')
        projection = json.loads(projection_path.read_text(encoding='utf-8'))
        points = {}
        for point in projection['map_points']:
            guid = point['addon_properties'].get('GUID', {}).get('hex')
            if point['kind'] == 'TGameDesignAddOn_Name' and guid:
                points.setdefault(guid, []).append(point)
        bounds = state['world']['playableSubfield']['bounds']
        def verified_target(index):
            obj = script_graph['objects'][index]
            words = {prop['property_name']: prop['value'].get('value')
                     for prop in obj['properties']}
            if any(type(words.get('GUID' + str(number))) is not int for number in range(1, 5)):
                return False
            guid = struct.pack('>4i', *(words['GUID' + str(number)]
                                      for number in range(1, 5))).hex()
            matching = points.get(guid, [])
            return (len(matching) == 1 and script_graph['exports'].get(index)
                    and bounds['minX'] <= matching[0]['position'][0] <= bounds['maxX']
                    and bounds['minY'] <= matching[0]['position'][1] <= bounds['maxY'])
        seen_positions = set()
        for row in requested_production_positions:
            _fields(row, ('objectId', 'export', 'beforeTargetObjectIds',
                          'afterTargetObjectIds'), 'native production position edit')
            object_id = row['objectId']
            if (type(object_id) is not int or not 0 <= object_id < len(script_graph['objects'])
                    or object_id in seen_positions):
                raise ValueError('Native production position source group is invalid or duplicated')
            seen_positions.add(object_id)
            group = script_graph['objects'][object_id]
            sides = group_sides.get(object_id, set())
            positions = [prop['value'] for prop in group['properties']
                         if prop['property_name'] == 'SpawnPositionsSortedByPriority']
            if (group['class'] != 'TGDStrategicReinforcementGroup'
                    or script_graph['exports'].get(object_id) != row['export']
                    or len(sides) != 1 or len(positions) != 1
                    or positions[0]['type'] != 'list'
                    or any(item['type'] != 'obj_ref' for item in positions[0]['items'])):
                raise ValueError('Native production position group has no unique source binding')
            before = [item['object_id'] for item in positions[0]['items']]
            after = row['afterTargetObjectIds']
            side = next(iter(sides))
            if (row['beforeTargetObjectIds'] != before
                    or not isinstance(after, list) or not 1 <= len(after) <= 8
                    or any(type(index) is not int for index in after)
                    or len(set(after)) != len(after) or after == before
                    or any(index not in position_pool[side] or not verified_target(index)
                           for index in after)):
                raise ValueError('Native production spawn positions must use unique same-side verified map points')
            production_position_edits.append(copy.deepcopy(row))
        known_reinforcement_keys = {prop['value']['value_hex'] for obj in script_graph['objects']
                                    for prop in obj['properties'] if prop['value']['type'] == 'loc_hash'}
        marker_rows = {row['id']: row for row in state['world'].get('markers', [])}
        if len(marker_rows) != len(state['world'].get('markers', [])):
            raise ValueError('Native production marker identity is duplicated')
        seen_reinforcement_ids = set()
        for row in requested_reinforcement_creations:
            required = {'id', 'templateObjectId', 'templateExport', 'name',
                        'spawnTargetObjectIds'}
            if not isinstance(row, dict) or set(row) not in (required, required | {'spawnMarkerId'}):
                raise ValueError('Native reinforcement group creation has unknown or missing fields')
            identifier = row['id']
            template_id = row['templateObjectId']
            if (not isinstance(identifier, str)
                    or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                    or identifier in seen_reinforcement_ids or type(template_id) is not int
                    or not 0 <= template_id < len(script_graph['objects'])):
                raise ValueError('Native reinforcement group requires unique id and source template')
            seen_reinforcement_ids.add(identifier)
            template = script_graph['objects'][template_id]
            sides = group_sides.get(template_id, set())
            props = {prop['property_name']: prop['value'] for prop in template['properties']}
            if (template['class'] != 'TGDStrategicReinforcementGroup'
                    or script_graph['exports'].get(template_id) != row['templateExport']
                    or len(sides) != 1
                    or set(props) != {'DisplayName', 'ShortDisplayName',
                                      'SpawnPositionsSortedByPriority'}
                    or any(props[name]['type'] != 'loc_hash'
                           for name in ('DisplayName', 'ShortDisplayName'))
                    or props['SpawnPositionsSortedByPriority']['type'] != 'list'):
                raise ValueError('Native reinforcement source template shape changed')
            parents = [obj for obj in script_graph['objects']
                       if obj['class'] == 'TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction'
                       and any(prop['property_name'] == 'ReinforcementGroups'
                           and prop['value']['type'] == 'list'
                           and any(item.get('object_id') == template_id
                                   for item in prop['value']['items'])
                           for prop in obj['properties'])]
            if len(parents) != 1:
                raise ValueError('New native reinforcement group needs one source registration action')
            parent = parents[0]
            parent_source_groups = [item['object_id'] for prop in parent['properties']
                                    if prop['property_name'] == 'ReinforcementGroups'
                                    for item in prop['value']['items']]
            parent_camp = next(prop['value']['object_id'] for prop in parent['properties']
                               if prop['property_name'] == 'Camp')
            side = next(iter(sides))
            if script_graph['exports'].get(parent_camp, '').rsplit('/', 1)[-1].lower() != side:
                raise ValueError('Native reinforcement parent coalition changed')
            name = row['name']
            targets = row['spawnTargetObjectIds']
            marker_id = row.get('spawnMarkerId')
            marker = marker_rows.get(marker_id) if isinstance(marker_id, str) else None
            if marker_id is not None:
                from .native_playable import contains_point
                from .native_markers import native_marker_identity

                polygons = [[[point['x'], point['y']] for point in polygon]
                            for polygon in state['playable_polygons']]
                if (marker is None or targets != [] or not isinstance(marker.get('name'), str)
                        or not marker['name'].strip()
                        or not contains_point(polygons,
                            [marker['position']['x'], marker['position']['y']])):
                    raise ValueError('New native reinforcement point requires a named playable map marker')
                marker_identity = native_marker_identity(identity['scenario'], marker_id)
                marker_export = '$/GDScript/GdItems/Tags/' + marker_identity['name']
                if marker_export in script_graph['exports'].values():
                    raise ValueError('New native reinforcement marker collides with source script')
            else:
                marker_identity = None
                marker_export = None
            if (not isinstance(name, dict) or set(name) != {'ru', 'en'}
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value) > 120 or '\x00' in value for value in name.values())
                    or not isinstance(targets, list)
                    or marker_id is None and (not 1 <= len(targets) <= 8
                        or any(type(index) is not int for index in targets)
                        or len(set(targets)) != len(targets)
                        or any(index not in position_pool[side] or not verified_target(index)
                               for index in targets))):
                raise ValueError('New native reinforcement group needs RU/EN name and same-side map points')
            digest = hashlib.sha256((identity['scenario'] + ':reinforcement:' + identifier).encode()).hexdigest()
            display_key, short_key = digest[:16], digest[16:32]
            target_export = '$/GDScript/AGF/ReinforcementGroup/' + digest[:16]
            if (display_key in known_reinforcement_keys or short_key in known_reinforcement_keys
                    or target_export in script_graph['exports'].values()):
                raise ValueError('New native reinforcement identity collides with source graph')
            known_reinforcement_keys.update((display_key, short_key))
            reinforcement_creations.append({**copy.deepcopy(row), 'side': side,
                'parentActionObjectId': parent['id'], 'campObjectId': parent_camp,
                'parentSourceGroups': parent_source_groups,
                'displayKey': display_key, 'shortKey': short_key,
                'spawnMarkerExport': marker_export,
                'spawnMarkerGuid': marker_identity['guid'] if marker_identity else None,
                'spawnMarkerPosition': marker['position'] if marker else None,
                'targetExport': target_export})
    production_creations = []
    requested_production_creations = state['campaign']['nativeProductionCreations']
    if not isinstance(requested_production_creations, list):
        raise ValueError('Native production creations must be a list')
    if requested_production_creations:
        if script_graph is None:
            script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
            _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        source_bindings = {row['id']: row['export'] for row in native['entityBindings']
                           if row['kind'] == 'battalion' and row.get('export')}
        known_keys = {prop['value']['value_hex'] for obj in script_graph['objects']
                      for prop in obj['properties'] if prop['value']['type'] == 'loc_hash'}
        edited_templates = {row['objectId'] for row in production_edits}
        private_reinforcements = {row['id']: row for row in reinforcement_creations}
        seen_ids = set()
        for row in requested_production_creations:
            required = {'id', 'templateObjectId', 'templateExport', 'name',
                        'unlockTurn', 'battalionIds'}
            if set(row) not in (required, required | {'reinforcementGroupId'}):
                raise ValueError('Native production creation has unknown or missing fields')
            identifier = row['id']
            if (not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                    or identifier in seen_ids):
                raise ValueError('Native production creation requires a unique short id')
            seen_ids.add(identifier)
            template_id = row['templateObjectId']
            if (type(template_id) is not int or not 0 <= template_id < len(script_graph['objects'])
                    or template_id in edited_templates):
                raise ValueError('Native production creation has no untouched source template')
            template = script_graph['objects'][template_id]
            if (template['class'] != 'TGDDescriptorStrategicAddPossibleProduction'
                    or script_graph['exports'].get(template_id) != row['templateExport']):
                raise ValueError('Native production template binding changed')
            props = {prop['property_name']: prop['value'] for prop in template['properties']}
            if (set(props) != {'Pawns', 'DisplayName', 'Camp', 'ReinforcementGroup',
                               'UnlockAtTurnVariable'} or props['Pawns']['type'] != 'list'
                    or any(item['type'] != 'trans_ref' for item in props['Pawns']['items'])
                    or props['DisplayName']['type'] != 'loc_hash'
                    or any(props[name]['type'] != 'obj_ref' for name in
                           ('Camp', 'ReinforcementGroup', 'UnlockAtTurnVariable'))):
                raise ValueError('Native production source template shape changed')
            camp_id = props['Camp']['object_id']
            side = script_graph['exports'].get(camp_id, '').rsplit('/', 1)[-1].lower()
            group_id = props['ReinforcementGroup']['object_id']
            turn_id = props['UnlockAtTurnVariable']['object_id']
            if (side not in ('nato', 'pact') or script_graph['objects'][camp_id]['class'] != 'TGDVariableCamp'
                    or script_graph['objects'][group_id]['class'] != 'TGDStrategicReinforcementGroup'
                    or script_graph['objects'][turn_id]['class'] != 'TGDVariableInteger'):
                raise ValueError('Native production template side, division or turn variable changed')
            private_group_id = row.get('reinforcementGroupId')
            if private_group_id is not None:
                created_group = private_reinforcements.get(private_group_id)
                if (not isinstance(private_group_id, str) or created_group is None
                        or created_group['templateObjectId'] != group_id
                        or created_group['side'] != side):
                    raise ValueError('New production group needs a matching authored reinforcement division')
            parents = [obj for obj in script_graph['objects']
                       if obj['class'] == 'TGDDescriptorSequential'
                       and any(prop['property_name'] == 'SubActions'
                           and prop['value']['type'] == 'list'
                           and any(item.get('object_id') == template_id for item in prop['value']['items'])
                           for prop in obj['properties'])]
            if len(parents) != 1:
                raise ValueError('Native production template has no unique source action chain')
            members = row['battalionIds']
            if (not isinstance(members, list) or not 1 <= len(members) <= 32
                    or any(type(item) is not str for item in members)
                    or len(set(members)) != len(members)
                    or any(item not in source_bindings or before_battalions[item]['side'] != side
                           for item in members)):
                raise ValueError('Native production creation has invalid same-side members')
            title = row['name']
            if (not isinstance(title, dict) or set(title) != {'ru', 'en'}
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value) > 120 or '\x00' in value for value in title.values())
                    or type(row['unlockTurn']) is not int or not 1 <= row['unlockTurn'] <= 30):
                raise ValueError('Native production creation needs RU/EN title and turn 1..30')
            digest = hashlib.sha256((identity['scenario'] + ':production:' + identifier).encode()).hexdigest()
            title_key = bytes.fromhex(digest[:16]).hex()
            target_export = '$/GDScript/AGF/Production/' + digest[:16]
            turn_export = '$/GDScript/AGF/ProductionTurn/' + digest[:16]
            if (title_key in known_keys
                    or title_key in {key for group in reinforcement_creations
                                     for key in (group['displayKey'], group['shortKey'])}
                    or target_export in script_graph['exports'].values()
                    or turn_export in script_graph['exports'].values()):
                raise ValueError('Native private production identity collides with source graph')
            known_keys.add(title_key)
            production_creations.append({**copy.deepcopy(row), 'parentObjectId': parents[0]['id'],
                'side': side, 'campObjectId': camp_id, 'reinforcementObjectId': group_id,
                'targetExport': target_export, 'turnExport': turn_export,
                'titleKey': title_key, 'pawnExports': [source_bindings[item] for item in members]})
    event_text_edits = []
    requested_event_text_edits = state['campaign']['nativeEventTextEdits']
    if not isinstance(requested_event_text_edits, list):
        raise ValueError('Native event text edits must be a list')
    if requested_event_text_edits:
        if script_graph is None:
            script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
            _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        from .game_resources import GameResources
        from .native_campaign_source import NativeCampaignReader

        translations = NativeCampaignReader(GameResources(manifest['game_root'])).translations(
            native['originalScenario'])
        existing_keys = {prop['value']['value_hex'] for obj in script_graph['objects']
                         for prop in obj['properties'] if prop['value']['type'] == 'loc_hash'}
        seen_text = set()
        for row in requested_event_text_edits:
            if set(row) not in ({'objectId', 'export', 'beforeKey', 'text'},
                                {'objectId', 'export', 'beforeKey', 'text', 'propertyName'}):
                raise ValueError('Native event text edit has unknown fields')
            object_id = row['objectId']
            if type(object_id) is not int or not 0 <= object_id < len(script_graph['objects']):
                raise ValueError('Native event text object id is invalid')
            obj = script_graph['objects'][object_id]
            property_name = row.get('propertyName', 'LocalizedText')
            allowed = ({'TGDDescriptorCutsceneTextComponent': {'LocalizedText'},
                        'TGDDescriptorCutsceneDialogWithMultipleChoice':
                            {'TokenBoutonChoix0', 'TokenBoutonChoix1'},
                        'TGDDescriptorCutsceneDialog': {'TokenBoutonChoix0'}})
            if property_name not in allowed.get(obj['class'], set()):
                raise ValueError('Native event text has no verified property binding')
            domain = 'dialog' if property_name == 'LocalizedText' else 'interface'
            props = [prop['value'] for prop in obj['properties'] if prop['property_name'] == property_name]
            if (obj['class'] not in allowed
                    or script_graph['exports'].get(object_id) != row['export']
                    or len(props) != 1 or props[0]['type'] != 'loc_hash'
                    or props[0]['value_hex'] != row['beforeKey']
                    or (object_id, property_name) in seen_text):
                raise ValueError('Native event text source binding changed or is duplicated')
            seen_text.add((object_id, property_name))
            for language in ('ru', 'en'):
                records = translations[language].get(row['beforeKey'], [])
                marker = '/Scripting/Dialog-' if domain == 'dialog' else '/Core/INTERFACE_INGAME-'
                if not any(marker in item['resource'] for item in records):
                    raise ValueError('Native event text lacks its original dictionary binding')
            text = row['text']
            if (not isinstance(text, dict) or set(text) != {'ru', 'en'}
                    or any(not isinstance(text[language], str) or not text[language].strip()
                           or len(text[language]) > (5000 if domain == 'dialog' else 120)
                           or '\x00' in text[language]
                           for language in ('ru', 'en'))):
                raise ValueError('Native event text requires nonempty RU/EN strings')
            identity_key = (identity['scenario'] + ':dialog:' + str(object_id)
                            if domain == 'dialog' else
                            identity['scenario'] + ':choice:' + str(object_id) + ':' + property_name)
            key = hashlib.sha256(identity_key.encode()).digest()[:8].hex()
            if key in existing_keys:
                raise ValueError('Private native event text key collides with the source script')
            event_text_edits.append({**copy.deepcopy(row), 'targetKey': key})
    turn_event_creations = []
    requested_turn_events = state['campaign']['nativeTurnEventCreations']
    if not isinstance(requested_turn_events, list):
        raise ValueError('Native turn events must be a list')
    if requested_turn_events:
        from .native_turn_events import TURN_EVENT_ADAPTERS, source_dialog_turns, property_wire

        adapter = TURN_EVENT_ADAPTERS.get(native['originalScenario'])
        if adapter is None:
            raise ValueError('Native turn event creation has no pinned source script adapter')
        script_path = 'NDF/Scenarios/GDScript/' + native['originalScenario'] + '.ndfbin'
        raw = resource('scenario_definition', script_path).read_bytes()
        if sha256(raw) != adapter['sha256']:
            raise ValueError('Native turn event source script revision changed')
        if script_graph is None:
            _, script_graph = decode(raw)
        objects = script_graph['objects']
        for side, spec in adapter['sides'].items():
            parent, sequence = objects[spec['parent']], objects[spec['template']]
            refs = [item['object_id'] for prop in parent['properties']
                    if prop['property_name'] == 'SubActions' for item in prop['value']['items']]
            if (parent['class'] != 'TGDDescriptorSimultaneous'
                    or sequence['class'] != 'TGDDescriptorSequential'
                    or not refs or len(refs) != spec.get('source_action_count', len(refs))
                    or refs != spec.get('source_actions', refs)
                    or objects[spec['compare']]['class'] != 'TGDOperatorIntegerCompare'
                    or objects[spec['text']]['class'] != 'TGDDescriptorCutsceneTextComponent'
                    or objects[spec['variable']]['class'] != 'TGDConditionVariable'
                    or objects[spec['player']]['class'] != 'TGDConditionStrategicIsPlayerTurn'
                    or objects[spec['camp']]['class'] != 'TGDVariableCamp'
                    or len(spec['subtree']) not in (10, 12)
                    or spec.get('synthetic', False) and
                       tuple(objects[index]['class'] for index in spec['subtree']) != (
                           'TGDDescriptorSequential', 'TGDDescriptorWaitCondition',
                           'TGDConditionAnd', 'TGDConditionVariable',
                           'TGDOperatorIntegerCompare', 'TGDConditionStrategicIsPlayerTurn',
                           'TGDDescriptorEncapsuleCutscene',
                           'TGDDescriptorCutscenePlayDialogList',
                           'TGDDescriptorCutsceneDialog',
                           'TGDDescriptorCutsceneTextComponent')
                           + (('TGDDescriptorCutsceneTextComponent',
                               'TGDDescriptorCutsceneTextureComponent')
                              if len(spec['subtree']) == 12 else ())):
                raise ValueError('Native turn event source action chain changed')
        known_keys = {prop['value']['value_hex'] for obj in objects for prop in obj['properties']
                      if prop['value']['type'] == 'loc_hash'}
        max_turn_ids = [row['id'] for row in native['rules']
                        if row['name'] == adapter.get('max_rule', 'TourMax')]
        max_turns = [row['value'] for row in state['rules'] if row['id'] in max_turn_ids]
        if len(max_turn_ids) != 1 or len(max_turns) != 1 or type(max_turns[0]) is not int:
            raise ValueError('Native turn event requires a unique maximum-turn rule')
        max_turn = max_turns[0]
        rule_values = {row['objectId']: next(item['value'] for item in state['rules']
                       if item['id'] == row['id']) for row in native['rules']
                       if any(item['id'] == row['id'] for item in state['rules'])}
        occupied_turns = {side: source_dialog_turns(script_graph, adapter['turn_variable'],
                          spec['camp'], rule_values) for side, spec in adapter['sides'].items()}
        seen_ids = set()
        seen_schedule = set()
        for row in requested_turn_events:
            required = {'id', 'side', 'turn', 'text'}
            if not isinstance(row, dict) or set(row) not in (required, required | {'secondaryText'}):
                raise ValueError('Native turn event creation has unknown or missing fields')
            identifier = row['id']
            side = row['side']
            turn = row['turn']
            localized = row['text']
            if (not isinstance(identifier, str)
                    or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                    or identifier in seen_ids or not isinstance(side, str)
                    or side not in adapter['sides']
                    or type(turn) is not int or not 1 <= turn <= max_turn
                    or not isinstance(localized, dict) or set(localized) != {'ru', 'en'}
                    or any(not isinstance(localized[language], str)
                           or not localized[language].strip() or len(localized[language]) > 5000
                           or '\x00' in localized[language] for language in ('ru', 'en'))):
                raise ValueError('Native turn event id, side, turn within campaign or RU/EN text is invalid')
            seen_ids.add(identifier)
            if turn in occupied_turns[side]:
                raise ValueError('Native turn event conflicts with an existing source dialog on that side and turn')
            if (side, turn) in seen_schedule:
                raise ValueError('Native turn events cannot share one side and turn')
            seen_schedule.add((side, turn))
            spec = adapter['sides'][side]
            secondary = row.get('secondaryText')
            if (len(spec['subtree']) == 12 and
                    (not isinstance(secondary, dict) or set(secondary) != {'ru', 'en'}
                     or any(not isinstance(secondary[language], str)
                            or not secondary[language].strip()
                            or len(secondary[language]) > 5000
                            or '\x00' in secondary[language]
                            for language in ('ru', 'en')))
                    or len(spec['subtree']) == 10 and secondary is not None):
                raise ValueError('Native portrait event requires two RU/EN text components')
            digest = hashlib.sha256((identity['scenario'] + ':turn-event:' + identifier).encode()).hexdigest()
            key = bytes.fromhex(digest[:16]).hex()
            secondary_key = bytes.fromhex(digest[16:32]).hex() if secondary else None
            sequence_export = '$/GDScript/AGF/TurnEvent/' + digest[:16]
            if (key in known_keys or secondary_key in known_keys
                    or sequence_export in script_graph['exports'].values()):
                raise ValueError('Private native turn event identity collides with source graph')
            known_keys.add(key)
            if secondary_key: known_keys.add(secondary_key)
            parent_actions = [item['object_id'] for item in
                property_wire(objects[spec['parent']], 'SubActions')['items']]
            turn_event_creations.append({**copy.deepcopy(row),
                'parentObjectId': spec['parent'], 'templateObjectId': spec['template'],
                'parentSourceActions': parent_actions,
                'sourceObjectCount': len(objects),
                'sourceSubtreeIds': spec['subtree'],
                'synthetic': spec.get('synthetic', False),
                'turnVariableObjectId': adapter['turn_variable'],
                'compareObjectId': spec['compare'], 'textObjectId': spec['text'],
                'variableObjectId': spec['variable'], 'playerObjectId': spec['player'],
                'conditionOrder': spec.get('condition_order', ['variable', 'player']),
                'campObjectId': spec['camp'], 'speaker': spec['speaker'],
                'textKey': key, 'secondaryKey': secondary_key,
                'secondaryTextObjectId': spec.get('secondary_text'),
                'textureObjectId': spec.get('texture'),
                'portraitToken': spec.get('portrait'),
                'sequenceExport': sequence_export})
    ai_target_edits = []
    requested_ai_target_edits = state['campaign']['nativeAiTargetEdits']
    if not isinstance(requested_ai_target_edits, list):
        raise ValueError('Native AI target edits must be a list')
    if requested_ai_target_edits:
        if script_graph is None:
            script_path = f"NDF/Scenarios/GDScript/{native['originalScenario']}.ndfbin"
            _, script_graph = decode(resource('scenario_definition', script_path).read_bytes())
        projection_path = _confined(snapshot, manifest['projection_file'])
        if sha256(projection_path.read_bytes()) != manifest['projection_sha256']:
            raise ValueError('Native AI target map projection changed')
        projection = json.loads(projection_path.read_text(encoding='utf-8'))
        points = {}
        for point in projection['map_points']:
            guid = point['addon_properties'].get('GUID', {}).get('hex')
            if point['kind'] == 'TGameDesignAddOn_Name' and guid:
                points.setdefault(guid, []).append(point)
        targets = {}
        bounds = state['world']['playableSubfield']['bounds']
        for obj in script_graph['objects']:
            if obj['class'] != 'TGDTagPosition':
                continue
            values = {prop['property_name']: prop['value'].get('value') for prop in obj['properties']}
            if any(type(values.get('GUID' + str(i))) is not int for i in range(1, 5)):
                continue
            guid = struct.pack('>4i', *(values['GUID' + str(i)] for i in range(1, 5))).hex()
            matches = points.get(guid, [])
            if (len(matches) == 1 and script_graph['exports'].get(obj['id'])
                    and bounds['minX'] <= matches[0]['position'][0] <= bounds['maxX']
                    and bounds['minY'] <= matches[0]['position'][1] <= bounds['maxY']):
                targets[obj['id']] = matches[0]
        seen_ai = set()
        for row in requested_ai_target_edits:
            _fields(row, ('objectId', 'nativeClass', 'propertyName', 'export',
                          'beforeTargetObjectId', 'afterTargetObjectId'), 'native AI target edit')
            object_id = row['objectId']
            if type(object_id) is not int or not 0 <= object_id < len(script_graph['objects']):
                raise ValueError('Native AI order object id is invalid')
            obj = script_graph['objects'][object_id]
            property_name = row['propertyName']
            allowed_field = {'TGDDescriptorStrategicMoveAndAttack': 'Positions',
                             'TGDDescriptorStrategicDefend': 'Position'}
            if (obj['class'] != row['nativeClass']
                    or allowed_field.get(obj['class']) != property_name
                    or script_graph['exports'].get(object_id) != row['export']
                    or (object_id, property_name) in seen_ai):
                raise ValueError('Native AI target has no verified order binding')
            seen_ai.add((object_id, property_name))
            props = [prop['value'] for prop in obj['properties'] if prop['property_name'] == property_name]
            if len(props) != 1:
                raise ValueError('Native AI order target property is ambiguous')
            wire = props[0]
            if property_name == 'Positions':
                if (wire['type'] != 'list' or len(wire['items']) != 1
                        or wire['items'][0]['type'] != 'obj_ref'):
                    raise ValueError('Native AI movement order requires one map target')
                before_id = wire['items'][0]['object_id']
            else:
                if wire['type'] != 'obj_ref':
                    raise ValueError('Native AI defence order target is not a map tag')
                before_id = wire['object_id']
            after_id = row['afterTargetObjectId']
            if (type(row['beforeTargetObjectId']) is not int or before_id != row['beforeTargetObjectId']
                    or type(after_id) is not int or after_id == before_id
                    or before_id not in targets or after_id not in targets):
                raise ValueError('Native AI target changed or has no matching playable map marker')
            ai_target_edits.append(copy.deepcopy(row))
    ai_order_creations = []
    requested_ai_order_creations = state['campaign']['nativeAiOrderCreations']
    if not isinstance(requested_ai_order_creations, list):
        raise ValueError('Native AI order creations must be a list')
    if requested_ai_order_creations:
        from .native_ai_creation import AI_CREATION_ADAPTERS, source_order_tag_ids
        from .native_frozen import native_spawn_identity

        adapter = AI_CREATION_ADAPTERS.get(native['originalScenario'])
        if adapter is None:
            raise ValueError('Native AI order creation has no pinned source script adapter')
        script_path = 'NDF/Scenarios/GDScript/' + native['originalScenario'] + '.ndfbin'
        script_raw = resource('scenario_definition', script_path).read_bytes()
        if sha256(script_raw) != adapter['sha256']:
            raise ValueError('Native AI order source script revision changed')
        if script_graph is None:
            _, script_graph = decode(script_raw)
        parent = script_graph['objects'][adapter['parent']]
        parent_actions = [item.get('object_id') for prop in parent['properties']
                          if prop['property_name'] == 'SubActions' and prop['value']['type'] == 'list'
                          for item in prop['value']['items']]
        if (parent['class'] != 'TGDDescriptorSimultaneous'
                or script_graph['exports'].get(parent['id']) != adapter['parent_export']
                or len(parent_actions) != adapter.get('source_action_count', len(parent_actions))
                or parent_actions != adapter.get('source_actions', parent_actions)
                or next((prop['value'].get('value') for prop in parent['properties']
                         if prop['property_name'] == 'NbExecutions'), None) != 1
                or not parent_actions):
            raise ValueError('Native AI order source startup action chain changed')
        if native['originalScenario'] == 'CampagneStrat_Highway':
            source_sequence = script_graph['objects'][723]
            if (source_sequence['class'] != 'TGDDescriptorSequential'
                    or [item.get('object_id') for prop in source_sequence['properties']
                        if prop['property_name'] == 'SubActions' for item in prop['value']['items']]
                        != [946, 947, 948]):
                raise ValueError('Native Highway AI order source action chain changed')
        for kind, template_id in (('attack', adapter['attack']), ('defend', adapter['defend'])):
            if template_id is None:
                continue
            template = script_graph['objects'][template_id]
            expected_class = ('TGDDescriptorStrategicMoveAndAttack' if kind == 'attack'
                              else 'TGDDescriptorStrategicDefend')
            props = {prop['property_name']: prop['value'] for prop in template['properties']}
            target_name = 'Positions' if kind == 'attack' else 'Position'
            target_wire = props.get(target_name)
            target_refs = (target_wire['items'] if kind == 'attack' and target_wire
                           and target_wire.get('type') == 'list' else
                           [target_wire] if target_wire is not None and kind == 'defend' else [])
            if (template['class'] != expected_class
                    or not {'Group', 'AttackEnemyInRadius', 'WaypointReachedRadius',
                            'ExecuteOnlyOnIAActivated', target_name} <= set(props)
                    or props['Group']['type'] != 'obj_ref'
                    or not target_refs
                    or any(ref['type'] != 'obj_ref'
                           or script_graph['objects'][ref['object_id']]['class'] != 'TGDTagPosition'
                           for ref in target_refs)):
                raise ValueError('Native AI order action template changed')
        projection_path = _confined(snapshot, manifest['projection_file'])
        if sha256(projection_path.read_bytes()) != manifest['projection_sha256']:
            raise ValueError('Native AI order source map projection changed')
        projection = json.loads(projection_path.read_text(encoding='utf-8'))
        map_points = {}
        for point in projection['map_points']:
            guid = point['addon_properties'].get('GUID', {}).get('hex')
            if point['kind'] == 'TGameDesignAddOn_Name' and guid:
                map_points.setdefault(guid, []).append(point)
        tags = {}
        bounds = state['world']['playableSubfield']['bounds']
        for obj in script_graph['objects']:
            if obj['class'] != 'TGDTagPosition':
                continue
            values = {prop['property_name']: prop['value'].get('value') for prop in obj['properties']}
            if any(type(values.get('GUID' + str(i))) is not int for i in range(1, 5)):
                continue
            guid = struct.pack('>4i', *(values['GUID' + str(i)] for i in range(1, 5))).hex()
            matches = map_points.get(guid, [])
            if (len(matches) == 1 and script_graph['exports'].get(obj['id'])
                    and bounds['minX'] <= matches[0]['position'][0] <= bounds['maxX']
                    and bounds['minY'] <= matches[0]['position'][1] <= bounds['maxY']):
                tags[obj['id']] = matches[0]
        stock_deployments = {row['id']: row for row in baseline['campaign']['deployments']}
        private_deployments = {row['id']: row for row in added_placements}
        names = {row['id']: row['export'] for row in native['entityBindings']
                 if row['kind'] == 'placement' and row.get('export')}
        source_placements = {}
        for point in projection['placements']:
            source_placements.setdefault(point['name'], []).append(point)
        source_order_tags = source_order_tag_ids(script_graph)
        seen_ai_ids = set()
        seen_ai_pawns = set()
        for row in requested_ai_order_creations:
            _fields(row, ('id', 'deploymentId', 'kind', 'targetObjectId',
                          'attackRadius', 'waypointRadius', 'aiOnly'), 'native AI order creation')
            identifier = row['id']
            if (not isinstance(identifier, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', identifier) is None
                    or identifier in seen_ai_ids):
                raise ValueError('Native AI order creation needs a unique short id')
            seen_ai_ids.add(identifier)
            deployment_id = row['deploymentId']
            if not isinstance(deployment_id, str):
                raise ValueError('Native AI order needs a source or private map deployment')
            if deployment_id in seen_ai_pawns:
                raise ValueError('Native AI creation supports one startup order per map pawn')
            seen_ai_pawns.add(deployment_id)
            is_private = deployment_id in private_deployments
            if not is_private and (deployment_id not in stock_deployments or deployment_id not in names):
                raise ValueError('Native AI order requires an imported stock deployment or new private map pawn')
            placement = (private_deployments if is_private else stock_deployments)[deployment_id]
            camp = camp_by_side[placement['side']]
            spawn = native_spawn_identity(identity['scenario'], deployment_id) if is_private else None
            name = spawn['name'] if spawn else names[deployment_id]
            tag_path = '$/GDScript/GdItems/Camp_' + str(camp) + '/' + name
            tag_ids = [index for index, path in script_graph['exports'].items() if path == tag_path]
            if is_private:
                if tag_ids:
                    raise ValueError('Private AI pawn tag collides with a source export')
                tag_id = None
            else:
                source_placement = source_placements.get(name, [])
                if (len(source_placement) != 1 or source_placement[0]['ranking'] != 'Camp_' + str(camp)
                        or len(tag_ids) != 1 or script_graph['objects'][tag_ids[0]]['class'] != 'TGDTagUnitGroup'):
                    raise ValueError('Native AI order stock pawn tag or coalition binding is ambiguous')
                guid_values = {prop['property_name']: prop['value'].get('value')
                               for prop in script_graph['objects'][tag_ids[0]]['properties']}
                if (any(type(guid_values.get('GUID' + str(i))) is not int for i in range(1, 5))
                        or struct.pack('>4i', *(guid_values['GUID' + str(i)] for i in range(1, 5))).hex()
                            != source_placement[0]['guid']):
                    raise ValueError('Native AI order pawn tag GUID differs from source map')
                tag_id = tag_ids[0]
                if tag_id in source_order_tags:
                    raise ValueError('Native AI pawn already belongs to the source startup order')
            kind = row['kind']
            template_id = adapter.get(kind)
            if (template_id is None or script_graph['objects'][template_id]['class'] !=
                    ('TGDDescriptorStrategicMoveAndAttack' if kind == 'attack'
                     else 'TGDDescriptorStrategicDefend')
                    or type(row['targetObjectId']) is not int or row['targetObjectId'] not in tags
                    or type(row['attackRadius']) is not int or not 0 <= row['attackRadius'] <= 100000
                    or type(row['waypointRadius']) is not int or not 1 <= row['waypointRadius'] <= 100000
                    or type(row['aiOnly']) is not bool):
                raise ValueError('Native AI order kind, target or behavior is invalid')
            digest = hashlib.sha256((identity['scenario'] + ':ai-order:' + identifier).encode()).hexdigest()[:16]
            ai_order_creations.append({**copy.deepcopy(row), 'sourceTagObjectId': tag_id,
                'newPlacement': is_private,
                'spawnTagExport': tag_path if is_private else None,
                'spawnGuid': spawn['guid'] if spawn else None,
                'campIndex': camp, 'parentObjectId': parent['id'],
                'parentSourceActions': parent_actions,
                'sourceObjectCount': len(script_graph['objects']),
                'templateObjectId': template_id,
                'sequenceExport': '$/GDScript/AGF/AI/' + digest,
                'orderExport': '$/GDScript/AGF/AIAction/' + digest})
    terrain = state['world']['terrain']
    height = _confined(source, terrain['heightmapPath'])
    surface = _confined(source, terrain['surfacePath'])
    height_changed = not _image_equal(resource('map_details', 'HeightMap.png'), height, 'I')
    surface_changed = not _image_equal(resource('map_details', 'Div_map.webp'), surface, 'RGB')
    world_changes = [change for change in changes if change['path'][0] in {'world', 'map_name', 'grid', 'playable_polygons'}
                     and change['path'][:2] != ['world', 'mapFeatures']]
    result = {'format': 'agf-native-editor-compiled/v1', 'source_root': str(source), 'identity': identity,
              'original_scenario': native['originalScenario'], 'snapshot': str(snapshot),
              'source_manifest_sha256': sha256(manifest_path.read_bytes()),
              'entity_bindings': native['entityBindings'],
              'state': copy.deepcopy(state), 'baseline': copy.deepcopy(baseline),
              'rule_edits': rule_edits, 'placement_edits': placements, 'battalion_edits': battalion_edits,
              'script_edits': script_edits,
              'production_edits': production_edits,
              'production_position_edits': production_position_edits,
              'reinforcement_creations': reinforcement_creations,
              'production_creations': production_creations,
              'event_text_edits': event_text_edits,
              'turn_event_creations': turn_event_creations,
              'ai_target_edits': ai_target_edits,
              'ai_order_creations': ai_order_creations,
              'map_feature_edits': map_feature_edits,
              'added_map_labels': added_map_labels,
              'added_placements': added_placements,
              'camp_by_side': camp_by_side,
              'frozen_deployments': frozen_deployments,
              'action_point_deployments': action_point_deployments,
              'initial_readiness_deployments': initial_readiness_deployments,
              'world_changes': world_changes, 'heightmap_changed': height_changed, 'surface_changed': surface_changed,
              'changes': changes, 'runtime_verified': False}
    if destination is not None:
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        (destination / 'native-campaign.compiled.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
