"""Template-independent authoring model for Army General campaigns.

Campaign authors describe only game content and map coordinates.  A map
profile owns every template-specific spawn name, GUID and script object id.
The compiled document is the boundary between the public YAML format and a
binary adapter such as the Bruderkrieg adapter.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path

import yaml

from .storage import sha256
from .strategic_grid import StrategicGrid
from .strategic_map_contract import StrategicMapContract


SCHEMA = 1
SIDES = {"nato", "pact"}
AI_ORDERS = {"attack", "defend", "counterattack", "hold", "move_to", "reserve", "support", "air_support"}
_ID = re.compile(r"[a-z][a-z0-9_]*\Z")
_GUID_NAMESPACE = uuid.UUID("712f2b7e-6e84-50e5-985d-8929f37b83c7")


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"Duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def _read_yaml(path):
    path = Path(path).resolve()
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise ValueError(f"Invalid YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return value


def _exact(value, keys, where, *, optional=()):
    if not isinstance(value, dict) or not set(keys) <= set(value) or not set(value) <= set(keys) | set(optional):
        missing = sorted(set(keys) - set(value or ()))
        extra = sorted(set(value or ()) - set(keys) - set(optional))
        raise ValueError(f"{where} fields mismatch; missing={missing}, extra={extra}")


def _identifier(value, where):
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{where} must be a lowercase identifier")
    return value


def _side(value, where):
    if value not in SIDES:
        raise ValueError(f"{where} must be nato or pact")
    return value


def _number(value, where, minimum=None):
    if type(value) not in (int, float):
        raise ValueError(f"{where} must be a number")
    if minimum is not None and value < minimum:
        raise ValueError(f"{where} must be at least {minimum}")
    return value


def _point(value, where, bounds):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(item) not in (int, float) for item in value)):
        raise ValueError(f"{where} must be [x, y]")
    x, y = map(float, value)
    if not (bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]):
        raise ValueError(f"{where} is outside the map profile bounds")
    return [x, y]


def _guid(kind, campaign_id, item_id):
    return uuid.uuid5(_GUID_NAMESPACE, f"{campaign_id}:{kind}:{item_id}").hex


def _label_token(campaign_id, item_id):
    digest = hashlib.sha256(f"{campaign_id}:label:{item_id}".encode("utf-8")).hexdigest()
    return "AG" + digest[:8].upper()


def _load_battalions(root):
    folder = root / "battalions"
    paths = sorted(folder.glob("*.yaml")) if folder.is_dir() else []
    if not paths:
        raise ValueError("Campaign has no battalions/*.yaml files")
    rows = []
    for path in paths:
        doc = _read_yaml(path)
        _exact(doc, {"schema", "battalions"}, path.name)
        if doc["schema"] != SCHEMA or not isinstance(doc["battalions"], list):
            raise ValueError(f"Unsupported battalion schema: {path}")
        rows.extend(copy.deepcopy(doc["battalions"]))
    ids = set()
    for number, row in enumerate(rows):
        where = f"battalion[{number}]"
        if not isinstance(row, dict):
            raise ValueError(f"{where} must be a mapping")
        required = {"id", "side", "definition"}
        if set(row) != required:
            raise ValueError(f"{where} fields must be {sorted(required)}")
        item_id = _identifier(row["id"], f"{where}.id")
        _side(row["side"], f"{where}.side")
        if item_id in ids:
            raise ValueError(f"Duplicate battalion id: {item_id}")
        ids.add(item_id)
        definition = row["definition"]
        full_fields = {"name", "organization", "companies", "strategic"}
        localized_fields = {"name_text", "organization_text"}
        optional_fields = localized_fields | {"formation", "initial_state"}
        fields = set(definition) if isinstance(definition, dict) else set()
        if (not isinstance(definition, dict)
                or fields != {"catalog"} and not any(
                    base <= fields <= base | optional_fields
                    for base in (full_fields | {"catalog"}, full_fields | {"country"}))):
            raise ValueError(f"{where}.definition must use either explicit country or one catalog entry")
        for field in localized_fields & fields:
            text = definition[field]
            if (not isinstance(text, dict) or set(text) != {'ru', 'en'}
                    or any(not isinstance(value, str) or not value.strip()
                           or len(value.encode('utf-16-le')) // 2 > 30
                           for value in text.values())):
                raise ValueError(f"{where}.definition.{field} requires short RU/EN text")
        if 'catalog' in definition and not isinstance(definition['catalog'], str):
            raise ValueError(f"{where}.definition.catalog must select one catalog entry")
        if 'country' in definition and (not isinstance(definition['country'], str)
                or re.fullmatch(r'[A-Z]{2,3}', definition['country']) is None):
            raise ValueError(f"{where}.definition.country must be a country code")
        if 'formation' in definition:
            formation = definition['formation']
            _exact(formation, {'division_id', 'division_text', 'regiment_id'},
                   f'{where}.definition.formation', optional={'emblem'})
            _identifier(formation['division_id'], f'{where}.formation.division_id')
            _identifier(formation['regiment_id'], f'{where}.formation.regiment_id')
            _exact(formation['division_text'], {'ru', 'en'}, f'{where}.formation.division_text')
            if any(not isinstance(value, str) or not value.strip()
                   or len(value.encode('utf-16-le')) // 2 > 30
                   for value in formation['division_text'].values()):
                raise ValueError(f'{where}.formation.division_text requires short RU/EN text')
            if 'emblem' in formation and (not isinstance(formation['emblem'], str)
                    or re.fullmatch(r'Texture_Division_Emblem_[A-Za-z0-9_]+',
                                    formation['emblem']) is None):
                raise ValueError(f'{where}.formation.emblem must name a division emblem')
        if 'initial_state' in definition:
            state = definition['initial_state']
            _exact(state, set(), f'{where}.definition.initial_state', optional={'fatigue', 'action_points'})
            if not state:
                raise ValueError('initial_state must declare at least one value')
            if 'fatigue' in state and (type(state['fatigue']) is not int or not 0 <= state['fatigue'] <= 8):
                raise ValueError(f'{where}.definition.initial_state.fatigue must be 0..8')
            if 'action_points' in state and (type(state['action_points']) is not int or not 0 <= state['action_points'] <= 12):
                raise ValueError(f'{where}.definition.initial_state.action_points must be 0..12')
    return rows


def _compile_oob(row, campaign_id, catalog, pack_signatures):
    """Use a schema shell, replacing all company/platoon content and names."""
    from .modgen import _ui_text
    if 'country' not in catalog or 'side' not in catalog:
        raise ValueError('Full battalion requires explicit country and side in the map catalog')
    if catalog['side'] != row["side"]:
        raise ValueError("Battalion catalog coalition does not match its side")
    result = {'coalition': catalog['side'].upper(), 'country': catalog['country']}
    result.update(mode='authored', role='authored_campaign')
    result['organization'] = {'superior': None, 'texture': 'UIBackgroundTexture_regiment'}
    definition = row["definition"]
    from .pawn import validate_strategy
    validate_strategy(definition["strategic"])
    result["strategic"] = copy.deepcopy(definition["strategic"])
    identity = "AGF_" + hashlib.sha256(f"{campaign_id}:{row['id']}".encode()).hexdigest()[:16]
    def token(*parts):
        return "AG" + hashlib.sha256(":".join((identity, *parts)).encode()).hexdigest()[:8].upper()
    def name(value):
        if not _ui_text(value):
            raise ValueError("Battalion, organization, company and platoon names must fit 30 UTF-16 units")
        return value
    result.update(id=identity, deck_id=identity, unit_export="Descriptor_Unit_" + identity,
                  deck_export="Descriptor_Deck_" + identity,
                  division="Descriptor_Deck_Division_" + identity,
                  name=name(definition["name"]), name_token=token("battalion"))
    if 'name_text' in definition:
        result['localized_name'] = copy.deepcopy(definition['name_text'])
    result["organization"].update(export=identity + "_Subordination",
                                  name=name(definition["organization"]), name_token=token("organization"))
    if 'organization_text' in definition:
        result['organization']['localized_name'] = copy.deepcopy(definition['organization_text'])
    result['division_definition'] = {
        'id': identity, 'name': name(definition['organization']), 'name_token': token('organization'),
        'coalition': result['coalition'],
        'emblem': ('Texture_Division_Emblem_RFA_TerrKdo_Sud' if row['side'] == 'nato'
                   else 'Texture_Division_Emblem_RDA_KDA_Erfurt'),
    }
    if 'formation' in definition:
        formation = definition['formation']
        division_id = 'AGF_' + hashlib.sha256(
            f"{campaign_id}:{row['side']}:division:{formation['division_id']}".encode()).hexdigest()[:16]
        regiment_id = 'AGF_' + hashlib.sha256(
            f"{campaign_id}:{row['side']}:regiment:{formation['regiment_id']}".encode()).hexdigest()[:16]
        division_token = 'AG' + hashlib.sha256((division_id + ':name').encode()).hexdigest()[:8].upper()
        regiment_token = 'AG' + hashlib.sha256((regiment_id + ':name').encode()).hexdigest()[:8].upper()
        command_export = division_id + '_Command'
        division_name = name(formation['division_text']['ru'])
        result['division'] = 'Descriptor_Deck_Division_' + division_id
        result['division_definition'].update(id=division_id, name=division_name,
                                             name_token=division_token,
                                             localized_name=copy.deepcopy(formation['division_text']))
        if 'emblem' in formation:
            result['division_definition']['emblem'] = formation['emblem']
        result['command'] = {'export': command_export, 'name': division_name,
                             'localized_name': copy.deepcopy(formation['division_text']),
                             'name_token': division_token, 'superior': None,
                             'texture': 'UIBackgroundTexture_division'}
        result['organization'].update(export=regiment_id + '_Subordination',
                                      name_token=regiment_token, superior=command_export)
        result['formation'] = {'division_id': formation['division_id'],
                               'regiment_id': formation['regiment_id']}
    result["state"] = {"fatigue": 0, "action_points": {"initial": 12, "recovery": 12},
                       "frozen_turns": 0, "casualties": {"count": 0, "random_range": 0, "type": 1}}
    if 'initial_state' in definition:
        result['state']['fatigue'] = definition['initial_state'].get('fatigue', 0)
        if 'action_points' in definition['initial_state']:
            ap = definition['initial_state']['action_points']
            result['state']['action_points'] = {'initial':ap, 'recovery':ap}
    if result['strategic']['type'] == 'airplane':
        result['state']['action_points'] = {'initial': 4, 'recovery': 4}
    companies = definition["companies"]
    if not isinstance(companies, list) or not companies:
        raise ValueError("Authored battalion must have companies")
    result["companies"] = []
    seen = set()
    for company in companies:
        _exact(company, {"id", "name", "hq", "platoons"}, "company",optional={'name_text'})
        cid = _identifier(company["id"], "company.id")
        if cid in seen or type(company["hq"]) is not bool:
            raise ValueError("Duplicate company id or invalid HQ flag")
        seen.add(cid)
        output = {"id": cid, "name": name(company["name"]), "hq": company["hq"],
                  "name_token": token(cid), "platoons": []}
        if 'name_text' in company:
            _exact(company['name_text'],{'ru','en'},'company.name_text')
            if any(not _ui_text(v) for v in company['name_text'].values()):raise ValueError('Invalid localized company name')
            output['localized_name']=copy.deepcopy(company['name_text'])
        if not isinstance(company["platoons"], list) or not company["platoons"]:
            raise ValueError("Company must have platoons")
        platoon_ids = set()
        for platoon in company["platoons"]:
            _exact(platoon, {"id", "name", "hq", "units"}, "platoon",optional={'name_text'})
            pid = _identifier(platoon["id"], "platoon.id")
            if pid in platoon_ids or type(platoon["hq"]) is not bool:
                raise ValueError("Duplicate platoon id or invalid HQ flag")
            platoon_ids.add(pid)
            packs = []
            if not isinstance(platoon["units"], list) or not platoon["units"]:
                raise ValueError("Platoon must have units")
            for unit in platoon["units"]:
                _exact(unit, {"type", "count"}, "unit")
                if (not isinstance(unit["type"], str) or not re.fullmatch(r"[A-Za-z0-9_]+", unit["type"])
                        or type(unit["count"]) is not int or not 1 <= unit["count"] <= 100):
                    raise ValueError("Invalid strategic unit type or count")
                pack_name = "Descriptor_StrategicPack_" + unit["type"]
                if pack_name not in pack_signatures:
                    raise ValueError("Unknown strategic unit type: " + unit["type"])
                if result['strategic']['type'] == 'airplane':
                    from .visual_catalog import current_visual_catalog
                    signature = pack_signatures[pack_name]
                    identifier = signature['unit'].rsplit('Descriptor_Unit_', 1)[-1]
                    visual = current_visual_catalog().get(identifier, {})
                    required_tags = {'fighter': {'Avion_Chasseur'},
                                     'bomber': {'Avion_Bombardier','Avion_AT'},
                                     'sead': {'Avion_SEAD'}}[result['strategic']['aircraft_role']]
                    if (visual.get('category') != 'airplane' or signature['transport']
                            or not required_tags.intersection(visual.get('tags', []))):
                        raise ValueError('Invalid aircraft roster for declared role: ' + unit['type'])
                packs.append({"pack": pack_name, "count": unit["count"],
                              "signature": pack_signatures[pack_name]})
            prepared={"id": pid, "name": name(platoon["name"]),
                      "hq": platoon["hq"], "name_token": token(cid, pid), "packs": packs}
            if 'name_text' in platoon:
                _exact(platoon['name_text'],{'ru','en'},'platoon.name_text')
                if any(not _ui_text(v) for v in platoon['name_text'].values()):raise ValueError('Invalid localized platoon name')
                prepared['localized_name']=copy.deepcopy(platoon['name_text'])
            output["platoons"].append(prepared)
        result["companies"].append(output)
    return result


def _load_profile(path):
    profile = _read_yaml(path)
    optional = {field for field in ('registration', 'strategic_map') if field in profile}
    _exact(profile, {"schema", "id", "template", "bounds", "capacity", "slots", "script",
                     "battalion_catalog", "event_images"} | optional, "map profile")
    if profile["schema"] != SCHEMA:
        raise ValueError("Unsupported map profile schema")
    _identifier(profile["id"], "profile.id")
    if profile.get('registration', 'legacy_slots') not in {'legacy_slots', 'dynamic'}:
        raise ValueError('profile.registration must be legacy_slots or dynamic')
    if 'strategic_map' in profile:
        strategic_map = StrategicMapContract.from_config(profile['strategic_map'])
        if list(strategic_map.bounds) != [float(value) for value in profile['bounds']]:
            raise ValueError('profile bounds differ from strategic map bounds')
    bounds = profile["bounds"]
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(type(item) not in (int, float) for item in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError("profile.bounds must be [min_x, min_y, max_x, max_y]")
    capacity = profile["capacity"]
    _exact(capacity, {"initial_per_side", "flags", "influence_sources", "labels", "runtime_positions"}, "profile.capacity")
    if any(type(value) is not int or value < 0 for value in capacity.values()):
        raise ValueError('profile.capacity values must be nonnegative integers')
    slots = profile["slots"]
    _exact(slots, {"spawns", "flags", "influence_sources", "labels", "runtime_positions"}, "profile.slots")
    _exact(slots["spawns"], SIDES, "profile.slots.spawns")
    dynamic = profile.get('registration', 'legacy_slots') == 'dynamic'
    for side in SIDES:
        if (not isinstance(slots["spawns"][side], list)
                or (not dynamic and len(slots["spawns"][side]) < capacity["initial_per_side"])):
            raise ValueError(f"profile has too few {side} spawn slots")
    for kind in ("flags", "influence_sources", "labels", "runtime_positions"):
        if not isinstance(slots[kind], list) or (not dynamic and len(slots[kind]) < capacity[kind]):
            raise ValueError(f"profile has too few {kind} slots")
    catalog = profile["battalion_catalog"]
    if not isinstance(catalog, dict):
        raise ValueError("profile.battalion_catalog must be a mapping")
    for name, row in catalog.items():
        if (not isinstance(name, str) or not isinstance(row, dict)
                or set(row) not in ({"unit_export", "authored"}, {"unit_export", "authored", "country", "side"})
                or not isinstance(row["unit_export"], str)
                or not row["unit_export"].startswith("Descriptor_Unit_")
                or type(row["authored"]) is not bool):
            raise ValueError(f"Invalid battalion catalog entry: {name}")
        if 'country' in row:
            if (not isinstance(row['country'], str) or re.fullmatch(r'[A-Z]{2,3}', row['country']) is None
                    or row['side'] not in SIDES):
                raise ValueError(f"Invalid battalion catalog country or side: {name}")
    if (not isinstance(profile["event_images"], dict)
            or any(not isinstance(name, str) or not isinstance(value, str) or not value
                   for name, value in profile["event_images"].items())):
        raise ValueError("profile.event_images must map logical names to engine assets")
    return profile


def _load_part(root, name, keys):
    value = _read_yaml(root / name)
    _exact(value, keys, name)
    if value["schema"] != SCHEMA:
        raise ValueError(f"Unsupported schema in {name}")
    return value


def _validate_public_surface(documents):
    """Reject template internals from every public campaign YAML document."""
    forbidden = {"guid", "object_id", "source_spawn", "spawn_slot", "template_object"}

    def visit(value, path):
        if isinstance(value, dict):
            for key, nested in value.items():
                if str(key).casefold() in forbidden:
                    raise ValueError(f"Template-specific field is forbidden in campaign YAML: {path}.{key}")
                visit(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")

    for name, document in documents.items():
        visit(document, name)


def compile_campaign(source, profile_path, destination=None):
    """Validate and resolve one authored campaign against a map adapter.

    The returned structure is deterministic and contains template internals
    only under ``adapter``.  It can therefore be audited before any binary is
    touched and used as the sole input to a map-specific binary compiler.
    """
    root = Path(source).resolve()
    campaign = _read_yaml(root / "campaign.yaml")
    _exact(campaign, {
        "schema", "id", "template", "title", "summary", "turns", "date",
        "score_to_win", "sides"
    }, 'campaign.yaml', optional={'ai_policy', 'victory', 'menu','capture_deadline'})
    if campaign['schema'] != SCHEMA:
        raise ValueError('Unsupported campaign schema')
    map_doc = _read_yaml(root / "map.yaml")
    _exact(map_doc, {"schema", "influence_sources", "flags", "labels"} | ({"strategic_grid", "markers", "waypoints"} & set(map_doc)), "map.yaml")
    if map_doc["schema"] != SCHEMA:
        raise ValueError("Unsupported schema in map.yaml")
    if 'markers' in map_doc:
        if not isinstance(map_doc['markers'], list):
            raise ValueError('Map markers must be a list')
        for marker in map_doc['markers']:
            _exact(marker, {'id', 'name', 'position'}, 'map marker')
            _identifier(marker['id'], 'marker.id')
            if not isinstance(marker['name'], str) or not marker['name'].strip():
                raise ValueError('Map marker requires a name')
            map_doc['labels'].append({'id': marker['id'], 'position': marker['position'],
                                      'text': {'ru': marker['name'], 'en': marker['name']}, 'size': 'small'})
    deployments_doc = _load_part(root, "deployments.yaml", {"schema", "deployments"})
    reinforcements_doc = _load_part(root, "reinforcements.yaml", {"schema", "reinforcements"})
    events_doc = _load_part(root, "events.yaml", {"schema", "events"})
    cinematics_doc = (_read_yaml(root / 'cinematics.yaml')
                      if (root / 'cinematics.yaml').is_file() else None)
    ai_doc = _load_part(root, "ai.yaml", {"schema", "orders"})
    battalions = _load_battalions(root)
    custom_packs_doc = (_read_yaml(root / 'packs.yaml') if (root / 'packs.yaml').is_file()
                        else {'schema': SCHEMA, 'packs': []})
    _exact(custom_packs_doc, {'schema', 'packs'}, 'packs.yaml')
    if custom_packs_doc['schema'] != SCHEMA or not isinstance(custom_packs_doc['packs'], list):
        raise ValueError('Invalid strategic packs document')
    from .modgen import strategic_pack_signatures, is_tactical_transport
    from .visual_catalog import current_visual_catalog
    pack_signatures = dict(strategic_pack_signatures())
    unit_catalog = current_visual_catalog() if custom_packs_doc['packs'] else {}
    custom_packs = []
    for row in custom_packs_doc['packs']:
        _exact(row, {'id', 'unit', 'transport', 'experience', 'number'}, 'custom strategic pack')
        if (any(not isinstance(row[key], str) or re.fullmatch(r'[A-Za-z0-9_]+', row[key]) is None
                for key in ('id', 'unit'))
                or row['unit'] not in unit_catalog
                or row['transport'] is not None and (not isinstance(row['transport'], str)
                    or row['transport'] not in unit_catalog
                    or not is_tactical_transport(row['transport']))
                or type(row['experience']) is not int or not 0 <= row['experience'] <= 3
                or type(row['number']) is not int or not 1 <= row['number'] <= 10):
            raise ValueError('Invalid custom strategic pack unit, transport or experience')
        name = 'Descriptor_StrategicPack_' + row['id']
        if name in pack_signatures:
            raise ValueError('Custom strategic pack duplicates an existing pack: ' + row['id'])
        pack_signatures[name] = {
            'unit': '$/GFX/Unit/Descriptor_Unit_' + row['unit'],
            'transport': ('$/GFX/Unit/Descriptor_Unit_' + row['transport']) if row['transport'] else '',
            'experience': row['experience'], 'number': row['number']}
        custom_packs.append(copy.deepcopy(row))
    production_doc = (_read_yaml(root / "production.yaml") if (root / "production.yaml").is_file()
                      else {"schema": 1, "deployment_points": [], "divisions": [], "groups": []})
    aviation_doc = (_read_yaml(root / 'aviation.yaml') if (root / 'aviation.yaml').is_file()
                    else {'schema': 1, 'airfields': [], 'wings': []})
    public_docs = {
        "campaign": campaign, "map": map_doc, "deployments": deployments_doc,
        "reinforcements": reinforcements_doc, "events": events_doc,
        "ai": ai_doc, "battalions": battalions, "production": production_doc, 'aviation': aviation_doc,
        'custom_packs': custom_packs,
        **({'cinematics': cinematics_doc} if cinematics_doc is not None else {}),
    }
    _validate_public_surface(public_docs)
    profile = _load_profile(profile_path)
    from .cinematics import compile_cinematics
    cinematics = compile_cinematics(cinematics_doc, profile['event_images'])
    from .division_emblems import declared_emblems
    emblems = declared_emblems(root)
    custom_emblems = {row['token'] for row in emblems}
    for row in battalions:
        emblem = row['definition'].get('formation', {}).get('emblem', '')
        if emblem.startswith('Texture_Division_Emblem_AGF_') and emblem not in custom_emblems:
            raise ValueError('Campaign battalion references an undeclared custom emblem: ' + emblem)
    dynamic = profile.get('registration', 'legacy_slots') == 'dynamic'
    def slot(kind, item_id, number, supports_frozen=False):
        if not dynamic:
            return copy.deepcopy(profile['slots'][kind][number])
        suffix = _guid('adapter-slot-' + kind, campaign['id'], item_id)[:16]
        return {'name': 'AGFW_' + kind + '_' + suffix,
                'supports_frozen': supports_frozen, 'dynamic': True}
    for number, row in enumerate(battalions):
        if 'country' in row['definition']:
            row['oob'] = _compile_oob(row, campaign['id'], {
                'country': row['definition']['country'], 'side': row['side'],
            }, pack_signatures)
            row['unit_export'] = row['oob']['unit_export']
            continue
        catalog_id = row["definition"]["catalog"]
        if catalog_id not in profile["battalion_catalog"]:
            raise ValueError(f"Unknown battalion catalog entry: {catalog_id}")
        catalog = profile["battalion_catalog"][catalog_id]
        if not catalog["authored"]:
            raise ValueError(f"Technical scenario rejects stock-derived battalion: {catalog_id}")
        row["unit_export"] = catalog["unit_export"]
        if "companies" in row["definition"]:
            row["oob"] = _compile_oob(row, campaign["id"], catalog, pack_signatures)
            row["unit_export"] = row["oob"]["unit_export"]
    campaign_id = _identifier(campaign["id"], "campaign.id")
    if campaign["template"] != profile["id"]:
        raise ValueError("Campaign template does not match map profile")
    if type(campaign["turns"]) is not int or campaign["turns"] < 2:
        raise ValueError("campaign.turns must be an integer >= 2")
    if type(campaign["score_to_win"]) is not int or campaign["score_to_win"] < 1:
        raise ValueError("campaign.score_to_win must be a positive integer")
    if (not isinstance(campaign["date"], list) or len(campaign["date"]) != 4
            or any(type(item) is not int for item in campaign["date"])):
        raise ValueError("campaign.date must be [year, month, day, period]")
    _exact(campaign["sides"], SIDES, "campaign.sides")
    for side in SIDES:
        side_doc = campaign["sides"][side]
        _exact(side_doc, {"countries", "playable"}, f"campaign.sides.{side}")
        if not isinstance(side_doc["countries"], list) or not side_doc["countries"]:
            raise ValueError(f"campaign.sides.{side}.countries must not be empty")
        if type(side_doc["playable"]) is not bool:
            raise ValueError(f"campaign.sides.{side}.playable must be boolean")
        if not side_doc["playable"]:
            raise ValueError("This map adapter requires both coalitions to be playable")
    for row in battalions:
        if "oob" in row and row["oob"]["country"] not in campaign["sides"][row["side"]]["countries"]:
            raise ValueError("Battalion country is outside its coalition's configured countries")

    bounds = list(map(float, profile["bounds"]))
    if 'strategic_map' in profile:
        bounds = list(map(float, profile['strategic_map'].get('playable_bounds', bounds)))
    strategic_grid = (StrategicGrid.from_config(map_doc["strategic_grid"])
                      if "strategic_grid" in map_doc else None)
    if strategic_grid is not None and 'strategic_map' in profile:
        from .strategic_map_package import authored_native_tiles
        authored_native_tiles(profile['strategic_map'], strategic_grid.as_dict())
    battalion_by_id = {row["id"]: row for row in battalions}

    def require_ground_battalion(identifier, where):
        if battalion_by_id[identifier].get('oob', {}).get('strategic', {}).get('type') == 'airplane':
            raise ValueError(f"{where}: aircraft must be bound through aviation.yaml")

    deployments = deployments_doc["deployments"]
    if not isinstance(deployments, list):
        raise ValueError("deployments must be a list")
    seen_deployments = set()
    side_counts = {side: 0 for side in SIDES}
    unused_slots = {side: copy.deepcopy(profile["slots"]["spawns"][side]) for side in SIDES}
    resolved_deployments = []
    for number, row in enumerate(deployments):
        where = f"deployment[{number}]"
        fields = {"id", "battalion", "side", "position", "fatigue", "action_points", "frozen_turns"}
        if isinstance(row, dict) and "initial_losses" in row:
            fields.add("initial_losses")
        _exact(row, fields, where)
        losses = row.get("initial_losses", {"budget": 0, "random_range": 0})
        if isinstance(losses, dict) and set(losses) == {'max_percent'}:
            from .losses import bounded_loss_budget, roster_ticket_costs
            battalion = battalion_by_id.get(row['battalion'], {})
            if 'oob' not in battalion:
                raise ValueError(where + '.initial_losses requires an explicit authored roster')
            losses = {'budget': bounded_loss_budget(roster_ticket_costs(battalion['oob']),
                                                    losses['max_percent']), 'random_range': 0}
        _exact(losses, {"budget", "random_range"}, where + ".initial_losses")
        if (any(type(value) is not int for value in losses.values())
                or not 0 <= losses["random_range"] <= losses["budget"]
                or losses["budget"] + losses["random_range"] > 2**31 - 1):
            raise ValueError(f"{where}.initial_losses requires a non-negative int32 budget and valid random range")
        deployment_id = _identifier(row["id"], f"{where}.id")
        if deployment_id in seen_deployments:
            raise ValueError(f"Duplicate deployment id: {deployment_id}")
        seen_deployments.add(deployment_id)
        if row["battalion"] not in battalion_by_id:
            raise ValueError(f"Unknown battalion in {where}: {row['battalion']}")
        require_ground_battalion(row['battalion'], where)
        side = _side(row["side"], f"{where}.side")
        if battalion_by_id[row["battalion"]]["side"] != side:
            raise ValueError(f"Battalion side mismatch in {where}")
        state = {
            "fatigue": int(_number(row["fatigue"], f"{where}.fatigue", 0)),
            "action_points": int(_number(row["action_points"], f"{where}.action_points", 0)),
            "frozen_turns": int(_number(row["frozen_turns"], f"{where}.frozen_turns", 0)),
        }
        if any(type(row[key]) is not int for key in state):
            raise ValueError("Fatigue, action points and frozen turns must be integers")
        if state["fatigue"] > 8:
            raise ValueError(f"{where}.fatigue exceeds WARNO's strategic scale")
        choices = unused_slots[side]
        if dynamic:
            slot_value = slot('spawns', row['id'], side_counts[side],
                              supports_frozen=bool(state['frozen_turns']))
        elif not choices:
            raise ValueError(f"Map profile has no free {side} spawn slot")
        # Reserve scarce frozen-capable shells for formations that need the
        # template's proven countdown/AP restore wiring.
        if not dynamic:
            if state["frozen_turns"]:
                match = next((i for i, item in enumerate(choices) if item.get("supports_frozen")), None)
                if match is None:
                    raise ValueError(f"Map profile has no free frozen-capable {side} spawn slot")
            else:
                match = next((i for i, item in enumerate(choices) if not item.get("supports_frozen")), 0)
            slot_value = choices.pop(match)
        side_counts[side] += 1
        resolved_deployments.append({
            **copy.deepcopy(row), "position": _point(row["position"], f"{where}.position", bounds),
            "state": state, "initial_losses": copy.deepcopy(losses),
            "unit_export": battalion_by_id[row["battalion"]]["unit_export"],
            "adapter_slot": copy.deepcopy(slot_value),
        })
    for side, count in side_counts.items():
        if (not dynamic and not 3 <= count <= profile["capacity"]["initial_per_side"]):
            raise ValueError(f"Technical scenario requires 3..{profile['capacity']['initial_per_side']} initial {side} battalions")

    flags = map_doc["flags"]
    if not isinstance(flags, list) or not flags:
        raise ValueError("map.flags must not be empty")
    if not dynamic and len(flags) > profile["capacity"]["flags"]:
        raise ValueError("Campaign exceeds map-profile flag capacity")
    flag_ids = set()
    resolved_flags = []
    for number, row in enumerate(flags):
        where = f"flag[{number}]"
        _exact(row, {"id", "position", "initial_owner", "capture_score", "hold_score", "name"}, where)
        item_id = _identifier(row["id"], f"{where}.id")
        if item_id in flag_ids:
            raise ValueError(f"Duplicate flag id: {item_id}")
        flag_ids.add(item_id)
        owner = row["initial_owner"]
        if owner is not None:
            _side(owner, f"{where}.initial_owner")
        for key in ("capture_score", "hold_score"):
            if type(row[key]) is not int or row[key] < 0:
                raise ValueError(f"{where}.{key} must be a non-negative integer")
        resolved_flags.append({
            **copy.deepcopy(row), "position": _point(row["position"], f"{where}.position", bounds),
            "guid": _guid("flag", campaign_id, item_id),
            "adapter_slot": slot('flags', item_id, number),
        })

    influence = map_doc["influence_sources"]
    if not isinstance(influence, list) or not influence:
        raise ValueError("map.influence_sources must not be empty")
    if not dynamic and len(influence) > profile["capacity"]["influence_sources"]:
        raise ValueError("Campaign exceeds map-profile influence-source capacity")
    resolved_influence = []
    for number, row in enumerate(influence):
        where = f"influence_source[{number}]"
        _exact(row, {"side", "position", "value"}, where)
        resolved_influence.append({
            "side": _side(row["side"], f"{where}.side"),
            "position": _point(row["position"], f"{where}.position", bounds),
            "value": float(_number(row["value"], f"{where}.value", 0)),
            "adapter_slot": slot('influence_sources', str(number), number),
        })
    for flag in resolved_flags:
        if flag["initial_owner"] is None:
            continue
        ranked = sorted(
            ((source["position"][0] - flag["position"][0]) ** 2
             + (source["position"][1] - flag["position"][1]) ** 2,
             source["side"])
            for source in resolved_influence)
        if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
            raise ValueError(f"flag[{flag['id']}] has ambiguous initial influence")
        if ranked[0][1] != flag["initial_owner"]:
            raise ValueError(f"flag[{flag['id']}] initial_owner conflicts with influence sources")

    labels = map_doc["labels"]
    if not isinstance(labels, list) or (not dynamic and len(labels) > profile["capacity"]["labels"]):
        raise ValueError("Campaign exceeds map-profile label capacity")
    resolved_labels = []
    label_ids = set()
    for number, row in enumerate(labels):
        where = f"label[{number}]"
        _exact(row, {"id", "position", "text", "size"}, where)
        item_id = _identifier(row["id"], f"{where}.id")
        if item_id in label_ids:
            raise ValueError(f"Duplicate map label id: {item_id}")
        label_ids.add(item_id)
        if row["size"] not in {"large", "medium", "small"}:
            raise ValueError(f"{where}.size is invalid")
        resolved_labels.append({
            **copy.deepcopy(row), "position": _point(row["position"], f"{where}.position", bounds),
            "token": _label_token(campaign_id, item_id),
            "adapter_slot": slot('labels', item_id, number),
        })
    if len({row["token"] for row in resolved_labels}) != len(resolved_labels):
        raise ValueError("Generated map-label token collision")

    waypoint_rows = map_doc.get('waypoints', [])
    if not isinstance(waypoint_rows, list):
        raise ValueError('Map waypoints must be a list')
    waypoint_ids = set()
    for waypoint in waypoint_rows:
        _exact(waypoint, {'id', 'position'}, 'map.waypoint')
        identifier = _identifier(waypoint['id'], 'waypoint.id')
        if identifier in waypoint_ids or identifier in flag_ids:
            raise ValueError('Waypoint duplicates an objective or waypoint')
        waypoint_ids.add(identifier)
    target_ids = flag_ids | waypoint_ids
    orders = ai_doc["orders"]
    if not isinstance(orders, list):
        raise ValueError("ai.orders must be a list")
    order_by_unit = {}
    for number, row in enumerate(orders):
        where = f"ai.order[{number}]"
        _exact(row, {"unit", "type", "target", "start_turn"}, where, optional={"route"})
        if row["unit"] in order_by_unit:
            raise ValueError(f"Conflicting AI orders for {row['unit']}")
        if row["type"] not in AI_ORDERS:
            raise ValueError(f"Unsupported AI order in {where}: {row['type']}")
        if row["target"] not in target_ids:
            raise ValueError(f"Unknown AI target in {where}: {row['target']}")
        route = row.get("route", [row["target"]])
        if (not isinstance(route, list) or not 1 <= len(route) <= 11
                or any(not isinstance(item, str) or item not in target_ids for item in route)
                or len(route) != len(set(route)) or route[-1] != row["target"]
                or len(route) > 1 and row["type"] not in {"attack", "counterattack", "move_to"}):
            raise ValueError(f"{where}.route needs distinct authored objectives ending at target")
        if type(row["start_turn"]) is not int or row["start_turn"] < 1:
            raise ValueError(f"{where}.start_turn must be >= 1")
        order_by_unit[row["unit"]] = copy.deepcopy(row)
    initial_ids = {row["id"] for row in resolved_deployments}
    if set(order_by_unit) != initial_ids:
        missing = sorted(initial_ids - set(order_by_unit))
        extra = sorted(set(order_by_unit) - initial_ids)
        raise ValueError(f"Every initial battalion needs exactly one AI order; missing={missing}, extra={extra}")

    runtime_slots = iter(copy.deepcopy(profile["slots"]["runtime_positions"]))
    resolved_runtime_positions = []

    def runtime_position(kind, item_id, position, where):
        if dynamic:
            position_slot = slot('runtime_positions', kind + '_' + item_id, len(resolved_runtime_positions))
        else:
            try:
                position_slot = next(runtime_slots)
            except StopIteration as exc:
                raise ValueError("Campaign exceeds map-profile runtime-position capacity") from exc
        result = {
            "id": item_id, "kind": kind,
            "position": _point(position, where, bounds),
            "guid": _guid(kind, campaign_id, item_id),
            "adapter_slot": position_slot,
        }
        resolved_runtime_positions.append(result)
        return result

    resolved_waypoints = [runtime_position('waypoint', row['id'], row['position'], 'waypoint.position')
                          for row in waypoint_rows]

    def resolve_ai(ai, where):
        _exact(ai, {"type", "target"}, where, optional={"route"})
        if ai["type"] not in AI_ORDERS or ai["target"] not in target_ids:
            raise ValueError(f"Invalid AI order in {where}")
        route = ai.get('route', [ai['target']])
        if (not isinstance(route, list) or not 1 <= len(route) <= 11
                or any(not isinstance(item, str) or item not in target_ids for item in route)
                or len(route) != len(set(route)) or route[-1] != ai['target']
                or len(route) > 1 and ai['type'] not in {'attack', 'counterattack', 'move_to'}):
            raise ValueError(f"Invalid AI route in {where}")
        return copy.deepcopy(ai)

    from .production import compile_production, bind_production_divisions
    production = compile_production(production_doc, campaign, battalion_by_id, bounds)
    if any(row.get('required_flag') not in flag_ids for row in production['divisions'] if 'required_flag' in row):
        raise ValueError('Production division requires an unknown flag')
    directed_production = [group for group in production['groups'] if 'ai' in group]
    if directed_production and len(directed_production) != len(production['groups']):
        raise ValueError('Every production group needs an AI plan when AI-directed production is enabled')
    for group in directed_production:
        group['ai'] = resolve_ai(group['ai'], 'production.' + group['id'] + '.ai')
        if 'member_ai' in group:
            group['member_ai'] = {
                member: resolve_ai(plan, 'production.' + group['id'] + '.member_ai.' + member)
                for member, plan in group['member_ai'].items()}
    bind_production_divisions(production, battalion_by_id)
    for point in production["deployment_points"]:
        marker = runtime_position("production_point", point["id"], point["position"], "production.position")
        point["adapter_slot"] = marker["adapter_slot"]
        label_id = "production_" + point["id"]
        if label_id in label_ids or (not dynamic and len(resolved_labels) >= profile["capacity"]["labels"]):
            raise ValueError("Production point exceeds label capacity or duplicates a label")
        label_ids.add(label_id)
        resolved_labels.append({
            "id": label_id, "position": list(point["position"]), "text": copy.deepcopy(point["name"]),
            "size": "small", "token": _label_token(campaign_id, label_id),
            "adapter_slot": slot('labels', label_id, len(resolved_labels)),
        })

    reinforcements = reinforcements_doc["reinforcements"]
    if not isinstance(reinforcements, list):
        raise ValueError("reinforcements must be a list")
    reinforcement_ids = set()
    resolved_reinforcements = []
    for number, row in enumerate(reinforcements):
        where = f"reinforcement[{number}]"
        _exact(row, {"id", "battalion", "side", "turn", "position", "ai"}, where)
        item_id = _identifier(row["id"], f"{where}.id")
        if item_id in reinforcement_ids:
            raise ValueError(f"Duplicate reinforcement id: {item_id}")
        reinforcement_ids.add(item_id)
        side = _side(row["side"], f"{where}.side")
        if row["battalion"] not in battalion_by_id or battalion_by_id[row["battalion"]]["side"] != side:
            raise ValueError(f"Invalid reinforcement battalion in {where}")
        require_ground_battalion(row['battalion'], where)
        if type(row["turn"]) is not int or not 1 <= row["turn"] <= campaign["turns"]:
            raise ValueError(f"Invalid reinforcement turn in {where}")
        ai = resolve_ai(row["ai"], f"{where}.ai")
        marker = runtime_position("reinforcement", item_id, row["position"], f"{where}.position")
        resolved_reinforcements.append({
            **copy.deepcopy(row), "position": marker["position"],
            "position_guid": marker["guid"], "adapter_slot": marker["adapter_slot"],
            "unit_export": battalion_by_id[row["battalion"]]["unit_export"],
            "ai": ai,
        })

    events = events_doc["events"]
    if not isinstance(events, list):
        raise ValueError("events must be a list")
    event_ids = set()
    resolved_events = []
    for number, row in enumerate(events):
        where = f"event[{number}]"
        _exact(row, {"id", "side", "trigger", "title", "text", "image", "choices", "effects"}, where,
               optional={"layout", "ai_choice"})
        item_id = _identifier(row["id"], f"{where}.id")
        if item_id in event_ids:
            raise ValueError(f"Duplicate event id: {item_id}")
        event_ids.add(item_id)
        side = _side(row["side"], f"{where}.side")
        if 'ai_choice' in row and (type(row['ai_choice']) is not int or row['ai_choice'] not in (0, 1)):
            raise ValueError(f'{where}.ai_choice must be 0 or 1')
        layout = row.get('layout', 'text')
        if layout not in ('text', 'graphic_cards'):
            raise ValueError(f"{where}.layout must be text or graphic_cards")
        trigger = row["trigger"]
        if not isinstance(trigger, dict) or set(trigger) not in ({"turn"}, {"turn", "when"}, {"flag", "owner"}, {"capture"}, {'first_enemy_destroyed'},{'capture_deadline'},{'turn','capture_deadline'}):
            raise ValueError(f"{where}.trigger must use turn, flag+owner, capture or first_enemy_destroyed")
        if 'when' in trigger:
            from .choice_conditions import validate_requirements
            validate_requirements(trigger['when'], f'{where}.trigger.when')
        if 'capture_deadline' in trigger and (trigger['capture_deadline'] not in ('blocked','not_blocked') or 'capture_deadline' not in campaign):
            raise ValueError('Deadline event needs a declared capture_deadline and blocked/not_blocked result')
        if (trigger.get('capture_deadline') == 'not_blocked'
                and ('turn' not in trigger or type(trigger['turn']) is not int
                     or trigger['turn'] < campaign['capture_deadline'].get('before_turn', 0))):
            raise ValueError('An open deadline result can be announced only at or after its cutoff')
        if "turn" in trigger:
            if type(trigger["turn"]) is not int or not 1 <= trigger["turn"] <= campaign["turns"]:
                raise ValueError(f"{where}.trigger.turn is invalid")
        elif 'first_enemy_destroyed' in trigger:
            if trigger['first_enemy_destroyed'] is not True:
                raise ValueError(f"{where}.trigger.first_enemy_destroyed must be true")
        elif 'capture' in trigger:
            if not isinstance(trigger['capture'], str) or trigger['capture'] not in flag_ids:
                raise ValueError(f"{where}.trigger.capture references an unknown flag")
        elif 'capture_deadline' not in trigger:
            if trigger["flag"] not in flag_ids:
                raise ValueError(f"{where}.trigger references an unknown flag")
            _side(trigger["owner"], f"{where}.trigger.owner")
        for localized_name in ("title", "text"):
            _exact(row[localized_name], {"ru", "en"}, f"{where}.{localized_name}")
            if not all(isinstance(value, str) and value for value in row[localized_name].values()):
                raise ValueError(f"{where}.{localized_name} translations must not be empty")
        if row['image'] is not None and (not isinstance(row["image"], str) or not row["image"]):
            raise ValueError(f"{where}.image must not be empty")
        if row['image'] is not None and row["image"] not in profile["event_images"]:
            raise ValueError(f"{where}.image is absent from the map-profile asset catalog")
        choices = row["choices"]
        effects = row["effects"]
        if not isinstance(choices, list) or not isinstance(effects, list) or choices and effects:
            raise ValueError(f"{where} cannot combine choices and effects")
        if choices and row['image'] is None:
            raise ValueError(f"{where} choice events require an image asset")
        if choices and len(choices) != 2:
            raise ValueError(f"{where} must have exactly two choices on this adapter")
        if layout == 'graphic_cards' and not choices:
            raise ValueError(f"{where}.layout graphic_cards requires two choices")

        def resolve_effect(effect, effect_where):
            if not isinstance(effect, dict):
                raise ValueError(f"{effect_where} must be a mapping")
            if set(effect) in ({"spawn", "position", "ai"},
                               {"spawn", "position", "ai", "at_turn"}):
                battalion_id = effect["spawn"]
                if (battalion_id not in battalion_by_id
                        or battalion_by_id[battalion_id]["side"] != row["side"]):
                    raise ValueError(f"Invalid event spawn in {effect_where}")
                require_ground_battalion(battalion_id, effect_where)
                if 'at_turn' in effect:
                    scheduled_turn = effect['at_turn']
                    if (type(scheduled_turn) is not int
                            or not 1 <= scheduled_turn <= campaign['turns']
                            or 'turn' not in trigger
                            or scheduled_turn <= trigger['turn']):
                        raise ValueError(f'{effect_where}.at_turn must follow its turn event')
                marker_id = f"{item_id}_{battalion_id}"
                marker = runtime_position("event", marker_id, effect["position"], f"{effect_where}.position")
                return {
                    **copy.deepcopy(effect), "position": marker["position"],
                    "position_guid": marker["guid"], "adapter_slot": marker["adapter_slot"],
                    "unit_export": battalion_by_id[battalion_id]["unit_export"],
                    "ai": resolve_ai(effect["ai"], f"{effect_where}.ai"),
                }
            if set(effect) == {'score', 'side'}:
                points = effect['score']
                if type(points) is not int or points == 0 or not -1000 <= points <= 1000:
                    raise ValueError(f'{effect_where}.score must be a nonzero integer from -1000 to 1000')
                return {'score': points, 'side': _side(effect['side'], f'{effect_where}.side')}
            if set(effect) in ({'action_points', 'battalion'},
                               {'casualties', 'random_range', 'battalion'}):
                deployment = next((item for item in resolved_deployments
                                   if item['battalion'] == effect['battalion']), None)
                if deployment is None:
                    raise ValueError(f'{effect_where}.battalion must be an initially deployed battalion')
                if 'action_points' in effect:
                    points = effect['action_points']
                    if type(points) is not int or not 0 <= points <= 12:
                        raise ValueError(f'{effect_where}.action_points must be 0..12')
                else:
                    losses, spread = effect['casualties'], effect['random_range']
                    if (type(losses) is not int or not 1 <= losses <= 1000
                            or type(spread) is not int or not 0 <= spread <= 1000):
                        raise ValueError(f'{effect_where} casualties and random range are invalid')
                return {**copy.deepcopy(effect), 'deployment_slot': deployment['adapter_slot']}
            raise ValueError(f"Unsupported event effect in {effect_where}")

        resolved_choices = []
        for choice_number, choice in enumerate(choices):
            choice_where = f"{where}.choices[{choice_number}]"
            _exact(choice, {"label", "effects"}, choice_where, optional={"card"})
            _exact(choice["label"], {"ru", "en"}, f"{choice_where}.label")
            card = choice.get('card')
            if layout == 'graphic_cards':
                _exact(card, {'image', 'title', 'text'}, f'{choice_where}.card')
                if card['image'] not in profile['event_images']:
                    raise ValueError(f'{choice_where}.card.image is absent from the map-profile asset catalog')
                for field in ('title', 'text'):
                    _exact(card[field], {'ru', 'en'}, f'{choice_where}.card.{field}')
                    if not all(isinstance(value, str) and value for value in card[field].values()):
                        raise ValueError(f'{choice_where}.card.{field} translations must not be empty')
            elif card is not None:
                raise ValueError(f'{choice_where}.card is only valid with graphic_cards layout')
            if not isinstance(choice["effects"], list):
                raise ValueError(f"{choice_where}.effects must be a list")
            resolved_choices.append({
                "label": copy.deepcopy(choice["label"]),
                **({'card': copy.deepcopy(card)} if card is not None else {}),
                "effects": [resolve_effect(effect, f"{choice_where}.effects[{i}]")
                            for i, effect in enumerate(choice["effects"])],
            })
        resolved_effects = [resolve_effect(effect, f"{where}.effects[{i}]")
                            for i, effect in enumerate(effects)]
        resolved_events.append({**copy.deepcopy(row), "choices": resolved_choices,
                                "effects": resolved_effects,
                                "adapter_image": profile["event_images"].get(row["image"])})

    # A strategic Pawn descriptor is not merely a reusable visual archetype:
    # battle results and campaign saves attach mutable roster state to it.  Two
    # live instances backed by one descriptor can therefore alias casualties
    # and corrupt end-of-battle save processing.  Keep every possible authored
    # instance unique, including mutually exclusive event branches.
    battalion_uses = []
    battalion_uses.extend((row["battalion"], f"deployment[{row['id']}]")
                          for row in resolved_deployments)
    battalion_uses.extend((row["battalion"], f"reinforcement[{row['id']}]")
                          for row in resolved_reinforcements)
    battalion_uses.extend((item, f"production[{row['id']}]")
                          for row in production["groups"] for item in row["battalions"])
    for event in resolved_events:
        effect_lists = ([choice["effects"] for choice in event["choices"]]
                        if event["choices"] else [event["effects"]])
        for branch, effects in enumerate(effect_lists):
            battalion_uses.extend((effect["spawn"],
                                   f"event[{event['id']}].branch[{branch}]")
                                  for effect in effects if 'spawn' in effect)
    from .aviation import compile_aviation
    aviation = compile_aviation(aviation_doc, campaign, battalion_by_id, resolved_events, bounds)
    from .choice_conditions import bind_requirements
    choice_consumers = bind_requirements(production, resolved_events)
    if 'playable_bounds' in profile.get('strategic_map', {}):
        from .strategic_map_package import NATIVE_ACTION_POINT_STEP
        left, bottom, right, top = bounds
        step = NATIVE_ACTION_POINT_STEP
        for airfield in aviation['airfields']:
            horizontal, vertical = airfield['position']
            if not (left + step <= horizontal < right - step
                    and bottom + step <= vertical < top - step):
                raise ValueError('Airfield requires a one-cell neighborhood inside playable bounds')
    for event in resolved_events:
        for index, choice in enumerate(event['choices']):
            if not choice['effects'] and not any(
                    wing['available'] == {'event': event['id'], 'choice': index}
                    for wing in aviation['wings']) and index not in choice_consumers.get(event['id'], set()):
                raise ValueError(f"event[{event['id']}].choices[{index}].effects must not be empty without aviation")
    airfield_sides = set()
    for field in aviation['airfields']:
        if field['side'] in airfield_sides:
            raise ValueError('This map adapter currently supports one authored airfield per side')
        airfield_sides.add(field['side'])
        if field['country'] not in campaign['sides'][field['side']]['countries']:
            raise ValueError('Airfield country is outside its coalition configured countries')
        field['spawn_slot'] = ('P0_C0_TestAirport_1' if field['side'] == 'nato' else 'P0_C0_TestAirport_2')
        if dynamic:
            field['spawn_slot'] = slot('runtime_positions', 'airfield_spawn_' + field['id'], 0)['name']
        marker = runtime_position('airfield', 'airfield_' + field['id'], field['position'], 'airfield.position')
        field['position_marker'] = marker['id']
        field['position_guid'] = marker['guid']
        label_id = 'airfield_' + field['id']
        if label_id in label_ids or (not dynamic and len(resolved_labels) >= profile['capacity']['labels']):
            raise ValueError('Airfield exceeds label capacity or duplicates a label')
        label_ids.add(label_id)
        resolved_labels.append({'id': label_id, 'position': list(field['position']),
                                'text': copy.deepcopy(field['name']), 'size': 'small',
                                'token': _label_token(campaign_id, label_id),
                                'adapter_slot': slot('labels', label_id, len(resolved_labels))})
    for wing in aviation['wings']:
        field = next(field for field in aviation['airfields'] if field['id'] == wing['airfield'])
        wing['position_marker'] = field['position_marker']
        wing['position_guid'] = field['position_guid']
    battalion_uses.extend((wing['battalion'], 'aviation[' + wing['battalion'] + ']')
                          for wing in aviation['wings'])
    first_use = {}
    for battalion_id, use in battalion_uses:
        if battalion_id in first_use:
            previous = first_use[battalion_id]
            raise ValueError(
                f"Strategic battalion {battalion_id} is instantiated more than once: "
                f"{previous}, {use}"
            )
        first_use[battalion_id] = use

    if 'ai_policy' in campaign:
        policy = campaign['ai_policy']
        from .ai_distances import FIELDS as distance_fields
        _exact(policy, {'attack_radius', 'cooperate'}, 'campaign.ai_policy',optional={'refresh_each_turn','phase_orders','continuous_route','retain_route_progress','aggressive_until','transit_waypoints','native_controller_sides','scripted_exceptions','native_strategies'}|distance_fields)
        if type(policy['attack_radius']) is not int or not 530 <= policy['attack_radius'] <= 2120 or type(policy['cooperate']) is not bool:
            raise ValueError('Invalid campaign AI attack policy')
        if set(policy)&distance_fields:
            import math
            if (set(policy)&distance_fields!=distance_fields or not policy.get('refresh_each_turn') or not policy.get('continuous_route')
                    or any(type(policy[key]) not in (int,float) or not math.isfinite(policy[key])
                           or not 0<policy[key]<=12 for key in distance_fields)):
                raise ValueError('AI cell radii require four positive bounded values and refreshed missions')
        transit=policy.get('transit_waypoints',[])
        if (not isinstance(transit,list) or any(not isinstance(key,str) for key in transit) or len(set(transit))!=len(transit)
                or any(key not in target_ids or key in flag_ids for key in transit)
                or transit and not set(policy)&distance_fields):
            raise ValueError('AI transit_waypoints require unique non-flag targets and cell radii')
        native=policy.get('native_controller_sides',[])
        exceptions=policy.get('scripted_exceptions',[])
        if (not isinstance(native,list) or any(not isinstance(side,str) or side not in SIDES for side in native)
                or len(set(native))!=len(native) or not isinstance(exceptions,list)
                or any(not isinstance(member,str) or member not in battalion_by_id for member in exceptions)
                or len(set(exceptions))!=len(exceptions)
                or any(battalion_by_id[member]['side'] not in native for member in exceptions)):
            raise ValueError('Invalid native AI sides or scripted exceptions')
        strategies=policy.get('native_strategies',{})
        if (not isinstance(strategies,dict) or any(side not in SIDES or mode not in ('attacker','defender')
                for side,mode in strategies.items())):
            raise ValueError('Native strategic roles must use known sides and attacker/defender')
        if 'refresh_each_turn' in policy and type(policy['refresh_each_turn']) is not bool:
            raise ValueError('AI refresh_each_turn must be boolean')
        if 'continuous_route' in policy and (type(policy['continuous_route']) is not bool
                or not policy.get('refresh_each_turn')):
            raise ValueError('AI continuous_route requires per-turn refresh')
        if 'retain_route_progress' in policy and (type(policy['retain_route_progress']) is not bool
                or not policy.get('continuous_route')):
            raise ValueError('AI retained progress requires continuous routes')
        aggression=policy.get('aggressive_until',{})
        if (not isinstance(aggression,dict) or any(side not in ('nato','pact')
                or type(turn) is not int or not 1<=turn<=campaign['turns'] for side,turn in aggression.items())
                or aggression and not policy.get('refresh_each_turn')):
            raise ValueError('AI aggressive_until needs side-specific dated refresh plans')
        phases=policy.get('phase_orders',{})
        if not isinstance(phases,dict) or any(key not in battalion_by_id for key in phases):
            raise ValueError('AI phase_orders references an unknown battalion')
        for changes in phases.values():
            if not isinstance(changes,list) or not changes:raise ValueError('AI phases need ordered turn plans')
            previous=0
            for phase in changes:
                _exact(phase,{'from_turn','type','target'},'AI phase',optional={'route'})
                route=phase.get('route',[phase['target']])
                if (type(phase['from_turn']) is not int or not previous<phase['from_turn']<=campaign['turns']
                        or phase['type'] not in AI_ORDERS or phase['target'] not in target_ids
                        or not isinstance(route,list) or not route or route[-1]!=phase['target']
                        or any(x not in target_ids for x in route)):
                    raise ValueError('Invalid AI phase turn, type or route')
                previous=phase['from_turn']
    if 'victory' in campaign:
        policy = campaign['victory']
        _exact(policy, {'nato_capture', 'pact_capture', 'time_limit'}, 'campaign.victory')
        if policy['nato_capture'] not in flag_ids or policy['pact_capture'] not in flag_ids or policy['nato_capture'] == policy['pact_capture'] or policy['time_limit'] not in ('draw','nato','pact'):
            raise ValueError('Victory requires distinct authored capture goals and a valid time-limit outcome')
    if 'capture_deadline' in campaign:
        rule=campaign['capture_deadline']
        _exact(rule,{'flag','owner','before_turn','division'},'campaign.capture_deadline')
        if (not isinstance(rule['flag'], str) or rule['flag'] not in flag_ids
                or not isinstance(rule['owner'], str) or rule['owner'] not in SIDES
                or type(rule['before_turn']) is not int or not 2<=rule['before_turn']<=campaign['turns']
                or not isinstance(rule['division'], str)
                or rule['division'] not in {d['id'] for d in production['divisions']}):
            raise ValueError('Invalid capture deadline flag, turn or production division')
        if any(g['turn']<rule['before_turn'] for g in production['groups'] if g['division']==rule['division']):
            raise ValueError('Blocked division must not deploy before its capture deadline')
        if not directed_production:
            raise ValueError('Capture deadlines require production AI version 2')
    if cinematics is not None and 'encirclement_flags' in cinematics and any(item not in flag_ids for item in cinematics['encirclement_flags']):
        raise ValueError('Encirclement references an unknown flag')
    if cinematics is not None and 'ending_flags' in cinematics and any(item not in flag_ids for item in cinematics['ending_flags'].values()):
        raise ValueError('Ending status references an unknown flag')
    if cinematics is not None and cinematics.get('start_camera', {}).get('focus') not in flag_ids and 'start_camera' in cinematics:
        raise ValueError('Cinematic start camera references an unknown objective')
    from .campaign_menu import compile_menu
    menu = compile_menu(source, campaign)
    result = {
        "schema": SCHEMA,
        "format": "authored-campaign-v1",
        "campaign": copy.deepcopy(campaign),
        "map": {"flags": resolved_flags, "influence_sources": resolved_influence,
                "labels": resolved_labels, "runtime_positions": resolved_runtime_positions,
                **({'waypoints':resolved_waypoints} if resolved_waypoints else {}),
                **({"strategic_grid": strategic_grid.as_dict()} if strategic_grid is not None else {})},
        "battalions": battalions,
        "custom_packs": custom_packs,
        "deployments": resolved_deployments,
        "reinforcements": resolved_reinforcements,
        "production": production,
        'aviation': aviation,
        "events": resolved_events,
        **({'menu': menu} if menu is not None else {}),
        **({'emblems': emblems} if emblems else {}),
        **({'cinematics': cinematics} if cinematics is not None else {}),
        "ai": {"orders": [order_by_unit[row["id"]] for row in resolved_deployments]},
        "adapter": {
            "ai_mission_version": 7 if 'attack_radius_cells' in campaign.get('ai_policy',{}) else 6 if (campaign.get('ai_policy',{}).get('retain_route_progress') or campaign.get('ai_policy',{}).get('aggressive_until')) else 5 if campaign.get('ai_policy',{}).get('continuous_route') else 4 if campaign.get('ai_policy',{}).get('refresh_each_turn') else 3 if 'ai_policy' in campaign else 2,
            **({'ai_startup_version':2} if 'ai_policy' in campaign else {}),
            **({'frozen_lifecycle_version': 4}
               if dynamic and any(row['frozen_turns'] for row in resolved_deployments) else {}),
            **({'production_ai_version': 2} if directed_production else {}),
            **({'registration': 'dynamic'} if dynamic else {}),
            **({'strategic_map': StrategicMapContract.from_config(profile['strategic_map']).as_dict()}
               if 'strategic_map' in profile else {}),
            "profile_id": profile["id"], "template": copy.deepcopy(profile["template"]),
            "script": copy.deepcopy(profile["script"]), "profile_sha256": sha256(Path(profile_path).read_bytes()),
        },
    }
    if result['adapter']['ai_mission_version']==7:
        from .ai_distances import compile_distance_units
        result['adapter']['ai_distance_units']=compile_distance_units(result)
    localisation=root/'localization.yaml'
    if localisation.is_file():
        from .localisation import compile_localisation
        result['localisation']=compile_localisation(_read_yaml(localisation),result)
    else:
        from .localisation import validate_ui_names
        validate_ui_names(result)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report = {
        "campaign": campaign_id, "template": profile["id"], "compiled_sha256": sha256(encoded),
        "initial_battalions": side_counts, "flags": len(resolved_flags),
        "influence_sources": len(resolved_influence), "labels": len(resolved_labels),
        "reinforcements": len(resolved_reinforcements), "events": len(resolved_events),
        **({'intro_slides': 8, 'ending_variants': 18} if cinematics is not None else {}),
        "production_groups": len(production["groups"]),
        "production_ai_groups": len(directed_production),
        "ai_orders": len(order_by_unit),
        "initial_losses": sum(row["initial_losses"]["budget"] > 0 for row in resolved_deployments),
    }
    if destination is not None:
        destination = Path(destination).resolve()
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "campaign.compiled.json").write_bytes(encoded + b"\n")
        (destination / "compile-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    return result, report
