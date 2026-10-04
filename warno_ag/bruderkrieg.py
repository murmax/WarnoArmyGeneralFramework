"""Binary adapter for authoring new content on the Bruderkrieg geography."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct

from .archives import read_directory, pack_v3, clone_v3
from .cndf import (decode, append_graph_objects, rebuild_objects, rebuild_sections,
                   encode_strings)
from .current_campaign import (DETAILS_LAYERS, DETAILS_RESOURCES, GAME_DATA,
                               EVENT_TEXT, _dictionary_keys, _int32_words,
                               _property, build_current_definition)
from .full_campaign import SCENARIO, _pack_trad, _trad_data
from .items import map_feature_inventory, patch_items, patch_map_features, spawn_inventory
from .storage import sha256
from .event_localisation import publish_ingame_choices, validate_ingame_choices, script_choice_keys
from .modgen_registry import authored_build_name


DEFAULT_DETAILS = GAME_DATA / "197351/201602/Scenarios/CampagneStrat_Bruderkrieg_Details.dat"
DEFAULT_DEFINITION = GAME_DATA / "201602/Scenarios/CampagneStrat_Bruderkrieg_Definition.dat"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "mods/ag-framework-mvp/red-line-1989.json"


def authored_text_key(campaign_id, *parts):
    """Return an isolated eight-byte key for author-supplied runtime text."""
    source = (campaign_id + "\0" + "\0".join(parts)).encode("utf-8")
    return b"AGF1" + hashlib.sha256(source).digest()[:4]


def _victory_text(compiled, language, side):
    flags = compiled['map']['flags']
    score = compiled['campaign']['score_to_win']
    name = {'nato': 'НАТО', 'pact': 'ОВД'}[side] if language == 'ru' else side.upper()
    if 'victory' in compiled['campaign']:
        if side=='pact' and compiled['campaign']['victory']['time_limit']=='pact':
            return 'ОВД: удержать Севастополь' if language=='ru' else 'PACT: hold Sevastopol'
        flag = next(row for row in flags if row['id'] == compiled['campaign']['victory'][side + '_capture'])
        return f'{name}: захватить {flag["name"][language]}' if language == 'ru' else f'{name}: capture {flag["name"][language]}'
    all_flags = (sum(flag['capture_score'] for flag in flags) == score
                 and all(flag['capture_score'] > 0 and flag['hold_score'] == 0 for flag in flags))
    if all_flags:
        if language == 'ru':
            noun = 'флага' if len(flags) in (2, 3, 4) else 'флагов'
            return f'{name}: захватить все {len(flags)} {noun} ({score} очков)'
        return f'{name}: capture all {len(flags)} flags ({score} points)'
    return f'{name}: набрать {score} победных очков' if language == 'ru' else f'{name}: reach {score} victory points'


def _authored_text_base(compiled, language):
    """Collect all runtime strings referenced by the authored script/map."""
    if language not in {"ru", "en"}:
        raise ValueError("Authored localisation supports ru and en")
    campaign_id = compiled["campaign"]["id"]
    values = {
        authored_text_key(campaign_id, "frozen", "countdown"): (
            ("Заблокировано на %1 ходов" if language == "ru" else "Locked for %1 turns")
            if compiled['adapter'].get('frozen_lifecycle_version', 1) >= 2 else
            ("Готовность через %1 ход(-ов)" if language == "ru" else "Available in %1 turn(s)")),
        authored_text_key(campaign_id, "frozen", "empty"): "",
    }
    values.update({
        authored_text_key(campaign_id, "victory", side): _victory_text(compiled, language, side)
        for side in ('nato', 'pact')
    })
    from .campaign_menu import menu_text
    values.update(menu_text(compiled, language))
    for flag in compiled["map"]["flags"]:
        values[authored_text_key(campaign_id, "flag", flag["id"])] = flag["name"][language]
    for event in compiled["events"]:
        values[authored_text_key(campaign_id, "event", event["id"], "title")] = event["title"][language]
        values[authored_text_key(campaign_id, "event", event["id"], "text")] = event["text"][language]
        values[authored_text_key(campaign_id, "event", event["id"], "presentation")] = (
            event["title"][language] + "\n\n" + event["text"][language])
        for index, choice in enumerate(event["choices"]):
            values[authored_text_key(campaign_id, "event", event["id"], "choice", str(index))] = choice["label"][language]
            if event.get('layout', 'text') == 'graphic_cards':
                for field in ('title', 'text'):
                    values[authored_text_key(campaign_id, 'event', event['id'], 'card',
                                             str(index), field)] = choice['card'][field][language]
    cinematic = compiled.get('cinematics')
    if cinematic is not None:
        def slide_text(slide, key):
            values[key] = slide['text'][language] if cinematic.get('layout') == 'briefing' else slide['title'][language] + '\n\n' + slide['text'][language]
            if cinematic.get('layout') == 'briefing':
                values[authored_text_key(campaign_id, 'cinematic_title', key.hex())] = slide['title'][language]
        for side, slides in cinematic['intro'].items():
            for index, slide in enumerate(slides):
                slide_text(slide, authored_text_key(campaign_id, 'intro', side, str(index)))
        for side, axes in cinematic['endings'].items():
            for axis, variants in axes.items():
                for variant, slide in variants.items():
                    slide_text(slide, authored_text_key(campaign_id, 'ending', side, axis, variant))
    for label in compiled["map"]["labels"]:
        values[authored_text_key(campaign_id, "label", label["id"])] = label["text"][language]
    production = compiled.get("production", {"divisions": [], "groups": []})
    for division in production["divisions"]:
        for field in ("name", "short_name"):
            values[authored_text_key(campaign_id, "division", division["id"], field)] = division[field][language]
    for group in production["groups"]:
        values[authored_text_key(campaign_id, "regiment", group["id"])] = group["name"][language]
    if len(values) != len(set(values)):
        raise ValueError("Authored localisation key collision")
    return values


def authored_text(compiled,language):
    from .localisation import locale,translate
    language=locale(language)
    values=_authored_text_base(compiled,'ru' if language=='ru' else 'en')
    return values if language=='ru' else {key:translate(compiled,text,language) for key,text in values.items()}


def authored_choice_text(compiled):
    keys = {authored_text_key(compiled['campaign']['id'], 'event', event['id'], 'choice', str(index))
            for event in compiled['events'] for index, choice in enumerate(event['choices'])}
    return {language: {key: text for key, text in authored_text(
                compiled, language).items() if key in keys}
            for language in ('DEV', 'FR', 'GER', 'POL', 'RU', 'SC', 'SPA', 'US')}


def authored_ingame_text(compiled):
    translations = authored_choice_text(compiled)
    production = compiled.get('production', {'divisions': [], 'groups': []})
    keys = {authored_text_key(compiled['campaign']['id'], 'regiment', group['id'])
            for group in production['groups']}
    keys.update(authored_text_key(compiled['campaign']['id'], 'division', division['id'], field)
                for division in production['divisions'] for field in ('name', 'short_name'))
    for language, values in translations.items():
        values.update({key: text for key, text in authored_text(
            compiled, language).items() if key in keys})
    return translations


def _payloads(raw):
    header, entries, _ = read_directory(raw)
    return {
        entry.path: raw[header.file_offset + entry.offset:
                        header.file_offset + entry.offset + entry.size]
        for entry in entries
    }


def patch_authored_pawn_states(raw, compiled):
    """Apply deployment fatigue/AP values to the authored Pawn descriptors.

    A strategic Pawn descriptor owns these values, so the same catalog entry
    cannot be deployed twice with contradictory state.  The public compiler
    reports that conflict before touching the binary.
    """
    requested = {}
    for row in compiled["deployments"]:
        state = (row["fatigue"], row["action_points"], bool(row['frozen_turns']) and
                 compiled['adapter'].get('frozen_lifecycle_version', 1) >= 2)
        previous = requested.setdefault(row["unit_export"], state)
        if previous != state:
            raise ValueError(f"Conflicting state for shared battalion: {row['battalion']}")
    doc, graph = decode(raw)
    objects = copy.deepcopy(graph["objects"])
    original_count = len(objects)
    by_export = {}
    for object_id, path in graph["exports"].items():
        if path.startswith("$/GFX/Pawn/Descriptor_Unit_"):
            by_export[path.rsplit("/", 1)[-1]] = object_id
    property_ids = {(row["class"], row["name"]): row["id"]
                    for row in graph["properties"]}
    fatigue_property = property_ids.get(("TStrategicFatigueModuleDescriptor", "InitialFatigue"))
    new_properties = ()
    if fatigue_property is None and any(fatigue for fatigue, unused, frozen in requested.values()):
        fatigue_property = len(graph["properties"])
        new_properties = (("InitialFatigue", "TStrategicFatigueModuleDescriptor"),)
    report = {}
    for unit_export, (fatigue, action_points, frozen) in requested.items():
        if unit_export not in by_export:
            raise ValueError(f"Candidate lacks authored Pawn: {unit_export}")
        pawn = objects[by_export[unit_export]]
        module_refs = _property(pawn, "ModulesDescriptors")["items"]
        modules = [objects[item["object_id"]]
                   for item in module_refs
                   if "object_id" in item]

        def one(class_name):
            found = [item for item in modules if item["class"] == class_name]
            if len(found) != 1:
                raise ValueError(f"Authored Pawn module mismatch: {unit_export}/{class_name}")
            return found[0]

        source_ap = one("TActionPointsModuleDescriptor")
        source_fatigue = one("TStrategicFatigueModuleDescriptor")
        ap = copy.deepcopy(source_ap)
        ap["id"] = len(objects)
        ap["is_top_object"] = False
        objects.append(ap)
        fatigue_module = copy.deepcopy(source_fatigue)
        fatigue_module["id"] = len(objects)
        fatigue_module["is_top_object"] = False
        objects.append(fatigue_module)
        for item in module_refs:
            if item.get("object_id") == source_ap["id"]:
                item["object_id"] = ap["id"]
            elif item.get("object_id") == source_fatigue["id"]:
                item["object_id"] = fatigue_module["id"]
        # InitialActionPoint is also the native AP capacity. A zero here
        # creates a permanent 0/0 pawn; clear current AP in the launch instead.
        legacy_zero = frozen and compiled['adapter'].get('frozen_lifecycle_version',1) < 4
        _property(ap, "InitialActionPoint")["value"] = 0.0 if legacy_zero else float(action_points)
        _property(ap, "ActionPointRecoveryPerTurn")["value"] = int(action_points)
        produced = [p for p in ap["properties"]
                    if p["property_name"] == "NbInitialActionsPointsForProducedPawn"]
        if produced:
            produced[0]["value"]["value"] = int(action_points)
        initial = [p for p in fatigue_module["properties"]
                   if p["property_name"] == "InitialFatigue"]
        if initial:
            initial[0]["value"]["value"] = int(fatigue)
        elif fatigue:
            fatigue_module["properties"].append({
                "property_id": fatigue_property,
                "property_name": "InitialFatigue",
                "value": {"type_id": 3, "type": "uint32", "reference_prefix": False,
                          "value": int(fatigue)},
            })
        report[unit_export] = {"fatigue": int(fatigue),
                               "action_points": 0 if legacy_zero else int(action_points)}
    base = {"classes": graph["classes"], "properties": graph["properties"],
            "objects": objects[:original_count]}
    result = append_graph_objects(doc, base, objects[original_count:], (), new_properties)
    _, check = decode(result)
    if len(check["objects"]) != len(graph["objects"]) + 2 * len(requested):
        raise ValueError("Pawn-state patch private-module count mismatch")
    pawn_state_contract(result, compiled)
    return result, report


def build_authored_details(compiled, source=DEFAULT_DETAILS):
    """Build a self-contained Details archive from the profile-resolved model."""
    source = Path(source).resolve()
    template = compiled["adapter"]["template"]
    if sha256(source.read_bytes()) != template["details_sha256"]:
        raise ValueError("Bruderkrieg Details fingerprint mismatch")
    data_root = source.parents[3]
    payloads = {}
    for relative, digest in DETAILS_LAYERS:
        layer = data_root / relative
        raw = layer.read_bytes()
        if sha256(raw) != digest:
            raise ValueError(f"Bruderkrieg Details layer fingerprint mismatch: {relative}")
        payloads.update(_payloads(raw))
    if set(payloads) != DETAILS_RESOURCES:
        raise ValueError("Incomplete Bruderkrieg Details overlay")

    strategic_map = compiled.get('adapter', {}).get('strategic_map')
    if strategic_map:
        from .strategic_zones import (build_regular_ia_zones,
            build_regular_map_strategies, build_regular_playable_zone,
            clear_item_database)
        from .strategic_camera import retarget_camera_paths
        payloads['out/IAStratZone.ndfbin'] = build_regular_ia_zones(
            payloads['out/IAStratZone.ndfbin'], strategic_map, compiled['campaign']['id'])
        payloads['out/MapStrategies.ndfbin'] = build_regular_map_strategies(
            payloads['out/MapStrategies.ndfbin'], strategic_map)
        payloads['out/PlayableZone.ndfbin'] = build_regular_playable_zone(
            payloads['out/PlayableZone.ndfbin'], strategic_map)
        payloads['CamPaths_LevelDesign.ndfbin'] = retarget_camera_paths(
            payloads['CamPaths_LevelDesign.ndfbin'], compiled)
        for item_name in ('Items.sav', 'out/LevelDesign.ndfbin'):
            payloads[item_name] = clear_item_database(payloads[item_name])

    keep = [{
        "name": row["adapter_slot"]["name"],
        "x": row["position"][0], "y": row["position"][1],
        "class_name": "$/GFX/Pawn/" + row["unit_export"],
    } for row in compiled["deployments"]]
    airfields = compiled.get('aviation', {}).get('airfields', [])
    keep += [{'name': row['spawn_slot'], 'x': row['position'][0], 'y': row['position'][1],
              'class_name': '$/GFX/Pawn/' + row['unit_export']} for row in airfields]
    feature_spec = {
        "flags": compiled["map"]["flags"],
        "influence_sources": compiled["map"]["influence_sources"],
        "labels": compiled["map"]["labels"],
        "runtime_positions": compiled["map"]["runtime_positions"],
    }
    reports = {}
    def same_native_xy(actual, expected):
        # LevelDesign stores native coordinates as float32. Around one million
        # units, one ULP is 0.0625; exact decimal equality rejects valid maps.
        return len(actual) >= 2 and len(expected) >= 2 and all(
            math.isclose(float(actual[i]), float(expected[i]), rel_tol=0,
                         abs_tol=0.125) for i in (0, 1))
    for name in ("Items.sav", "out/LevelDesign.ndfbin"):
        raw = payloads[name]
        if compiled['adapter'].get('registration') == 'dynamic':
            from .map_registration import append_map_items, campaign_map_items
            registration_source = raw
            registrations = campaign_map_items(compiled)
            raw = append_map_items(raw, registrations)
        if strategic_map:
            if compiled['adapter'].get('registration') != 'dynamic':
                raise ValueError('Blank strategic maps require dynamic registration')
            expected_spawns = {row['name']: row for row in registrations if row['kind'] == 'spawn'}
            actual_spawns = {row['name']: row for row in spawn_inventory(raw)}
            if set(actual_spawns) != set(expected_spawns):
                raise ValueError('Blank strategic map spawn set mismatch')
            for spawn_name, expected in expected_spawns.items():
                actual = actual_spawns[spawn_name]
                if (not actual['auto_spawn']
                        or actual['class_name'] != '$/GFX/Pawn/' + expected['unit_export']
                        or not same_native_xy(actual['position'], expected['position'])):
                    raise ValueError('Blank strategic map spawn readback mismatch: ' + spawn_name
                                     + f' actual={actual!r} expected={expected!r}')
            expected_features = {(row['kind'], row['name']): row for row in registrations
                                 if row['kind'] in ('position', 'influence', 'label')}
            class_kinds = {'TGameDesignAddOn_Name': 'position',
                           'TGameDesignAddOn_InfluencePoint': 'influence',
                           'TGameDesignAddOn_LabelOnMap': 'label'}
            actual_features = {(class_kinds[row['class']], row['name']): row
                               for row in map_feature_inventory(raw)}
            if set(actual_features) != set(expected_features):
                raise ValueError('Blank strategic map feature set mismatch')
            for key, expected in expected_features.items():
                actual = actual_features[key]
                if actual['guid'] != expected['guid'] or not same_native_xy(actual['position'], expected['position']):
                    raise ValueError('Blank strategic map feature readback mismatch: ' + expected['name'])
                if key[0] == 'influence' and (actual['alliance'] != (1 if expected['side'] == 'nato' else 0)
                        or not math.isclose(actual['influence'], float(expected['value']),
                                            rel_tol=0, abs_tol=1e-6)
                        or actual['commands_influence'] is not True):
                    raise ValueError('Blank strategic map influence readback mismatch: ' + expected['name']
                                     + f' actual={actual!r} expected={expected!r}')
                if key[0] == 'label' and (actual['token'] != expected['token']
                        or actual['component'] != expected['component']):
                    raise ValueError('Blank strategic map label readback mismatch: ' + expected['name'])
            patched = raw
            spawn_report = {'source_sha256': sha256(registration_source),
                'output_sha256': sha256(raw), 'active_battalions': len(expected_spawns),
                'disabled_battalions': 0, 'spawn_count': len(actual_spawns),
                'registration': 'dynamic-clean'}
            map_report = {'source_sha256': sha256(registration_source),
                'output_sha256': sha256(raw), 'feature_count': len(actual_features),
                'registration': 'dynamic-clean'}
        else:
            patched, spawn_report = patch_items(raw, {
                "source_sha256": sha256(raw), "keep": keep,
                "disable_auto_spawn": True,
                "disabled_position_base": {"x": 170000.0, "y": 790000.0},
                "disabled_position_step": 1500.0,
                **({'disable_names': ['P0_C0_TestAirport_1', 'P0_C0_TestAirport_2']} if airfields else {}),
            })
            patched, map_report = patch_map_features(patched, {
                "source_sha256": sha256(patched), **feature_spec,
            })
        payloads[name] = patched
        reports[name] = {"spawns": spawn_report, "map": map_report}

    result = pack_v3(payloads)
    header, entries, _ = read_directory(result)
    if header.version != 3 or {entry.path for entry in entries} != DETAILS_RESOURCES:
        raise ValueError("Authored Details archive is not self-contained")
    runtime = payloads["out/LevelDesign.ndfbin"]
    deployment_names = {row['adapter_slot']['name'] for row in compiled['deployments']}
    active = [row for row in spawn_inventory(runtime) if row["auto_spawn"]
              and ("_pion_" in row["name"] or row['name'] in deployment_names)]
    if len(active) != len(compiled["deployments"]):
        raise ValueError("Authored Details active-spawn count mismatch")
    features = map_feature_inventory(runtime)
    by_name = {(row["class"], row["name"]): row for row in features}
    for row in compiled["map"]["flags"] + compiled["map"]["runtime_positions"]:
        actual = by_name[("TGameDesignAddOn_Name", row["adapter_slot"]["name"])]
        if actual["guid"] != row["guid"] or not same_native_xy(actual["position"], row["position"]):
            raise ValueError("Authored map position mismatch: " + row['adapter_slot']['name'])
    return result, {
        "active_battalions": len(active), "flags": len(compiled["map"]["flags"]),
        "influence_sources": len(compiled["map"]["influence_sources"]),
        "labels": len(compiled["map"]["labels"]),
        "runtime_positions": len(compiled["map"]["runtime_positions"]),
        "resources": sorted(DETAILS_RESOURCES), "reports": reports,
    }


def _rebuild_imports(document, graph, imports, section_name='IMPR'):
    return rebuild_sections(document, _reference_table_sections(document, imports, section_name))


def _reference_table_sections(document, imports, section_name='IMPR'):
    """Rebuild a CNDF import trie after safely repurposing import leaves."""
    translations = []
    for section in document.sections:
        if section.name == "TRAN":
            from .binary_codec import read_len_prefixed_strings
            translations = read_len_prefixed_strings(document.full_data, section)
            break
    if not translations:
        raise ValueError("GDScript has no TRAN table")
    segment_index = {value: index for index, value in enumerate(translations)}

    def segment(value):
        if value not in segment_index:
            segment_index[value] = len(translations)
            translations.append(value)
        return segment_index[value]

    class Node:
        def __init__(self, name):
            self.name = name
            self.index = 0xFFFFFFFF
            self.children = {}

    roots = {}
    for index, path in imports.items():
        children = roots
        node = None
        for part in path.split("/"):
            node = children.setdefault(part, Node(segment(part)))
            children = node.children
        if node.index != 0xFFFFFFFF:
            raise ValueError("Duplicate rebuilt import path")
        node.index = index
    ordered = []

    def visit(node):
        ordered.append(node)
        for child in node.children.values():
            visit(child)

    for root in roots.values():
        visit(root)
    offsets = {}
    offset = 0
    for node in ordered:
        offsets[id(node)] = offset
        offset += 12 + 4 * len(node.children)
    encoded = bytearray(offset)
    for node in ordered:
        children = list(node.children.values())
        position = offsets[id(node)]
        struct.pack_into("<III", encoded, position, node.name, node.index, len(children))
        for number, child in enumerate(children):
            struct.pack_into("<I", encoded, position + 12 + 4 * number,
                             offsets[id(child)] - (position + 12))
    return {"TRAN": encode_strings(translations), section_name: bytes(encoded)}


def _reachable_objects(graph, root):
    reachable = set()
    pending = [root]
    while pending:
        item = pending.pop()
        if item in reachable:
            continue
        if not 0 <= item < len(graph["objects"]):
            raise ValueError(f"Object reference is out of range: {item}")
        reachable.add(item)
        for property_row in graph["objects"][item]["properties"]:
            value = property_row["value"]
            if "object_id" in value:
                pending.append(value["object_id"])
            elif value.get("type") == "list":
                pending.extend(child["object_id"] for child in value["items"]
                               if "object_id" in child)
    return reachable


def _initial_operational_groups(compiled):
    """Coalesce formations which share one authored strategic order.

    Native Army General scripts issue one blocking mission to an operational
    group containing all battalions taking part in the same attack.  Giving
    every battalion its own concurrent blocking mission splits that operation.
    Keep the public per-battalion order format and the native group shape.
    Whether split operations cause the observed save-completion crash has
    not been established by offline analysis.
    """
    order_by_unit = {row["unit"]: row for row in compiled["ai"]["orders"]}
    groups = {}
    for deployment in compiled["deployments"]:
        order = order_by_unit[deployment["id"]]
        key = (deployment["side"], order["type"], tuple(order.get("route", [order["target"]])),
               order["start_turn"])
        if compiled['adapter'].get('ai_mission_version',0)>=4:key+= (deployment['id'],)
        if key not in groups:
            groups[key] = {"side": deployment["side"],
                           "order": order, "deployments": []}
        groups[key]["deployments"].append(deployment)
    return list(groups.values())


def _capture_deadline_contract(graph, compiled):
    """Check the one-shot early-capture latch and its strict turn cutoff."""
    rule = compiled['campaign'].get('capture_deadline')
    if not rule:
        return None
    objects = graph['objects']

    def target(obj, name):
        return objects[_property(obj, name)['object_id']]

    content = objects[compiled['adapter']['script']['campaign_content']]
    index = (2 + len(compiled['map']['flags']) + len(_initial_operational_groups(compiled))
             + sum(bool(row['frozen_turns']) for row in compiled['deployments'])
             + (2 if compiled.get('cinematics') else 0)
             + len(compiled['events']) + len(compiled['reinforcements']))
    monitor = objects[_property(content, 'SubActions')['items'][index]['object_id']]
    if monitor['class'] != 'TGDDescriptorCompetition':
        raise ValueError('Capture deadline must stop observing at its cutoff')
    branches = _property(monitor, 'SubActions')['items']
    if len(branches) != 2:
        raise ValueError('Capture deadline monitor branch count differs')
    capture, stop = (objects[row['object_id']] for row in branches)
    if capture['class'] != 'TGDDescriptorSequential' or stop['class'] != 'TGDDescriptorWaitCondition':
        raise ValueError('Capture deadline monitor shape differs')
    steps = _property(capture, 'SubActions')['items']
    if len(steps) != 2 or _property(capture, 'NbExecutions')['value'] != 1:
        raise ValueError('Capture deadline must latch only once')
    wait, latch = (objects[row['object_id']] for row in steps)
    condition = target(wait, 'Condition')
    if wait['class'] != 'TGDDescriptorWaitCondition' or condition['class'] != 'TGDConditionAnd':
        raise ValueError('Capture deadline must check both turn and ownership')
    conditions = _property(condition, 'SousConditions')['items']
    if len(conditions) != 2:
        raise ValueError('Capture deadline condition count differs')
    before, owner = (objects[row['object_id']] for row in conditions)
    expired = target(stop, 'Condition')
    for item, operator in ((before, 2), (expired, 5)):
        compare = target(item, 'Operator')
        if (item['class'] != 'TGDConditionVariable'
                or _property(item, 'Variable')['object_id'] != 381
                or _property(compare, 'OperatorType')['value'] != operator
                or _property(compare, 'Value')['value'] != rule['before_turn']):
            raise ValueError('Capture deadline strict turn boundary differs')
    flag = next(row for row in compiled['map']['flags'] if row['id'] == rule['flag'])
    if (owner['class'] != 'TGDConditionPositionInInfluenceMap'
            or graph['exports'].get(_property(owner, 'Position')['object_id'])
            != '$/GDScript/GdItems/Tags/' + flag['adapter_slot']['name']
            or _property(owner, 'Alliance')['value'] != (1 if rule['owner'] == 'nato' else 0)):
        raise ValueError('Capture deadline flag or captor differs')
    variable = target(latch, 'Variable1')
    if (latch['class'] != 'TGDDescriptorModifieVariableInteger'
            or _property(latch, 'ModificationType')['value'] != 0
            or _property(latch, 'Value')['value'] != 1
            or variable['class'] != 'TGDVariableInteger'
            or _property(variable, 'Value')['value'] != 0):
        raise ValueError('Capture deadline must permanently latch from zero to one')
    return variable['id']


def _authored_event_contract(graph, compiled):
    objects = graph["objects"]
    deadline_variable = _capture_deadline_contract(graph, compiled)

    def require(condition, detail):
        if not condition:
            raise ValueError("Authored event " + detail)

    def field(obj, name, default=None):
        rows = [prop["value"] for prop in obj["properties"]
                if prop["property_name"] == name]
        if not rows and default is not None:
            return default
        require(len(rows) == 1, "missing or duplicate property: " + name)
        return rows[0]

    def target(value, class_name):
        object_id = value.get("object_id", -1)
        require(0 <= object_id < len(objects), "invalid object reference")
        obj = objects[object_id]
        require(obj["class"] == class_name and value.get("class_id") == obj["class_id"],
                "unexpected descriptor: " + class_name)
        return obj

    def actions(obj, count=None):
        require(field(obj, "NbExecutions").get("value") == 1,
                "action must execute once")
        rows = field(obj, "SubActions")["items"]
        require(count is None or len(rows) == count, "action count mismatch")
        return rows

    def scheduled(value, trigger, side):
        camp = 284 if side == "nato" else 283
        if 'capture_deadline' in trigger:
            sequence=target(value,'TGDDescriptorSequential');wait_ref,action_ref=actions(sequence,2)
            wait=target(wait_ref,'TGDDescriptorWaitCondition');condition=target(field(wait,'Condition'),'TGDConditionAnd')
            values=field(condition,'SousConditions')['items']
            status=target(values[0],'TGDConditionVariable');compare=target(field(status,'Operator'),'TGDOperatorIntegerCompare')
            require(field(compare,'Value').get('value')==(1 if trigger['capture_deadline']=='blocked' else 0)
                    and field(compare, 'OperatorType', {'value': 0}).get('value') == 0
                    and field(status, 'Variable').get('object_id') == deadline_variable,
                    'Deadline notice uses the wrong result')
            timing=target(values[1],'TGDConditionAnd' if 'turn' in trigger else 'TGDConditionStrategicIsPlayerTurn')
            if 'turn' in trigger:
                parts=field(timing,'SousConditions')['items'];number=target(parts[0],'TGDConditionVariable')
                compare=target(field(number,'Operator'),'TGDOperatorIntegerCompare')
                require(field(compare,'Value').get('value')==trigger['turn']
                        and field(compare, 'OperatorType', {'value': 0}).get('value') == 0
                        and field(number, 'Variable').get('object_id') == 381,
                        'Deadline notice has wrong turn')
                timing=target(parts[1],'TGDConditionStrategicIsPlayerTurn')
            require(field(timing,'Camp').get('object_id')==camp,'Deadline notice side mismatch')
            return action_ref,camp
        if 'first_enemy_destroyed' in trigger:
            root = target(value, 'TGDDescriptorSimultaneous')
            polling, presentation = actions(root, 2)
            polling = target(polling, 'TGDDescriptorSequential')
            require(field(polling, 'NbExecutions').get('value') == 4294967295,
                    'destruction score polling must repeat')
            subactions = field(polling, 'SubActions')['items']
            require(len(subactions) == 2, 'destruction score polling shape mismatch')
            read = target(subactions[0], 'TGDDescriptorGetAllianceActualScore')
            delay = target(subactions[1], 'TGDDescriptorWaitDuration')
            require(field(read, 'ScorePointType', {'value': 0}).get('value') == 0
                    and field(read, 'Alliance', {'value': 0}).get('value') == (1 if side == 'nato' else 0),
                    'destruction score must sample the owning alliance, never losses or total score')
            require(field(delay, 'Duree').get('value') == 1,
                    'destruction score polling must be throttled')
            variable = target(field(read, 'Variable'), 'TGDVariableInteger')
            require(field(variable, 'Value', {'value': 0}).get('value') == 0,
                    'destruction score variable must start at zero')
            return scheduled(presentation, {'score_variable': variable['id']}, side)
        sequence = target(value, "TGDDescriptorSequential")
        wait_ref, action_ref = actions(sequence, 2)
        wait = target(wait_ref, "TGDDescriptorWaitCondition")
        if 'capture' in trigger:
            enemy = target(field(wait, 'Condition'), 'TGDConditionPositionInInfluenceMap')
            flag = next(row for row in compiled['map']['flags'] if row['id'] == trigger['capture'])
            path = '$/GDScript/GdItems/Tags/' + flag['adapter_slot']['name']
            require(graph['exports'].get(field(enemy, 'Position').get('object_id')) == path
                    and field(enemy, 'Alliance', {'value': 0}).get('value') == (0 if side == 'nato' else 1),
                    'capture must first observe enemy ownership')
            return scheduled(action_ref, {'flag': trigger['capture'], 'owner': side}, side)
        condition = target(field(wait, "Condition"), "TGDConditionAnd")
        conditions = field(condition, "SousConditions")["items"]
        require(len(conditions) == 2, "trigger condition count mismatch")
        if trigger.get('turn') == 1 and compiled.get('cinematics') is not None:
            intro_done = target(conditions[1], 'TGDConditionVariable')
            compare = target(field(intro_done, 'Operator'), 'TGDOperatorIntegerCompare')
            require(field(compare, 'Value').get('value') == 0,
                    'intro gate must wait for the four slides')
            condition = target(conditions[0], 'TGDConditionAnd')
            conditions = field(condition, 'SousConditions')['items']
            require(len(conditions) == 2, 'nested turn condition differs')
        side_condition = target(conditions[1], "TGDConditionStrategicIsPlayerTurn")
        require(field(side_condition, "Camp").get("object_id") == camp,
                "trigger side mismatch")
        if "turn" in trigger:
            number = target(conditions[0], "TGDConditionVariable")
            compare = target(field(number, "Operator"), "TGDOperatorIntegerCompare")
            require(field(number, "Variable").get("object_id") == 381
                    and field(compare, "OperatorType", {"value": 0}).get("value") == 0
                    and field(compare, "Value").get("value") == trigger["turn"],
                    "trigger turn mismatch")
        elif 'score_variable' in trigger:
            number = target(conditions[0], 'TGDConditionVariable')
            compare = target(field(number, 'Operator'), 'TGDOperatorIntegerCompare')
            require(field(number, 'Variable').get('object_id') == trigger['score_variable']
                    and field(compare, 'OperatorType').get('value') == 4
                    and field(compare, 'Value', {'value': 0}).get('value') == 0,
                    'destruction trigger requires a strictly positive score')
        else:
            owner = target(conditions[0], "TGDConditionPositionInInfluenceMap")
            flag = next(row for row in compiled["map"]["flags"] if row["id"] == trigger["flag"])
            path = "$/GDScript/GdItems/Tags/" + flag["adapter_slot"]["name"]
            alliance = next((prop["value"].get("value") for prop in owner["properties"]
                             if prop["property_name"] == "Alliance"), 0)
            require(graph["exports"].get(field(owner, "Position").get("object_id")) == path
                    and alliance == (1 if trigger["owner"] == "nato" else 0),
                    "ownership trigger mismatch")
        return action_ref, camp

    def effects(value, expected, camp):
        root = objects[value["object_id"]]
        reachable = _reachable_objects(graph, root["id"])
        creates = [objects[object_id] for object_id in reachable
                   if objects[object_id]["class"] == "TGDDescriptorCreateUnitOnPosition"]
        require(sorted(field(obj, "TypeUnit")["value"] for obj in creates)
                == sorted("$/GFX/Pawn/" + row["unit_export"] for row in expected if 'unit_export' in row),
                "choice spawn mismatch")
        require(all(field(obj, "Camp").get("object_id") == camp for obj in creates),
                "spawn side mismatch")
        score_actions = [objects[object_id] for object_id in reachable
                         if objects[object_id]['class'] == 'TGDDescriptorAddScoreCamp']
        require(sorted((field(obj, 'AddToScore').get('value'),
                        field(obj, 'Camp').get('object_id'), field(obj, 'ScoreType').get('value'))
                       for obj in score_actions) == sorted((row['score'],
                        284 if row['side'] == 'nato' else 283, 5)
                        for row in expected if 'score' in row), 'choice score effect mismatch')
        ap_actions = [objects[object_id] for object_id in reachable
                      if objects[object_id]['class'] == 'TGDDescriptorChangePawnActionPoint']
        require(sorted((graph['exports'].get(field(obj, 'UnitsGroup').get('object_id'), '').rsplit('/', 1)[-1],
                        field(obj, 'ActionPointNumber').get('value')) for obj in ap_actions)
                == sorted((row['deployment_slot']['name'], float(row['action_points']))
                          for row in expected if 'action_points' in row),
                'choice action-point effect mismatch')
        casualty_actions = [objects[object_id] for object_id in reachable
                            if objects[object_id]['class'] == 'TGDDescriptorAddCasualtiesToPawn']
        require(sorted((graph['exports'].get(field(obj, 'Group').get('object_id'), '').rsplit('/', 1)[-1],
                        field(obj, 'Casualties').get('value'), field(obj, 'RandomRange').get('value'),
                        field(obj, 'TypeCasualties').get('value')) for obj in casualty_actions)
                == sorted([(row['deployment_slot']['name'], row['casualties'],
                           row['random_range'], 1) for row in expected if 'casualties' in row]+[("",row['loss_budget'],0,1) for row in expected if row.get('loss_budget')]),
                'choice casualty effect mismatch')
        for object_id in reachable:
            obj = objects[object_id]
            if obj["class"] in {"TGDDescriptorSequential", "TGDDescriptorSimultaneous"}:
                rows = actions(obj)
                require(len({row["object_id"] for row in rows}) == len(rows),
                        "duplicate effect scheduling")
            require(obj['class'] == 'TGDConditionCutSceneIsCampControllableByLocalPlayer'
                    or "Cutscene" not in obj["class"] and "CutScene" not in obj["class"],
                    "AI effects must not open a dialog")

    content = objects[compiled["adapter"]["script"]["campaign_content"]]
    rows = actions(content)
    start = (2 + len(compiled["map"]["flags"]) + len(_initial_operational_groups(compiled))
             + sum(bool(row["frozen_turns"]) for row in compiled["deployments"]))
    if compiled.get('cinematics') is not None:
        start += 2
    production_count = int(bool(compiled.get("production", {}).get("groups")))
    timed_wings = [wing for wing in compiled.get('aviation', {}).get('wings', [])
                   if wing['available'].get('turn', 0) > 1]
    lifecycle_count=int(bool(compiled['campaign'].get('capture_deadline')))+sum('withdraw_turn' in w for w in compiled.get('aviation',{}).get('wings',[]))
    require(len(rows) == start + len(compiled["events"]) + len(compiled["reinforcements"]) + len(timed_wings) + production_count + lifecycle_count,
            "schedule count mismatch")
    require(len({row["object_id"] for row in rows}) == len(rows), "duplicate scheduling")
    for value, event in zip(rows[start:], compiled["events"]):
        action_ref, camp = scheduled(value, event["trigger"], event["side"])
        gate = target(action_ref, "TGDDescriptorIfThenElse")
        condition = target(field(gate, "Condition"), "TGDConditionCutSceneIsCampControllableByLocalPlayer")
        require(field(condition, "Camp").get("object_id") == camp, "local UI gate mismatch")
        local = target(field(gate, "EffetIfTrue"), "TGDDescriptorSequential")
        presentation, dispatch = actions(local, 2)
        presentation_objects = _reachable_objects(graph, presentation["object_id"])
        dialog_class = ("TGDDescriptorCutsceneDialogWithMultipleChoice" if event["choices"]
                        else "TGDDescriptorCutsceneDialog")
        dialogs = [objects[object_id] for object_id in presentation_objects
                   if objects[object_id]["class"] == dialog_class]
        require(len(dialogs) == 1, "presentation dialog mismatch")
        dialog = dialogs[0]
        graphic = event.get('layout', 'text') == 'graphic_cards'
        require(field(dialog, "ComponentName").get("value") == (
                    ('AGF_GraphicCardsV2' if compiled.get('cinematics',{}).get('layout_version')==2 else 'ST_Popup_1Texture_5Text') if graphic else 'ST_Component_1Texture_1Text'),
                "presentation template mismatch")
        text_bindings = field(dialog, "TextComponentsToFill")["items"]
        expected_text = [('Text1', ('presentation',))]
        if graphic:
            expected_text += [
                ('Text2', ('card', '0', 'title')), ('Text3', ('card', '0', 'text')),
                ('Text4', ('card', '1', 'title')), ('Text5', ('card', '1', 'text')),
            ]
        require(len(text_bindings) == len(expected_text), 'presentation text count mismatch')
        for value, (ui_name, key_parts) in zip(text_bindings, expected_text):
            text_component = target(value, 'TGDDescriptorCutsceneTextComponent')
            require(field(text_component, 'UIComponentName').get('value') == ui_name
                    and field(text_component, 'LocalizedText').get('value_hex') == authored_text_key(
                        compiled['campaign']['id'], 'event', event['id'], *key_parts).hex(),
                    'presentation text mismatch')
        texture_bindings = field(dialog, "TextureComponentsToFill")["items"]
        require(len(texture_bindings) == int(event['adapter_image'] is not None), "presentation texture count mismatch")
        if texture_bindings:
            texture_component = target(texture_bindings[0], "TGDDescriptorCutsceneTextureComponent")
            require(field(texture_component, "UIComponentName").get("value") == "Texture1"
                    and field(texture_component, "TextureFile").get("value") == event["adapter_image"],
                    "presentation texture mismatch")
        require(field(dialog, "VisibleByCamp").get("object_id") == camp,
                "dialog visibility mismatch")
        if event["choices"]:
            selection = target(dispatch, "TGDDescriptorIfThenElse")
            condition = target(field(selection, "Condition"), "TGDConditionVariable")
            compare = target(field(condition, "Operator"), "TGDOperatorIntegerCompare")
            require(field(condition, "Variable").get("object_id")
                    == field(dialog, "SelectedButton").get("object_id")
                    and field(compare, "Value", {"value": 0}).get("value") == 0
                    and field(compare, "OperatorType").get("value") == 3
                    and field(dialog, "DefaultButtonChoice").get("value") == 0,
                    "choice variable or default mismatch")
            for index, (branch, choice) in enumerate(zip(("EffetIfTrue", "EffetIfFalse"), event["choices"])):
                wings = [wing for wing in compiled.get('aviation', {}).get('wings', [])
                         if wing['available'] == {'event': event['id'], 'choice': index}]
                effects(field(selection, branch), choice["effects"] + wings, camp)
            fallback = field(selection, "EffetIfTrue")
        else:
            effects(dispatch, event["effects"], camp)
            if not event['effects']:
                require(objects[dispatch['object_id']]['class'] == 'TGDDescriptorWaitDuration'
                        and field(objects[dispatch['object_id']], 'Duree').get('value') == 0,
                        'text-only event must have an immediate no-op dispatch')
            fallback = dispatch
        require(field(gate, "EffetIfFalse") == fallback, "AI fallback mismatch")
    start += len(compiled["events"])
    for value, reinforcement in zip(rows[start:], compiled["reinforcements"]):
        action_ref, camp = scheduled(value, {"turn": reinforcement["turn"]}, reinforcement["side"])
        effects(action_ref, [reinforcement], camp)
    start += len(compiled['reinforcements'])
    if compiled['campaign'].get('capture_deadline'):start+=1
    for value, wing in zip(rows[start:], timed_wings):
        action_ref, camp = scheduled(value, wing['available'], wing['side'])
        effects(action_ref, [wing], camp)
    start += len(timed_wings)
    creates = {field(obj, 'TypeUnit').get('value'): obj
               for obj in objects if obj['class'] == 'TGDDescriptorCreateUnitOnPosition'}
    withdrawn = [wing for wing in compiled.get('aviation', {}).get('wings', [])
                 if 'withdraw_turn' in wing]
    for value, wing in zip(rows[start:], withdrawn):
        if compiled['aviation'].get('withdrawal_version') == 2:
            root=target(value,'TGDDescriptorSimultaneous')
            retries=actions(root,compiled['campaign']['turns']-wing['withdraw_turn']+1)
            groups=set()
            for turn,value in enumerate(retries,wing['withdraw_turn']):
                action_ref,camp=scheduled(value,{'turn':turn},wing['side'])
                collect_ref,remove_ref=actions(target(action_ref,'TGDDescriptorSequential'),2)
                collect=target(collect_ref,'TGDDescriptorAddDetectedUnitsToUnitGroup')
                detected=target(field(collect,'Detector'),'TGDConditionDetectUnitDansDetecteur')
                detector=target(field(detected,'Detecteur'),'TGDTagDetecteur')
                require(graph['exports'].get(detector['id'])=='$/GDScript/GdItems/CircularZones/AGFW_AirWingTracking',
                        'withdrawal detector is not registered')
                constraints=target(field(detected,'Contrainte'),'TGDContrainteOnUnitAllContrainte')
                tag_ref,camp_ref=field(constraints,'ContrainteList')['items']
                tag=target(tag_ref,'TGDContrainteOnUnitTag');team=target(camp_ref,'TGDContrainteOnUnitTeam')
                require(field(tag,'Tag').get('value')==wing['tracking_tag']
                        and field(team,'Camp').get('object_id')==camp,'withdrawal tracking tag or side differs')
                group=field(collect,'Group')
                remove=target(remove_ref,'TGDDescriptorKillAllUnit')
                require(field(remove,'GroupList')['items']==[group],
                        'air-wing withdrawal must remove only its fresh matching group')
                require(group['object_id'] not in groups,'withdrawal must rescan into a fresh group')
                groups.add(group['object_id'])
            continue
        sequence = target(value, 'TGDDescriptorSequential')
        wait_ref, remove_ref = actions(sequence, 2)
        wait = target(wait_ref, 'TGDDescriptorWaitCondition')
        condition = target(field(wait, 'Condition'), 'TGDConditionVariable')
        compare = target(field(condition, 'Operator'), 'TGDOperatorIntegerCompare')
        require(field(condition, 'Variable').get('object_id') == 381
                and field(compare, 'OperatorType').get('value') == 5
                and field(compare, 'Value').get('value') == wing['withdraw_turn'],
                'air-wing withdrawal turn mismatch')
        remove = target(remove_ref, 'TGDDescriptorKillAllUnit')
        group = field(creates['$/GFX/Pawn/' + wing['unit_export']], 'Group')
        require(field(remove, 'GroupList')['items'] == [group],
                'air-wing withdrawal must remove only its own group')
    initial_wings = [wing for wing in compiled.get('aviation', {}).get('wings', [])
                     if wing['available'].get('turn') == 1]
    if initial_wings:
        launch = objects[compiled['adapter']['script']['launch']]
        initial = actions(launch)[1]
        container = target(initial, 'TGDDescriptorSimultaneous')
        for value, wing in zip(actions(container, len(initial_wings)), initial_wings):
            effects(value, [wing], 284 if wing['side'] == 'nato' else 283)


def _cinematic_script_contract(graph, compiled, reachable):
    cinematic = compiled.get('cinematics')
    if cinematic is None:
        return {'intro_slides': 0, 'ending_variants': 0}
    objects = graph['objects']
    campaign_id = compiled['campaign']['id']
    expected_keys, expected_images = set(), set()
    for side, slides in cinematic['intro'].items():
        for index, slide in enumerate(slides):
            expected_keys.add(authored_text_key(campaign_id, 'intro', side, str(index)).hex())
            expected_images.add(slide['adapter_image'])
    for side, axes in cinematic['endings'].items():
        for axis, variants in axes.items():
            for variant, slide in variants.items():
                expected_keys.add(authored_text_key(
                    campaign_id, 'ending', side, axis, variant).hex())
                expected_images.add(slide['adapter_image'])
    texts = {_property(objects[item], 'LocalizedText')['value_hex']
             for item in reachable
             if objects[item]['class'] == 'TGDDescriptorCutsceneTextComponent'}
    images = {_property(objects[item], 'TextureFile')['value']
              for item in reachable
              if objects[item]['class'] == 'TGDDescriptorCutsceneTextureComponent'}
    if not expected_keys <= texts or not expected_images <= images:
        raise ValueError('Introduction or ending slide text/image is unreachable')
    if cinematic.get('start_camera'):
        cameras = [objects[item] for item in reachable
                   if objects[item]['class'] == 'TGDDescriptorCutsceneStartCameraPath']
        if (len(cameras) != 2
                or {_property(obj, 'VisibleByCamp')['object_id'] for obj in cameras} != {283, 284}
                or any(_property(obj, 'CameraPathName')['value'] != 'camera'
                       or _property(obj, 'StartFromCurrentCameraPosition')['value']
                       or _property(obj, 'TimeInSecond')['value'] > 0.02 for obj in cameras)):
            raise ValueError('Both introductions must explicitly establish the overview camera')
    for sequence_id in (588, 690, 691):
        if sequence_id not in reachable:
            raise ValueError('A native end-game result branch is unreachable')
        actions = _property(objects[sequence_id], 'SubActions')['items']
        if (len(actions) != 3 or any(objects[item['object_id']]['class'] != 'TGDDescriptorIfThenElse'
                                     for item in actions[:2])
                or objects[actions[2]['object_id']]['class'] != 'TGDDescriptorTriggerEndGame'):
            raise ValueError('Three ending slides must precede native game completion')
    return {'intro_slides': 8, 'ending_variants': 18,
            'image_assets': len(expected_images), 'result_branches': 3}


def _decisive_victory_contract(graph, compiled):
    policy = compiled['campaign'].get('victory')
    if not policy:
        return None
    objects = graph['objects']
    def target(obj, field):
        return objects[_property(obj, field)['object_id']]
    def owner(condition, flag_id, side):
        flag = next(row for row in compiled['map']['flags'] if row['id'] == flag_id)
        if condition['class'] != 'TGDConditionPositionInInfluenceMap':
            raise ValueError('Decisive victory must follow capture ownership')
        tag = target(condition, 'Position')
        alliance = next((p['value']['value'] for p in condition['properties']
                         if p['property_name'] == 'Alliance'), 0)
        if (alliance != (1 if side == 'nato' else 0)
                or [_property(tag, 'GUID'+str(i))['value'] for i in range(1, 5)] != list(_int32_words(flag['guid']))):
            raise ValueError('Decisive victory capture flag or coalition differs')
    def ending(sequence, side):
        if sequence['class'] != 'TGDDescriptorSequential':
            raise ValueError('Decisive victory ending sequence is absent')
        end = objects[_property(sequence, 'SubActions')['items'][-1]['object_id']]
        if (end['class'] != 'TGDDescriptorTriggerEndGame'
                or [_property(end, k)['value'] for k in ('VictoryReason', 'VictoryType', 'WinningAlliance')]
                != [6, 6, 1 if side == 'nato' else 0]):
            raise ValueError('Decisive victory result was changed')
    owner(target(objects[384], 'Condition'), policy['nato_capture'], 'nato')
    owner(target(objects[385], 'Condition'), policy['pact_capture'], 'pact')
    ending(target(objects[384], 'ActionsReussi'), 'nato')
    failure = target(objects[384], 'ConditionEchec')
    if failure['class'] != 'TGDConditionOr' or [x['object_id'] for x in _property(failure, 'SousConditions')['items']] != [_property(objects[385], 'Condition')['object_id'], 409]:
        raise ValueError('Decisive victory failure must follow opposing capture or time limit')
    dispatch = objects[_property(objects[402], 'SubActions')['items'][0]['object_id']]
    if dispatch['class'] != 'TGDDescriptorIfThenElse':
        raise ValueError('Decisive victory failure dispatch differs')
    owner(target(dispatch, 'Condition'), policy['pact_capture'], 'pact')
    ending(target(dispatch, 'EffetIfTrue'), 'pact')
    if _property(dispatch, 'EffetIfFalse')['object_id'] != 448:
        raise ValueError('Decisive victory lost its time-limit ending')
    if (_property(objects[384], 'BonusScoreMission')['value'] != 0
            or _property(objects[385], 'BonusScoreMission')['value'] != 0
            or target(objects[385], 'ActionsReussi')['class'] != 'TGDDescriptorWaitDuration'):
        raise ValueError('Decisive capture must not duplicate scoring or ending')
    time_value = {'draw':3,'nato':6,'pact':0}[policy['time_limit']]
    if (_property(objects[586], 'Value')['value'] != time_value
            or [x['object_id'] for x in _property(objects[448], 'SubActions')['items']] != [514]
            or [_property(objects[688], k)['value'] for k in ('VictoryReason', 'VictoryType')] != [6, 3]):
        raise ValueError('Time-limit stalemate must not be overridden by score ratios')
    if policy['time_limit'] != 'draw':
        if _property(objects[454],'OperatorType')['value'] != 0:
            raise ValueError('Scripted deadline winner must be decided when the final turn begins')
        end = objects[920 if policy['time_limit']=='nato' else 924]
        if [_property(end,k)['value'] for k in ('VictoryReason','VictoryType','WinningAlliance')] != [6,6,1 if policy['time_limit']=='nato' else 0]:
            raise ValueError('Time-limit winner must be scripted without score-ratio reclassification')
    return dict(policy)


def authored_script_contract(raw, compiled):
    """Prove the executable campaign boundary from a compiled GDScript."""
    _, graph = decode(raw)
    from .authored_compaction import script_root, verify_release_script
    if script_root(graph) != compiled['adapter']['script']['root']:
        reference, compaction = verify_release_script(raw, compiled)
        report = authored_script_contract(reference, compiled)
        return {**report, 'release_compaction': compaction}
    if compiled['adapter'].get('registration') == 'dynamic':
        from .map_registration import dynamic_script_registration_contract
        dynamic_script_registration_contract(graph, compiled)
    objects = graph["objects"]
    root = compiled["adapter"]["script"]["root"]
    reachable = _reachable_objects(graph, root)
    script = compiled["adapter"]["script"]
    legacy_roots = set(range(386, 392)) | set(script["legacy_launch_presentations"])
    if reachable & legacy_roots:
        raise ValueError("Reachable legacy Bruderkrieg content remains")
    launch_ids = [item["object_id"] for item in
                  _property(objects[script["launch"]], "SubActions")["items"]]
    expected_launch = [script["startup_groups"]]
    initial_wings = [wing for wing in compiled.get('aviation', {}).get('wings', [])
                     if wing['available'].get('turn') == 1]
    if initial_wings:
        initial_container = objects[launch_ids[1]]
        if (initial_container['class'] != 'TGDDescriptorSimultaneous'
                or _property(initial_container, 'NbExecutions')['value'] != 1):
            raise ValueError('Initial air wings require a one-shot startup container')
        expected_launch.append(initial_container['id'])
    frozen_rows = [row for row in compiled["deployments"] if row["frozen_turns"]]
    frozen_version = compiled['adapter'].get('frozen_lifecycle_version', 1)
    launch_frozen_clear_ids = []
    if frozen_rows and frozen_version in (1,4):
        if len(launch_ids) < len(expected_launch) + len(frozen_rows) + 1:
            raise ValueError("Native frozen-state startup actions are missing")
        clear_ids = launch_ids[len(expected_launch):len(expected_launch) + len(frozen_rows)]
        if any(objects[item]["class"] != "TGDDescriptorChangePawnActionPoint"
               or next((p["value"].get("value") for p in objects[item]["properties"]
                        if p["property_name"] == "ActionPointNumber"), 0) != 0
               for item in clear_ids):
            raise ValueError("Frozen native startup AP clear is broken")
        expected_launch.extend(clear_ids)
        launch_frozen_clear_ids = list(clear_ids)
    loss_rows = [row for row in compiled["deployments"]
                 if row.get("initial_losses", {}).get("budget", 0)]
    loss_actions = [objects[item] for item in reachable
                    if objects[item]["class"] == "TGDDescriptorAddCasualtiesToPawn"]
    event_losses = sum('casualties' in effect for event in compiled['events']
                       for effects in ([event['effects']] if not event['choices'] else
                                       [choice['effects'] for choice in event['choices']])
                       for effect in effects)
    air_losses = sum(bool(wing.get('loss_budget'))
                     for wing in compiled.get('aviation', {}).get('wings', []))
    if len(loss_actions) != len(loss_rows) + event_losses + air_losses:
        raise ValueError("Initial/event/air-wing loss action count mismatch")
    if loss_rows:
        loss_container = objects[launch_ids[-2]]
        if (loss_container["class"] != "TGDDescriptorSimultaneous"
                or _property(loss_container, "NbExecutions")["value"] != 1):
            raise ValueError("Initial losses must run once before the kernel")
        action_ids = [item["object_id"] for item in _property(loss_container, "SubActions")["items"]]
        if len(action_ids) != len(loss_rows) or any(objects[item]['class'] != 'TGDDescriptorAddCasualtiesToPawn'
                                                    for item in action_ids):
            raise ValueError("Initial losses must have one startup container")
        for action_id, row in zip(action_ids, loss_rows):
            action = objects[action_id]
            group_id = _property(action, "Group")["object_id"]
            expected_tags = [key for key, value in graph["exports"].items()
                             if value.endswith("/" + row["adapter_slot"]["name"])]
            if (expected_tags != [group_id]
                    or objects[group_id]["class"] != "TGDTagUnitGroup"
                    or _property(action, "Casualties")["value"] != row["initial_losses"]["budget"]
                    or _property(action, "RandomRange")["value"] != row["initial_losses"]["random_range"]
                    or _property(action, "TypeCasualties")["value"] != 1):
                raise ValueError("Initial loss budget or registered group mismatch")
        expected_launch.append(loss_container["id"])
    expected_launch.append(script["strategic_kernel"])
    if launch_ids != expected_launch:
        raise ValueError("Authored launch contains non-authored actions")
    frozen = frozen_rows
    if frozen and frozen_version == 1:
        clear = {p["property_name"]: p["value"] for p in objects[296]["properties"]}
        if (clear.get("ActionPointNumber", {}).get("value", 0) != 0
                or clear["UnitsGroup"]["object_id"] != 309
                or _property(objects[619], "Effet")["value"] != "$/GFX/EffectCapacity/UnitEffect_ArmyGen_No_regen_PA"
                or _property(objects[746], "Value")["value"] != frozen[0]["frozen_turns"]
                or _property(objects[871], "Value")["value"] != frozen[0]["frozen_turns"]
                or _property(objects[529], "ActionPointNumber")["value"] != frozen[0]["action_points"]
                or not {325, 471, 528, 529, 616, 617, 618, 619} <= reachable):
            raise ValueError("Native frozen-state lifecycle is broken")
    if frozen:
        if frozen_version >= 2:
            content_refs = _property(objects[script['campaign_content']], 'SubActions')['items']
            offset = 2 + len(compiled['map']['flags']) + len(_initial_operational_groups(compiled))
            clear_ids = []
            for row, sequence_ref in zip(frozen, content_refs[offset:offset + len(frozen)]):
                sequence = objects[sequence_ref['object_id']]
                steps = _property(sequence, 'SubActions')['items']
                if (sequence['class'] != 'TGDDescriptorSequential' or len(steps) != 4
                        or [objects[x['object_id']]['class'] for x in steps] != [
                            'TGDDescriptorWaitCondition', 'TGDDescriptorChangePawnActionPoint',
                            'TGDDescriptorCompetition', 'TGDDescriptorChangePawnActionPoint']):
                    raise ValueError('Frozen lifecycle must begin on its owner turn and clear AP')
                wait = objects[steps[0]['object_id']]
                condition = objects[_property(wait, 'Condition')['object_id']]
                own_camp = 284 if row['side'] == 'nato' else 283
                if (condition['class'] != 'TGDConditionStrategicIsPlayerTurn'
                        or _property(condition, 'Camp')['object_id'] != own_camp):
                    raise ValueError('Frozen initialization is bound to the wrong coalition')
                clear_id = steps[1]['object_id']
                if _property(objects[clear_id], 'ActionPointNumber')['value'] != 0:
                    raise ValueError('Frozen initialization must clear action points')
                clear_ids.append(clear_id)
                competition = objects[steps[2]['object_id']]
                phases = [objects[x['object_id']] for x in _property(competition, 'SubActions')['items']]
                stop, label, countdown, capacity = phases
                release_condition = objects[_property(stop, 'Condition')['object_id']]
                release_parts = [objects[x['object_id']] for x in _property(release_condition, 'SousConditions')['items']]
                number, owner = release_parts
                comparison = objects[_property(number, 'Operator')['object_id']]
                if (_property(comparison, 'Value')['value'] != row['frozen_turns'] + 1
                        or _property(owner, 'Camp')['object_id'] != own_camp
                        or [x['object_id'] for x in _property(label, 'VisibleByCamps')['items']] != [own_camp]):
                    raise ValueError('Frozen release turn or label visibility is wrong')
                countdown_steps = [objects[x['object_id']] for x in _property(countdown, 'SubActions')['items']]
                if [x['class'] for x in countdown_steps] != [
                        'TGDDescriptorWaitCondition', 'TGDDescriptorWaitCondition',
                        'TGDDescriptorModifieVariableInteger']:
                    raise ValueError('Frozen counter must wait before decrementing')
                camps = [_property(objects[_property(x, 'Condition')['object_id']], 'Camp')['object_id']
                         for x in countdown_steps[:2]]
                if camps != [283 if own_camp == 284 else 284, own_camp]:
                    raise ValueError('Frozen counter follows the wrong side turns')
                if frozen_version == 2:
                    if _property(capacity, 'Effet')['value'] != '$/GFX/EffectCapacity/UnitEffect_ArmyGen_No_regen_PA':
                        raise ValueError('Frozen lifecycle lost its no-regeneration capacity')
                else:
                    if capacity['class'] != 'TGDDescriptorSequential':
                        raise ValueError('Frozen AP gate has the wrong shape')
                    gate_steps=_property(capacity,'SubActions')['items']
                    gate_actions=objects[gate_steps[0]['object_id']]
                    ending_wait=objects[gate_steps[1]['object_id']]
                    false_condition=objects[_property(ending_wait,'Condition')['object_id']]
                    false_compare=objects[_property(false_condition,'Operator')['object_id']]
                    if (len(gate_steps)!=2 or gate_actions['class']!='TGDDescriptorSimultaneous'
                            or ending_wait['class']!='TGDDescriptorWaitCondition'
                            or _property(false_condition,'Variable')['object_id']!=381
                            or _property(false_compare,'Value')['value']!=0):
                        raise ValueError('Frozen AP gate must remain pending until release')
                    phases=_property(gate_actions,'SubActions')['items']
                    if len(phases)!=row['frozen_turns']-1:
                        raise ValueError('Frozen AP gate must cover every locked owner turn')
                    for turn,phase in enumerate(phases,2):
                        wait_ref,clear_ref=_property(objects[phase['object_id']],'SubActions')['items']
                        condition=objects[_property(objects[wait_ref['object_id']],'Condition')['object_id']]
                        number_ref,owner_ref=_property(condition,'SousConditions')['items']
                        number=objects[number_ref['object_id']]; compare=objects[_property(number,'Operator')['object_id']]
                        clear=objects[clear_ref['object_id']]
                        if (_property(compare,'Value')['value']!=turn
                                or _property(objects[owner_ref['object_id']],'Camp')['object_id']!=own_camp
                                or _property(clear,'ActionPointNumber')['value']!=0
                                or _property(clear,'UnitsGroup')['object_id']!=_property(objects[clear_id],'UnitsGroup')['object_id']):
                            raise ValueError('Frozen AP suppression crosses its owner/turn/group boundary')
                    subtree=_reachable_objects(graph,sequence['id'])
                    if any(objects[item]['class']=='TGDDescriptorSetEffect' for item in subtree):
                        raise ValueError('Frozen AP gate must not leave a persistent no-regeneration effect')
        startup_refs = _property(objects[script['startup_groups']], 'SubActions')['items']
        if frozen_version == 4 and launch_frozen_clear_ids != clear_ids:
            raise ValueError('Frozen launch must clear the same collected groups as the turn lifecycle')
        frozen_collectors = startup_refs[len(_initial_operational_groups(compiled)):]
        if len(frozen_collectors) != len(frozen):
            raise ValueError('Frozen pawn group collector count mismatch')
        for row, collector_ref, clear_id in zip(frozen, frozen_collectors, clear_ids):
            collector = objects[collector_ref['object_id']]
            if collector['class'] != 'TGDDescriptorAddUnitGroupListToUnitGroup':
                raise ValueError('Frozen pawn collector class mismatch')
            group_id = _property(collector, 'GroupDestination')['object_id']
            sources = _property(collector, 'ListGroupSource')['items']
            if (len(sources) != 1 or graph['exports'].get(sources[0]['object_id'], '').rsplit('/', 1)[-1]
                    != row['adapter_slot']['name']
                    or _property(objects[clear_id], 'UnitsGroup')['object_id'] != group_id):
                raise ValueError('Frozen pawn source or AP clear targets another battalion')
            labels = [objects[item] for item in reachable
                      if objects[item]['class'] == 'TGDDescriptorDrawLabelOnPosition'
                      and _property(objects[item], 'Group')['object_id'] == group_id]
            restores = [objects[item] for item in reachable
                        if objects[item]['class'] == 'TGDDescriptorChangePawnActionPoint'
                        and _property(objects[item], 'UnitsGroup')['object_id'] == group_id
                        and any(p['property_name'] == 'ActionPointNumber'
                                and p['value'].get('value') == float(row['action_points'])
                                for p in objects[item]['properties'])]
            if len(labels) != 1 or len(restores) != 1:
                raise ValueError('Frozen pawn countdown or AP restoration is missing')
            variable = _property(labels[0], 'ListVariablesForFoldedText')['items']
            if (len(variable) != 1
                    or _property(objects[variable[0]['object_id']], 'Value')['value'] != row['frozen_turns']):
                raise ValueError('Frozen pawn countdown starts at the wrong turn')
    kernel_ids = [item["object_id"] for item in
                  _property(objects[script["strategic_kernel"]], "SubActions")["items"]]
    if kernel_ids != [315, 316, 317, 318, 319]:
        raise ValueError("Authored strategic kernel contains an extra mission block")
    if compiled['adapter'].get('ai_startup_version') == 2 and not (
            _property(objects[349], 'Duree')['value'] > _property(objects[352], 'Duree')['value']):
        raise ValueError('Authored AI orders must be assigned before its controller starts')
    content = _property(objects[script["campaign_content"]], "SubActions")["items"]
    if [item["object_id"] for item in content[:2]] != script["score_victory"]:
        raise ValueError("Generic score-victory objectives are not first")
    reachable_classes = [objects[item]["class"] for item in reachable]
    if any(objects[item]["class"] in {
            "TGDDescriptorCutSceneLaunchVideo", "TGDDescriptorUnlockAchievementForObjective"}
           or (objects[item]["class"] == "TGDDescriptorCutsceneDialog" and item < 1729)
           for item in reachable):
        raise ValueError("Reachable stock campaign presentation or achievement remains")
    from collections import Counter
    production_ai_version = compiled['adapter'].get('production_ai_version', 1)
    if production_ai_version not in (1, 2):
        raise ValueError('Unknown authored production AI version')
    directed_groups = (compiled.get('production', {}).get('groups', [])
                       if production_ai_version == 2 else [])
    divisions = {row['id']: row for row in compiled.get('production', {}).get('divisions', [])}
    production_by_export = {export: group for group in directed_groups
                            for export in group['unit_exports']}
    expected_event_spawns = sum(
        1 for event in compiled["events"]
        for effect in (event["effects"] if not event["choices"] else
                       [item for choice in event["choices"] for item in choice["effects"]])
        if "spawn" in effect)
    creates = [objects[item] for item in reachable
               if objects[item]["class"] == "TGDDescriptorCreateUnitOnPosition"]
    air_wings = compiled.get('aviation', {}).get('wings', [])
    air_exports = {wing['unit_export'] for wing in air_wings}
    production_creates = sum(len(group['unit_exports']) *
                             len(divisions[group['division']]['deployment_points'])
                             for group in directed_groups)
    if len(creates) != (expected_event_spawns + len(compiled["reinforcements"])
                        + len(air_wings) + production_creates):
        raise ValueError("Reachable runtime-spawn count mismatch")
    expected_exports = {
        effect["unit_export"] for event in compiled["events"]
        for effect in (event["effects"] if not event["choices"] else
                       [item for choice in event["choices"] for item in choice["effects"]])
        if "spawn" in effect
    } | {row["unit_export"] for row in compiled["reinforcements"]} | air_exports
    expected_exports |= set(production_by_export)
    actual_export_list = [_property(item, "TypeUnit")["value"].rsplit("/", 1)[-1]
                          for item in creates]
    actual_exports = set(actual_export_list)
    if actual_exports != expected_exports:
        raise ValueError("Reachable runtime-spawn catalog mismatch")
    expected_export_counts = Counter({export: 1 for export in expected_exports})
    for export, group in production_by_export.items():
        expected_export_counts[export] = len(divisions[group['division']]['deployment_points'])
    if Counter(actual_export_list) != expected_export_counts:
        raise ValueError("Reachable runtime spawns duplicate or omit a strategic battalion")
    ordinary_creates = [item for item in creates
                        if _property(item, "TypeUnit")['value'].rsplit('/', 1)[-1]
                        not in production_by_export]
    ordinary_groups = [_property(item, "Group")["object_id"] for item in ordinary_creates]
    if len(ordinary_groups) != len(set(ordinary_groups)):
        raise ValueError("Independent runtime spawns share an AI group")
    production_groups = {}
    for group in directed_groups:
        member_creates = [item for item in creates
                          if _property(item, "TypeUnit")['value'].rsplit('/', 1)[-1]
                          in group['unit_exports']]
        groups_by_export = {}
        for create in member_creates:
            export = _property(create, 'TypeUnit')['value'].rsplit('/', 1)[-1]
            groups_by_export.setdefault(export, set()).add(_property(create, 'Group')['object_id'])
        if (set(groups_by_export) != set(group['unit_exports'])
                or any(len(values) != 1 for values in groups_by_export.values())):
            raise ValueError('AI production alternatives change their strategic group')
        member_group_ids = {export: next(iter(groups_by_export[export]))
                            for export in group['unit_exports']}
        if ((group.get('member_ai') and len(set(member_group_ids.values())) != len(member_group_ids))
                or (not group.get('member_ai') and len(set(member_group_ids.values())) != 1)):
            raise ValueError('AI production group sharing disagrees with member orders')
        production_groups[group['id']] = member_group_ids
        expected_locations = Counter((export, point)
                                     for export in group['unit_exports']
                                     for point in divisions[group['division']]['deployment_points'])
        actual_locations = Counter()
        for create in member_creates:
            if _property(create, 'NbUnit')['value'] != 1:
                raise ValueError('AI production must create each battalion once')
            position = objects[_property(create, 'Position')['object_id']]
            words = [_property(position, f'GUID{i}')['value'] for i in range(1, 5)]
            point, = [item for item in compiled['production']['deployment_points']
                      if list(_int32_words(item['guid'])) == words]
            export = _property(create, 'TypeUnit')['value'].rsplit('/', 1)[-1]
            actual_locations[export, point['id']] += 1
        if actual_locations != expected_locations:
            raise ValueError('AI production spawn priority or battalion catalog mismatch')
    all_production_groups = [value for group in production_groups.values()
                             for value in set(group.values())]
    if len(set(all_production_groups)) != len(all_production_groups) or (
            set(all_production_groups) & set(ordinary_groups)):
        raise ValueError('AI production aliases another strategic group')
    air_creates = [item for item in creates
                   if _property(item, 'TypeUnit')['value'].rsplit('/', 1)[-1] in air_exports]
    ground_creates = [item for item in ordinary_creates if item not in air_creates]
    runtime_groups = ([_property(item, 'Group')['object_id'] for item in ground_creates]
                      + all_production_groups)
    for create in air_creates:
        wing, = [row for row in air_wings
                 if '$/GFX/Pawn/' + row['unit_export'] == _property(create, 'TypeUnit')['value']]
        position = objects[_property(create, 'Position')['object_id']]
        words = [_property(position, f'GUID{index}')['value'] for index in range(1, 5)]
        if words != list(_int32_words(wing['position_guid'])):
            raise ValueError('Air wing airport position mismatch')
        if _property(create, 'NbUnit')['value'] != 1:
            raise ValueError('Air wing must be created exactly once')
        group = _property(create, 'Group')['object_id']
        damage = [item for item in loss_actions
                  if _property(item, 'Group')['object_id'] == group]
        if len(damage) != int(bool(wing.get('loss_budget'))):
            raise ValueError('Air wing arrival loss binding differs')
        if damage:
            damage = damage[0]
            if ([_property(damage, key)['value'] for key in
                 ('Casualties', 'RandomRange', 'TypeCasualties')]
                    != [wing['loss_budget'], 0, 1]):
                raise ValueError('Air wing arrival loss budget differs')
            order = [create['id'], damage['id']]
            if not any(item['class'] == 'TGDDescriptorSequential'
                       and [_ref['object_id'] for _ref in _property(item, 'SubActions')['items']] == order
                       and _property(item, 'NbExecutions')['value'] == 1
                       for item in (objects[oid] for oid in reachable)):
                raise ValueError('Air wing arrival losses must run once after its creation')
    missions = [objects[item] for item in reachable if objects[item]["class"] in {
        "TGDDescriptorStrategicDefend", "TGDDescriptorStrategicMoveAndAttack"}]
    operational_groups = _initial_operational_groups(compiled)
    startup = _property(objects[script["startup_groups"]], "SubActions")["items"]
    authored_collectors = startup[:len(operational_groups)]
    initial_groups = [_property(objects[item["object_id"]], "GroupDestination")["object_id"]
                      for item in authored_collectors]
    if len(initial_groups) != len(set(initial_groups)):
        raise ValueError("Initial formations share an AI group")
    expected_sources = []
    for operational in operational_groups:
        expected_sources.append({
            next(object_id for object_id, value in graph["exports"].items()
                 if value.endswith("/" + deployment["adapter_slot"]["name"]))
            for deployment in operational["deployments"]
        })
    actual_sources = [{item["object_id"] for item in _property(
        objects[collector["object_id"]], "ListGroupSource")["items"]}
        for collector in authored_collectors]
    if actual_sources != expected_sources or sum(map(len, actual_sources)) != len(compiled["deployments"]):
        raise ValueError("Initial operational-group membership mismatch")
    all_groups = set(initial_groups + runtime_groups)
    mission_groups = [_property(item, "Group")["object_id"] for item in missions]
    ai_mission_version = compiled['adapter'].get('ai_mission_version', 1)
    if ai_mission_version not in (1, 2, 3, 4, 5, 6):
        raise ValueError('Unknown authored AI mission version')
    expected_counts = {}
    group_members = {}
    for operational, group in zip(operational_groups, initial_groups):
        group_members[group] = [d['battalion'] for d in operational['deployments']]
        order = operational['order']
        defensive = order['type'] in {'defend', 'hold', 'reserve', 'support', 'air_support'}
        expected_counts[group] = (1 if defensive or ai_mission_version == 1 else
                                  len(order.get('route', [order['target']])) + 1)
    runtime_specs = [effect for event in compiled["events"]
                     for effect in (event["effects"] if not event["choices"] else
                                    [e for choice in event["choices"] for e in choice["effects"]])
                     if 'spawn' in effect]
    runtime_specs += compiled["reinforcements"]
    for create in ground_creates:
        position = objects[_property(create, "Position")['object_id']]
        words = [_property(position, f'GUID{i}')['value'] for i in range(1, 5)]
        spec, = [row for row in runtime_specs if list(_int32_words(row['position_guid'])) == words]
        order = spec['ai']
        group_members[_property(create,'Group')['object_id']] = [spec.get('spawn',spec.get('battalion'))]
        defensive = order['type'] in {'defend', 'hold', 'reserve', 'support', 'air_support'}
        expected_counts[_property(create, 'Group')['object_id']] = (
            1 if defensive or ai_mission_version == 1 else
            len(order.get('route', [order['target']])) + 1)
    for production_group in directed_groups:
        for member, export in zip(production_group['battalions'], production_group['unit_exports']):
            group_id = production_groups[production_group['id']][export]
            order = production_group.get('member_ai', {}).get(member, production_group['ai'])
            group_members[group_id] = ([member] if production_group.get('member_ai')
                                       else production_group['battalions'])
            defensive = order['type'] in {'defend', 'hold', 'reserve', 'support', 'air_support'}
            expected_counts[group_id] = (
                1 if defensive or ai_mission_version == 1 else
                len(order.get('route', [order['target']])) + 1)
    if set(mission_groups) != all_groups or (ai_mission_version<4 and Counter(mission_groups) != Counter(expected_counts)):
        raise ValueError('Authored formations lack the expected staged AI missions')
    def check_order(group, order, side):
        group_missions = [item for item in missions
                          if _property(item, "Group")["object_id"] == group]
        if ai_mission_version>=4:
            plans = [order] + [phase for member in group_members[group]
                              for phase in compiled['campaign']['ai_policy'].get('phase_orders',{}).get(member,[])]
            targets = {row['id']:'$/GDScript/GdItems/Tags/'+row['adapter_slot']['name']
                       for row in compiled['map']['flags']+compiled['map'].get('waypoints',[])}
            allowed_routes = set()
            for plan in plans:
                if plan['type'] in {'defend','hold','reserve','support','air_support'}:
                    continue
                route = plan.get('route',[plan['target']])
                allowed_routes.update(tuple(targets[target] for target in route[index:])
                                      for index in range(len(route)))
            for item in group_missions:
                if (_property(item,'Blocking')['value'] or _property(item,'ExecuteOnlyOnIAActivated')['value']
                        or not _property(item,'OrderCancelable')['value']):
                    raise ValueError('Refreshing AI needs cancelable, nonblocking missions')
                if _property(item,'UseOnlyUnitInMissionToAttack')['value'] != (not compiled['campaign']['ai_policy']['cooperate']):
                    raise ValueError('Refreshing AI cooperation differs')
                if ai_mission_version>=5 and item['class']=='TGDDescriptorStrategicMoveAndAttack':
                    actual=tuple(graph['exports'].get(p['object_id']) for p in _property(item,'Positions')['items'])
                    if actual not in allowed_routes:
                        raise ValueError('Continuous AI must retain its own remaining route to the final objective')
            return
        if ai_mission_version == 3:
            mission_ids = {item['id'] for item in group_missions}
            roots = [item for item in objects if item['class'] == 'TGDDescriptorSequential'
                     and {value['object_id'] for value in _property(item, 'SubActions')['items']} == mission_ids]
            root = roots[0]['id'] if len(group_missions) > 1 and len(roots) == 1 else group_missions[0]['id']
            gates = [item for item in objects if item['id'] in reachable
                     and item['class'] == 'TGDDescriptorIfThenElse'
                     and _property(item, 'EffetIfFalse')['object_id'] == root]
            if len(gates) != 1:
                raise ValueError('Early AI mission lacks an exclusive human-control gate')
            condition = objects[_property(gates[0], 'Condition')['object_id']]
            idle = objects[_property(gates[0], 'EffetIfTrue')['object_id']]
            if (condition['class'] != 'TGDConditionCutSceneIsCampControllableByLocalPlayer'
                    or _property(condition, 'Camp')['object_id'] != (284 if side == 'nato' else 283)
                    or idle['class'] != 'TGDDescriptorWaitDuration' or _property(idle, 'Duree')['value'] != 0):
                raise ValueError('Early AI mission human-control gate owns the wrong side')
            for mission in group_missions:
                if (_property(mission, 'ExecuteOnlyOnIAActivated')['value']
                        or _property(mission, 'UseOnlyUnitInMissionToAttack')['value']
                        != (not compiled['campaign']['ai_policy']['cooperate'])):
                    raise ValueError('Early AI mission activation or cooperation differs')
        defensive = order["type"] in {"defend", "hold", "reserve", "support", "air_support"}
        route = order.get("route", [order["target"]])
        expected_paths = ["$/GDScript/GdItems/Tags/" + next(
            row for row in compiled["map"]["flags"] + compiled['map'].get('waypoints', []) if row["id"] == flag_id
        )["adapter_slot"]["name"] for flag_id in route]
        if ai_mission_version == 1:
            mission, = group_missions
            expected_class = ('TGDDescriptorStrategicDefend' if defensive else
                              'TGDDescriptorStrategicMoveAndAttack')
            if mission['class'] != expected_class:
                raise ValueError('Authored legacy AI mission type mismatch')
            positions = ([_property(mission, 'Position')] if defensive else
                         _property(mission, 'Positions')['items'])
            actual = [graph['exports'].get(item['object_id']) for item in positions]
            if actual != expected_paths:
                raise ValueError('Authored legacy AI route mismatch')
            return
        if defensive:
            mission, = group_missions
            if mission['class'] != 'TGDDescriptorStrategicDefend':
                raise ValueError('Authored defensive AI mission type mismatch')
            actual = graph['exports'].get(_property(mission, 'Position')['object_id'])
            if actual != expected_paths[-1]:
                raise ValueError('Authored defensive AI target mismatch')
            return
        ids = {item['id'] for item in group_missions}
        chains = [item for item in objects if item['class'] == 'TGDDescriptorSequential'
                  and {value['object_id'] for value in
                       _property(item, 'SubActions')['items']} == ids
                  and len(_property(item, 'SubActions')['items']) == len(ids)]
        if len(chains) != 1:
            raise ValueError('Authored AI route lacks one ordered mission chain')
        steps = [objects[item['object_id']] for item in
                 _property(chains[0], 'SubActions')['items']]
        if ([item['class'] for item in steps] !=
                ['TGDDescriptorStrategicMoveAndAttack'] * len(route) +
                ['TGDDescriptorStrategicDefend']):
            raise ValueError('Authored AI route mission phases differ')
        actual_paths = []
        for step in steps[:-1]:
            positions = _property(step, 'Positions')['items']
            if len(positions) != 1:
                raise ValueError('Authored AI waypoint must be its own mission')
            actual_paths.append(graph['exports'].get(positions[0]['object_id']))
        if (actual_paths != expected_paths or
                graph['exports'].get(_property(steps[-1], 'Position')['object_id'])
                != expected_paths[-1]):
            raise ValueError('Authored AI route mismatch')
    for operational, group in zip(operational_groups, initial_groups):
        check_order(group, operational["order"], operational['deployments'][0]['side'])
    for create in ground_creates:
        position = objects[_property(create, "Position")["object_id"]]
        words = [_property(position, f"GUID{i}")["value"] for i in range(1, 5)]
        spec, = [row for row in runtime_specs if list(_int32_words(row["position_guid"])) == words]
        check_order(_property(create, "Group")["object_id"], spec["ai"],
                    'nato' if _property(create, 'Camp')['object_id'] == 284 else 'pact')
    for production_group in directed_groups:
        for member, export in zip(production_group['battalions'], production_group['unit_exports']):
            order = production_group.get('member_ai', {}).get(member, production_group['ai'])
            check_order(production_groups[production_group['id']][export], order, production_group['side'])
    if reachable_classes.count("TGDDescriptorIAStrategicScripted") != 2:
        raise ValueError("Both generic strategic AI controllers must remain reachable")
    if ai_mission_version==6:
        from .refresh_ai import validate_refresh_profiles
        validate_refresh_profiles(graph,compiled)
    if reachable_classes.count("TGDDescriptorGereObjectifWithVariableOwner") != len(compiled["map"]["flags"]):
        raise ValueError("Authored flag-objective count mismatch")
    if reachable_classes.count("TGDDescriptorCutsceneDialogWithMultipleChoice") != sum(
            bool(event["choices"]) for event in compiled["events"]):
        raise ValueError("Authored choice-dialog count mismatch")
    _authored_event_contract(graph, compiled)
    cinematic_report = _cinematic_script_contract(graph, compiled, reachable)
    victory_report = _decisive_victory_contract(graph, compiled)
    from .production import production_script_contract
    production_report = production_script_contract(graph, compiled, reachable)
    date, = [item for item in objects if item["class"] == "TGDDescriptorSetInitialDate"]
    actual_date = [_property(date, name)["value"]
                   for name in ("Annee", "Mois", "Jour", "Periode")]
    if actual_date != compiled["campaign"]["date"]:
        raise ValueError("Authored initial date mismatch")
    for oid, field in ((344, "turns"), (406, "score_to_win"), (410, "score_to_win")):
        if _property(objects[oid], "Value")["value"] != compiled["campaign"][field]:
            raise ValueError("Authored turn/score rule mismatch")
    return {
        "reachable_objects": len(reachable),
        "initial_formations": len(compiled["deployments"]),
        "initial_groups": len(initial_groups),
        "runtime_spawn_groups": len(runtime_groups),
        **({'air_wings': len(air_wings)} if air_wings else {}),
        **({'air_wing_arrival_losses': air_losses,
            'air_wing_withdrawals': sum('withdraw_turn' in wing for wing in air_wings)}
           if air_losses or any('withdraw_turn' in wing for wing in air_wings) else {}),
        **({'capture_deadline': copy.deepcopy(compiled['campaign']['capture_deadline'])}
           if compiled['campaign'].get('capture_deadline') else {}),
        "ai_missions": len(all_groups),
        **({'ai_mission_phases': len(missions)} if ai_mission_version >= 2 else {}),
        "generic_ai_controllers": 2,
        "flags": len(compiled["map"]["flags"]),
        "events": len(compiled["events"]),
        "reinforcements": len(compiled["reinforcements"]),
        "legacy_content_reachable": 0,
        "initial_losses": len(loss_rows),
        "production": production_report,
        **({'victory': victory_report} if victory_report else {}),
        **({'cinematics': cinematic_report} if compiled.get('cinematics') else {}),
    }


def compile_authored_script(raw, compiled):
    """Replace Bruderkrieg's content graph with one authored content graph.

    The engine kernel (turn accounting, score polling, AI turn hand-off,
    tactical battle bridge and end-game dispatch) stays reachable.  Every
    stock objective, presentation, reinforcement and scripted order is cut
    from the only reachable campaign-content root.
    """
    if compiled['adapter'].get('ai_mission_version',0)>=4 or compiled.get('aviation',{}).get('withdrawal_version')==2:
        from .refresh_ai import ensure_aa_schema
        raw=ensure_aa_schema(raw)
    doc, graph = decode(raw)
    ai_mission_version = compiled['adapter'].get('ai_mission_version', 1)
    if ai_mission_version not in (1, 2, 3, 4, 5, 6):
        raise ValueError('Unknown authored AI mission version')
    production_ai_version = compiled['adapter'].get('production_ai_version', 1)
    if production_ai_version not in (1, 2):
        raise ValueError('Unknown authored production AI version')
    objects = copy.deepcopy(graph["objects"])
    original_count = len(objects)
    databases = [obj for obj in objects if obj["class"] == "TCutsceneDescriptorDatabase"]
    if len(databases) != 1 or not databases[0]["is_top_object"]:
        raise ValueError("Authored script requires one top-level cutscene database")
    _property(databases[0], "CutsceneDescriptorList").update(length=0, items=[])
    classes = {name: index for index, name in enumerate(graph["classes"])}
    properties = {(row["class"], row["name"]): row["id"] for row in graph["properties"]}
    required_classes = {
        "TGDDescriptorSequential", "TGDDescriptorSimultaneous", "TGDVariableUnitGroup",
        "TGDDescriptorAddUnitGroupListToUnitGroup", "TGDTagUnitGroup", "TGDTagPosition",
        "TGDDescriptorStrategicDefend", "TGDDescriptorStrategicMoveAndAttack",
        "TGDDescriptorWaitCondition", "TGDConditionVariable", "TGDOperatorIntegerCompare",
        "TGDConditionStrategicIsPlayerTurn", "TGDConditionAnd",
        "TGDConditionPositionInInfluenceMap", "TGDGereObjectifOwningInfo",
        "TGDGereObjectifOwnerInfo", "TGDDescriptorGereObjectifWithVariableOwner",
        "TGDDescriptorCreateUnitOnPosition", "TGDConditionCutSceneIsCampControllableByLocalPlayer",
        "TGDDescriptorAddScoreCamp",
        "TGDDescriptorChangePawnActionPoint", "TGDDescriptorAddCasualtiesToPawn",
        "TGDDescriptorCutsceneTextComponent", "TGDDescriptorCutsceneDialogWithMultipleChoice",
        "TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice",
        "TGDDescriptorCutsceneTextureComponent", "TGDDescriptorCutsceneDialog",
        "TGDDescriptorCutscenePlayDialogList", "TGDDescriptorEncapsuleCutscene",
    }
    missing = sorted(required_classes - set(classes))
    if missing:
        raise ValueError(f"Bruderkrieg script lacks authored schema class: {missing[0]}")

    def ref(object_id, class_name):
        return {"type_id": 3149642683, "type": "obj_ref", "reference_prefix": True,
                "object_id": object_id, "class_id": classes[class_name]}

    def integer(value):
        return {"type_id": 2, "type": "int32", "reference_prefix": False, "value": int(value)}

    def uint(value):
        return {"type_id": 3, "type": "uint32", "reference_prefix": False, "value": int(value)}

    def boolean(value):
        return {"type_id": 0, "type": "bool", "reference_prefix": False, "value": bool(value)}

    def floating(value):
        return {"type_id": 5, "type": "float32", "reference_prefix": False, "value": float(value)}

    def loc(value):
        return {"type_id": 29, "type": "loc_hash", "reference_prefix": False,
                "value_hex": value.hex()}

    def string(value):
        if value not in graph["strings"]:
            graph["strings"].append(value)
        return {"type_id": 7, "type": "strg_ref", "reference_prefix": False,
                "index": graph["strings"].index(value), "value": value}

    def listref(values):
        return {"type_id": 17, "type": "list", "reference_prefix": False,
                "length": len(values), "items": values}

    def prop(class_name, name, value):
        key = (class_name, name)
        if key not in properties:
            raise ValueError(f"Bruderkrieg script lacks property schema {class_name}.{name}")
        return {"property_id": properties[key], "property_name": name, "value": value}

    def add(class_name, values=()):
        object_id = len(objects)
        objects.append({"id": object_id, "class": class_name, "class_id": classes[class_name],
                        "is_top_object": False, "properties": list(values)})
        return object_id

    def tag(export_name):
        path = f"$/GDScript/GdItems/Tags/{export_name}"
        found = [object_id for object_id, value in graph["exports"].items() if value == path]
        if len(found) != 1 or objects[found[0]]["class"] != "TGDTagPosition":
            raise ValueError(f"Missing Bruderkrieg position shell: {export_name}")
        return found[0]

    def unit_tag(spawn_name):
        found = [object_id for object_id, value in graph["exports"].items()
                 if value.endswith("/" + spawn_name)]
        if len(found) != 1 or objects[found[0]]["class"] != "TGDTagUnitGroup":
            raise ValueError(f"Missing Bruderkrieg unit tag: {spawn_name}")
        return found[0]

    def patch_tag_guid(object_id, guid):
        for index, word in enumerate(_int32_words(guid), 1):
            _property(objects[object_id], f"GUID{index}")["value"] = word

    dynamic_tags = []
    if compiled['adapter'].get('registration') == 'dynamic':
        from .map_registration import campaign_map_items
        map_items = campaign_map_items(compiled)
        registrations = [(row['name'], 'TGDTagPosition', row['guid'], 'Tags')
                         for row in map_items if row['kind'] == 'position']
        registrations += [(row['name'], 'TGDTagUnitGroup', row['guid'],
                           'Camp_1' if row['side'] == 'nato' else 'Camp_0')
                          for row in map_items if row['kind'] == 'spawn']
        registrations += [(row['name'], 'TGDTagPosition', row['guid'],
                           'SpecificStrategicBattleground')
                          for row in map_items if row['kind'] == 'battleground']
        registrations += [(row['name'],'TGDTagDetecteur',row['guid'],'CircularZones')
                          for row in map_items if row['kind']=='detector']
        for name, class_name, guid, folder in registrations:
            path = '$/GDScript/GdItems/' + folder + '/' + name
            if path in graph['exports'].values():
                raise ValueError('Dynamic tag export collision: ' + path)
            object_id = add(class_name, [prop(class_name, 'GUID' + str(index), integer(word))
                           for index, word in enumerate(_int32_words(guid), 1)])
            graph['exports'][object_id] = path
            dynamic_tags.append(object_id)

    flag_tags = {}
    for row in compiled["map"]["flags"]:
        object_id = tag(row["adapter_slot"]["name"])
        patch_tag_guid(object_id, row["guid"])
        flag_tags[row["id"]] = object_id
    runtime_tags = {}
    for row in compiled["map"]["runtime_positions"]:
        object_id = tag(row["adapter_slot"]["name"])
        patch_tag_guid(object_id, row["guid"])
        runtime_tags[row["id"]] = object_id

    # Campaign scalar rules.
    _property(objects[344], "Value")["value"] = compiled["campaign"]["turns"]
    _property(objects[406], "Value")["value"] = compiled["campaign"]["score_to_win"]
    _property(objects[410], "Value")["value"] = compiled["campaign"]["score_to_win"]
    dates = [obj for obj in objects if obj["class"] == "TGDDescriptorSetInitialDate"]
    if len(dates) != 1:
        raise ValueError("Pinned initial-date descriptor changed")
    for name, value in zip(("Annee", "Mois", "Jour", "Periode"),
                           compiled["campaign"]["date"]):
        _property(dates[0], name)["value"] = value

    campaign_id = compiled["campaign"]["id"]
    if compiled['adapter'].get('ai_startup_version') == 2:
        _property(objects[349], 'Duree')['value'] = 3.0
    _property(objects[384], "ObjectiveText")["value_hex"] = authored_text_key(campaign_id, "victory", "nato").hex()
    _property(objects[385], "ObjectiveText")["value_hex"] = authored_text_key(campaign_id, "victory", "pact").hex()
    # End-game presentation is campaign-specific; retain only the generic
    # dispatch action which asks the engine for the actual victory type.
    for sequence_id in (402, 403, 407):
        actions = _property(objects[sequence_id], "SubActions")
        generic = [item for item in actions["items"] if item.get("object_id") == 448]
        if len(generic) != 1:
            raise ValueError("Pinned generic end-game dispatch changed")
        actions["items"] = generic
        actions["length"] = 1
    # The dispatch itself also contains stock cutscenes and achievements.
    # Keep its native victory classification and end-game actions only.
    for sequence_id, end_id in ((588, 688), (690, 920), (691, 924)):
        if objects[end_id]["class"] != "TGDDescriptorTriggerEndGame":
            raise ValueError("Pinned end-game action changed")
        actions = _property(objects[sequence_id], "SubActions")
        actions["items"] = [ref(end_id, "TGDDescriptorTriggerEndGame")]
        actions["length"] = 1

    # Build entirely new capture-point managers from authored flags.
    objective_ids = []

    def position_owner_condition(position_id, side):
        condition_props = [
            prop("TGDConditionPositionInInfluenceMap", "MinimumeDurationInSec", floating(1)),
            prop("TGDConditionPositionInInfluenceMap", "Position",
                 ref(position_id, "TGDTagPosition")),
        ]
        if side == "nato":
            condition_props.insert(0, prop(
                "TGDConditionPositionInInfluenceMap", "Alliance", uint(1)))
        return add("TGDConditionPositionInInfluenceMap", condition_props)

    def flag_owner_condition(flag_id, side):
        return position_owner_condition(flag_tags[flag_id], side)

    for flag in compiled["map"]["flags"]:
        position = flag_tags[flag["id"]]
        name_key = authored_text_key(campaign_id, "flag", flag["id"])
        owner_infos = []
        for side in ("nato", "pact"):
            owning = add("TGDGereObjectifOwningInfo", [
                prop("TGDGereObjectifOwningInfo", "ObjectiveEtiquetteText", loc(name_key)),
                prop("TGDGereObjectifOwningInfo", "ObjectiveText", loc(name_key)),
            ])
            not_owning = add("TGDGereObjectifOwningInfo", [
                prop("TGDGereObjectifOwningInfo", "ObjectiveEtiquetteText", loc(name_key)),
                prop("TGDGereObjectifOwningInfo", "ObjectiveText", loc(name_key)),
            ])
            condition = flag_owner_condition(flag["id"], side)
            info_props = [
                prop("TGDGereObjectifOwnerInfo", "InfoWhenNotOwning", ref(not_owning, "TGDGereObjectifOwningInfo")),
                prop("TGDGereObjectifOwnerInfo", "InfoWhenOwning", ref(owning, "TGDGereObjectifOwningInfo")),
                prop("TGDGereObjectifOwnerInfo", "OwningCondition", ref(condition, "TGDConditionPositionInInfluenceMap")),
            ]
            if side == "nato":
                info_props.insert(0, prop("TGDGereObjectifOwnerInfo", "Alliance", integer(1)))
            owner_infos.append(add("TGDGereObjectifOwnerInfo", info_props))
        objective_ids.append(add("TGDDescriptorGereObjectifWithVariableOwner", [
            prop("TGDDescriptorGereObjectifWithVariableOwner", "BonusScoreIncomeMission", integer(flag["hold_score"])),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "BonusScoreMission", integer(flag["capture_score"])),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "LabelComponent", _property(objects[386], "LabelComponent")),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "ObjectiveName", loc(name_key)),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "Position", ref(position, "TGDTagPosition")),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "ShowEtiquette", boolean(True)),
            prop("TGDDescriptorGereObjectifWithVariableOwner", "OwnerInfoList",
                 listref([ref(item, "TGDGereObjectifOwnerInfo") for item in owner_infos])),
        ]))

    def strategic_mission(group, order, side=None, members=()):
        mission_tags = {**flag_tags, **{row['id']:runtime_tags[row['id']] for row in compiled['map'].get('waypoints', [])}}
        position = mission_tags[order["target"]]
        cooperate = compiled['campaign'].get('ai_policy', {}).get('cooperate', False)
        attack_radius = compiled['campaign'].get('ai_policy', {}).get('attack_radius', 707)
        active_only = ai_mission_version < 3
        def protect(action, kind):
            if ai_mission_version < 3:
                return action, kind
            if side not in ('nato','pact'):
                raise ValueError('Early AI mission registration needs its owning side')
            local = add('TGDConditionCutSceneIsCampControllableByLocalPlayer', [
                prop('TGDConditionCutSceneIsCampControllableByLocalPlayer','Camp',ref(284 if side=='nato' else 283,'TGDVariableCamp'))])
            no_op = add('TGDDescriptorWaitDuration',[prop('TGDDescriptorWaitDuration','Duree',floating(0))])
            gate = add('TGDDescriptorIfThenElse',[
                prop('TGDDescriptorIfThenElse','Condition',ref(local,'TGDConditionCutSceneIsCampControllableByLocalPlayer')),
                prop('TGDDescriptorIfThenElse','EffetIfTrue',ref(no_op,'TGDDescriptorWaitDuration')),
                prop('TGDDescriptorIfThenElse','EffetIfFalse',ref(action,kind))])
            return gate,'TGDDescriptorIfThenElse'
        if ai_mission_version>=4:
            from .refresh_ai import scheduled_missions
            return scheduled_missions(group,order,side,members,compiled,add=add,prop=prop,ref=ref,
                boolean=boolean,integer=integer,uint=uint,listref=listref,turn_condition=turn_condition,
                wait_then=wait_then,owner=lambda target,camp: position_owner_condition(mission_tags[target],camp),
                tags=mission_tags,protect=protect)
        def defend(target):
            class_name = "TGDDescriptorStrategicDefend"
            mission = add(class_name, [
                prop(class_name, "Blocking", boolean(True)),
                prop(class_name, "Group", ref(group, "TGDVariableUnitGroup")),
                prop(class_name, "AttackEnemyInRadius", integer(1060)),
                prop(class_name, "ExecuteOnlyOnIAActivated", boolean(active_only)),
                prop(class_name, "Position", ref(target, "TGDTagPosition")),
                prop(class_name, "UseOnlyUnitInMissionToAttack", boolean(not cooperate)),
                prop(class_name, "WaypointReachedRadius", integer(707)),
            ])
            return mission, class_name
        if order["type"] in {"defend", "hold", "reserve", "support", "air_support"}:
            return protect(*defend(position))
        route = order.get("route", [order["target"]])
        if ai_mission_version == 1:
            class_name = 'TGDDescriptorStrategicMoveAndAttack'
            mission = add(class_name, [
                prop(class_name, 'Blocking', boolean(True)),
                prop(class_name, 'Group', ref(group, 'TGDVariableUnitGroup')),
                prop(class_name, 'AttackEnemyInRadius', integer(707)),
                prop(class_name, 'ExecuteOnlyOnIAActivated', boolean(True)),
                prop(class_name, 'Positions', listref([
                    ref(mission_tags[flag_id], 'TGDTagPosition') for flag_id in route])),
                prop(class_name, 'UseOnlyUnitInMissionToAttack', boolean(True)),
                prop(class_name, 'WaypointReachedRadius', integer(707)),
            ])
            return mission, class_name
        steps = []
        for flag_id in route:
            class_name = "TGDDescriptorStrategicMoveAndAttack"
            mission = add(class_name, [
                prop(class_name, "Blocking", boolean(True)),
                prop(class_name, "Group", ref(group, "TGDVariableUnitGroup")),
                prop(class_name, "AttackEnemyInRadius", integer(attack_radius)),
                prop(class_name, "ExecuteOnlyOnIAActivated", boolean(active_only)),
                prop(class_name, "Positions", listref([ref(mission_tags[flag_id], "TGDTagPosition")])),
                prop(class_name, "UseOnlyUnitInMissionToAttack", boolean(not cooperate)),
                prop(class_name, "WaypointReachedRadius", integer(707)),
            ])
            steps.append(ref(mission, class_name))
        hold, hold_class = defend(position)
        steps.append(ref(hold, hold_class))
        chain = add('TGDDescriptorSequential', [
            prop('TGDDescriptorSequential', 'SubActions', listref(steps)),
            prop('TGDDescriptorSequential', 'NbExecutions', uint(1)),
        ])
        return protect(chain, 'TGDDescriptorSequential')

    deadline_rule=compiled['campaign'].get('capture_deadline')
    deadline_variable=add('TGDVariableInteger',[prop('TGDVariableInteger','Value',integer(0))]) if deadline_rule else None
    def deadline_status(blocked):
        compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','Value',integer(1 if blocked else 0))])
        return add('TGDConditionVariable',[prop('TGDConditionVariable','Variable',ref(deadline_variable,'TGDVariableInteger')),
            prop('TGDConditionVariable','Operator',ref(compare,'TGDOperatorIntegerCompare'))])

    intro_ready = {}
    if compiled.get('cinematics') is not None:
        intro_ready = {side: add('TGDVariableInteger', [
            prop('TGDVariableInteger', 'Value', integer(1))])
            for side in ('nato', 'pact')}

    def side_turn_condition(side):
        camp = 284 if side == "nato" else 283
        return add("TGDConditionStrategicIsPlayerTurn", [
            prop("TGDConditionStrategicIsPlayerTurn", "Camp", ref(camp, "TGDVariableCamp")),
        ])

    def turn_condition(turn, side):
        compare = add("TGDOperatorIntegerCompare", [
            prop("TGDOperatorIntegerCompare", "Value", integer(turn)),
        ])
        number = add("TGDConditionVariable", [
            prop("TGDConditionVariable", "Operator", ref(compare, "TGDOperatorIntegerCompare")),
            prop("TGDConditionVariable", "Variable", ref(381, "TGDVariableInteger")),
        ])
        side_turn = side_turn_condition(side)
        return add("TGDConditionAnd", [
            prop("TGDConditionAnd", "SousConditions", listref([
                ref(number, "TGDConditionVariable"),
                ref(side_turn, "TGDConditionStrategicIsPlayerTurn"),
            ])),
        ])

    def event_trigger_condition(trigger, side):
        if 'capture_deadline' in trigger:
            status=deadline_status(trigger['capture_deadline']=='blocked')
            timing=turn_condition(trigger['turn'],side) if 'turn' in trigger else side_turn_condition(side)
            return add('TGDConditionAnd',[prop('TGDConditionAnd','SousConditions',listref([
                ref(status,'TGDConditionVariable'),ref(timing,objects[timing]['class'])]))])
        if "turn" in trigger:
            condition = turn_condition(trigger["turn"], side)
            if trigger['turn'] == 1 and side in intro_ready:
                compare = add('TGDOperatorIntegerCompare', [
                    prop('TGDOperatorIntegerCompare', 'Value', integer(0))])
                done = add('TGDConditionVariable', [
                    prop('TGDConditionVariable', 'Operator', ref(compare, 'TGDOperatorIntegerCompare')),
                    prop('TGDConditionVariable', 'Variable', ref(intro_ready[side], 'TGDVariableInteger')),
                ])
                condition = add('TGDConditionAnd', [
                    prop('TGDConditionAnd', 'SousConditions', listref([
                        ref(condition, 'TGDConditionAnd'), ref(done, 'TGDConditionVariable')]))])
            return condition
        if 'capture' in trigger:
            trigger = {'flag': trigger['capture'], 'owner': side}
        owner = flag_owner_condition(trigger["flag"], trigger["owner"])
        player_turn = side_turn_condition(side)
        return add("TGDConditionAnd", [
            prop("TGDConditionAnd", "SousConditions", listref([
                ref(owner, "TGDConditionPositionInInfluenceMap"),
                ref(player_turn, "TGDConditionStrategicIsPlayerTurn"),
            ])),
        ])

    def wait_then(action, action_class, condition):
        wait = add("TGDDescriptorWaitCondition", [
            prop("TGDDescriptorWaitCondition", "Condition", ref(condition, objects[condition]["class"])),
        ])
        return add("TGDDescriptorSequential", [
            prop("TGDDescriptorSequential", "SubActions", listref([
                ref(wait, "TGDDescriptorWaitCondition"), ref(action, action_class),
            ])),
            prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
        ])

    def schedule_event(action, event):
        if 'first_enemy_destroyed' in event['trigger']:
            variable = add('TGDVariableInteger', [prop('TGDVariableInteger', 'Value', integer(0))])
            read = add('TGDDescriptorGetAllianceActualScore', [
                prop('TGDDescriptorGetAllianceActualScore', 'ScorePointType', integer(0)),
                prop('TGDDescriptorGetAllianceActualScore', 'Alliance', integer(1 if event['side'] == 'nato' else 0)),
                prop('TGDDescriptorGetAllianceActualScore', 'Variable', ref(variable, 'TGDVariableInteger')),
            ])
            delay = add('TGDDescriptorWaitDuration', [prop('TGDDescriptorWaitDuration', 'Duree', floating(1))])
            poll = add('TGDDescriptorSequential', [
                prop('TGDDescriptorSequential', 'SubActions', listref([
                    ref(read, 'TGDDescriptorGetAllianceActualScore'), ref(delay, 'TGDDescriptorWaitDuration')])),
                prop('TGDDescriptorSequential', 'NbExecutions', uint(4294967295)),
            ])
            compare = add('TGDOperatorIntegerCompare', [
                prop('TGDOperatorIntegerCompare', 'OperatorType', integer(4)),
                prop('TGDOperatorIntegerCompare', 'Value', integer(0)),
            ])
            positive = add('TGDConditionVariable', [
                prop('TGDConditionVariable', 'Variable', ref(variable, 'TGDVariableInteger')),
                prop('TGDConditionVariable', 'Operator', ref(compare, 'TGDOperatorIntegerCompare')),
            ])
            player_turn = side_turn_condition(event['side'])
            condition = add('TGDConditionAnd', [prop('TGDConditionAnd', 'SousConditions', listref([
                ref(positive, 'TGDConditionVariable'), ref(player_turn, 'TGDConditionStrategicIsPlayerTurn')]))])
            presentation = wait_then(action, 'TGDDescriptorIfThenElse', condition)
            simultaneous = add('TGDDescriptorSimultaneous', [
                prop('TGDDescriptorSimultaneous', 'SubActions', listref([
                    ref(poll, 'TGDDescriptorSequential'), ref(presentation, 'TGDDescriptorSequential')])),
                prop('TGDDescriptorSimultaneous', 'NbExecutions', uint(1)),
            ])
            return simultaneous, 'TGDDescriptorSimultaneous'
        condition = event_trigger_condition(event['trigger'], event['side'])
        scheduled = wait_then(action, 'TGDDescriptorIfThenElse', condition)
        if 'capture' in event['trigger']:
            enemy = 'pact' if event['side'] == 'nato' else 'nato'
            condition = flag_owner_condition(event['trigger']['capture'], enemy)
            scheduled = wait_then(scheduled, 'TGDDescriptorSequential', condition)
        return scheduled, 'TGDDescriptorSequential'

    # One private unit group per distinct authored operation.  Battalions with
    # the same side/type/target/start turn move and fight as one native-style
    # operational group, while unrelated formations never overlap.
    collectors = []
    mission_roots = []
    for operational in _initial_operational_groups(compiled):
        group = add("TGDVariableUnitGroup")
        sources = [unit_tag(deployment["adapter_slot"]["name"])
                   for deployment in operational["deployments"]]
        collectors.append(add("TGDDescriptorAddUnitGroupListToUnitGroup", [
            prop("TGDDescriptorAddUnitGroupListToUnitGroup", "GroupDestination", ref(group, "TGDVariableUnitGroup")),
            prop("TGDDescriptorAddUnitGroupListToUnitGroup", "ListGroupSource",
                 listref([ref(source, "TGDTagUnitGroup") for source in sources])),
        ]))
        order = operational["order"]
        mission, mission_class = strategic_mission(group, order, operational['side'],[d['battalion'] for d in operational['deployments']])
        if order["start_turn"] > 1:
            mission = wait_then(mission, mission_class, turn_condition(
                order["start_turn"], operational["side"]))
            mission_class = "TGDDescriptorSequential"
        mission_roots.append((mission, mission_class))

    startup = _property(objects[291], "SubActions")
    startup["items"] = [ref(item, "TGDDescriptorAddUnitGroupListToUnitGroup") for item in collectors]
    frozen_sequences = []
    frozen_launch = []
    frozen_deployments = [deployment for deployment in compiled["deployments"]
                          if deployment["frozen_turns"]]
    frozen_version = compiled['adapter'].get('frozen_lifecycle_version', 1)
    if frozen_version not in (1, 2, 3, 4):
        raise ValueError('Unknown authored frozen lifecycle version')

    def owned_frozen_shell(deployment):
        """Bind the stock countdown to its owner and start after that owner's turn begins."""
        own_camp = 284 if deployment['side'] == 'nato' else 283
        other_camp = 283 if own_camp == 284 else 284
        pawn_group = add('TGDVariableUnitGroup')
        pawn_tag = unit_tag(deployment['adapter_slot']['name'])
        fixed = {309:pawn_group, 365:pawn_tag, 284:own_camp, 283:other_camp, 381:381}
        cloned = {}

        def transplant(old_id):
            if old_id in fixed:
                return fixed[old_id]
            if old_id in cloned:
                return cloned[old_id]
            source = graph['objects'][old_id]
            new_id = add(source['class'])
            cloned[old_id] = new_id
            values = copy.deepcopy(source['properties'])
            if old_id == 471:
                steps = next(p['value'] for p in values if p['property_name'] == 'SubActions')
                steps.update(items=steps['items'][:2], length=2)

            def remap(value):
                if isinstance(value, dict):
                    if value.get('type') == 'obj_ref' and value.get('object_id') != 0xffffffff:
                        target = transplant(value['object_id'])
                        value.update(object_id=target, class_id=objects[target]['class_id'])
                    for child in value.values():
                        remap(child)
                elif isinstance(value, list):
                    for child in value:
                        remap(child)
            remap(values)
            objects[new_id]['properties'] = values
            return new_id

        collector, clear, timeline = transplant(325), transplant(296), transplant(471)
        objects[clear]['properties'].append(prop('TGDDescriptorChangePawnActionPoint',
                                                'ActionPointNumber', floating(0)))
        _property(objects[cloned[746]], 'Value')['value'] = deployment['frozen_turns']
        _property(objects[cloned[871]], 'Value')['value'] = deployment['frozen_turns'] + 1
        _property(objects[cloned[529]], 'ActionPointNumber')['value'] = float(deployment['action_points'])
        label = objects[cloned[617]]
        _property(label, 'FoldedText')['value_hex'] = authored_text_key(campaign_id, 'frozen', 'countdown').hex()
        _property(label, 'Text')['value_hex'] = authored_text_key(campaign_id, 'frozen', 'empty').hex()
        _property(label, 'VisibleByCamps').update(items=[ref(own_camp, 'TGDVariableCamp')], length=1)
        # Wait for the other side, then the next owner turn, before reducing
        # the displayed remaining count. No decrement happens on the first turn.
        _property(objects[cloned[618]], 'SubActions').update(items=[
            ref(cloned[749], 'TGDDescriptorWaitCondition'),
            ref(cloned[748], 'TGDDescriptorWaitCondition'),
            ref(cloned[747], 'TGDDescriptorModifieVariableInteger')], length=3)
        first_turn = add('TGDDescriptorWaitCondition', [
            prop('TGDDescriptorWaitCondition', 'Condition', ref(
                side_turn_condition(deployment['side']), 'TGDConditionStrategicIsPlayerTurn'))])
        _property(objects[timeline], 'SubActions').update(items=[
            ref(first_turn, 'TGDDescriptorWaitCondition'),
            ref(clear, 'TGDDescriptorChangePawnActionPoint'),
            ref(cloned[528], 'TGDDescriptorCompetition'),
            ref(cloned[529], 'TGDDescriptorChangePawnActionPoint')], length=4)
        if frozen_version >= 3:
            suppress=[]
            for turn in range(2,deployment['frozen_turns']+1):
                suppress.append(ref(wait_then(clear,'TGDDescriptorChangePawnActionPoint',
                    turn_condition(turn,deployment['side'])),'TGDDescriptorSequential'))
            gate=add('TGDDescriptorSimultaneous',[
                prop('TGDDescriptorSimultaneous','SubActions',listref(suppress)),
                prop('TGDDescriptorSimultaneous','NbExecutions',uint(1))])
            zero_compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','Value',integer(0))])
            never=add('TGDConditionVariable',[
                prop('TGDConditionVariable','Variable',ref(381,'TGDVariableInteger')),
                prop('TGDConditionVariable','Operator',ref(zero_compare,'TGDOperatorIntegerCompare'))])
            pending=add('TGDDescriptorWaitCondition',[prop('TGDDescriptorWaitCondition','Condition',ref(never,'TGDConditionVariable'))])
            gate=add('TGDDescriptorSequential',[
                prop('TGDDescriptorSequential','SubActions',listref([
                    ref(gate,'TGDDescriptorSimultaneous'),ref(pending,'TGDDescriptorWaitCondition')])),
                prop('TGDDescriptorSequential','NbExecutions',uint(1))])
            phases=_property(objects[cloned[528]],'SubActions')
            phases['items'][-1]=ref(gate,'TGDDescriptorSequential')
        return collector, timeline

    def clone_frozen_shell(deployment):
        """Transplant the pinned working stock lifecycle for another pawn."""
        pawn_tag = unit_tag(deployment["adapter_slot"]["name"])
        pawn_group = add("TGDVariableUnitGroup")
        fixed = {309: pawn_group, 365: pawn_tag, 283: 283, 284: 284, 381: 381}
        cloned = {}

        def transplant(old_id):
            if old_id in fixed:
                return fixed[old_id]
            if old_id in cloned:
                return cloned[old_id]
            source = objects[old_id]
            new_id = add(source["class"])
            cloned[old_id] = new_id
            values = copy.deepcopy(source["properties"])

            def remap(value):
                if isinstance(value, dict):
                    if value.get("type") == "obj_ref" and value.get("object_id") != 0xffffffff:
                        target = transplant(value["object_id"])
                        value["object_id"] = target
                        value["class_id"] = objects[target]["class_id"]
                    for child in value.values():
                        remap(child)
                elif isinstance(value, list):
                    for child in value:
                        remap(child)
            remap(values)
            objects[new_id]["properties"] = values
            return new_id

        collector = transplant(325)
        _property(objects[collector], 'ListGroupSource').update(
            items=[ref(pawn_tag, 'TGDTagUnitGroup')], length=1)
        clear = transplant(296)
        timeline = transplant(471)
        _property(objects[cloned[746]], "Value")["value"] = deployment["frozen_turns"]
        _property(objects[cloned[871]], "Value")["value"] = deployment["frozen_turns"]
        _property(objects[cloned[529]], "ActionPointNumber")["value"] = float(deployment["action_points"])
        label = objects[cloned[617]]
        _property(label, "FoldedText")["value_hex"] = authored_text_key(
            campaign_id, "frozen", "countdown").hex()
        _property(label, "Text")["value_hex"] = authored_text_key(
            campaign_id, "frozen", "empty").hex()
        return collector, clear, timeline

    for deployment in compiled["deployments"]:
        if not deployment["frozen_turns"]:
            continue
        if frozen_version >= 2:
            collector_id, timeline_id = owned_frozen_shell(deployment)
            startup['items'].append(ref(collector_id, 'TGDDescriptorAddUnitGroupListToUnitGroup'))
            if frozen_version >= 4:
                clear_id=_property(objects[timeline_id],'SubActions')['items'][1]['object_id']
                frozen_launch.append(ref(clear_id,'TGDDescriptorChangePawnActionPoint'))
            frozen_sequences.append((timeline_id, 'TGDDescriptorSequential'))
            continue
        # The current Bruderkrieg profile deliberately exposes only the one
        # isolated native frozen shell (142PzG -> group 309). Dynamic
        # registration may use any generated slot name, but still has one
        # deterministic lifecycle shell.
        if (not deployment["adapter_slot"].get("dynamic")
                and deployment["adapter_slot"]["name"] != "P0_C0_pion_RFA_5PzD_142PzG_1"):
            raise ValueError("Profile assigned an unsupported frozen shell")
        if not frozen_sequences:
            collector_id, clear_id, timeline_id = 325, 296, 471
            _property(objects[325], 'ListGroupSource').update(
                items=[ref(unit_tag(deployment['adapter_slot']['name']), 'TGDTagUnitGroup')],
                length=1)
            _property(objects[529], "ActionPointNumber")["value"] = float(deployment["action_points"])
            _property(objects[746], "Value")["value"] = deployment["frozen_turns"]
            _property(objects[871], "Value")["value"] = deployment["frozen_turns"]
        else:
            collector_id, clear_id, timeline_id = clone_frozen_shell(deployment)
        startup["items"].append(ref(collector_id, "TGDDescriptorAddUnitGroupListToUnitGroup"))
        frozen_launch.append(ref(clear_id, "TGDDescriptorChangePawnActionPoint"))
        # Object 471 is the native, working countdown/no-regeneration/restore
        # sequence.  Its final stock notification is removed.
        sequence = _property(objects[471], "SubActions")
        sequence["items"] = sequence["items"][:2]
        sequence["length"] = 2
        labels = [obj for obj in objects if obj["class"] == "TGDDescriptorDrawLabelOnPosition"
                  and any(p["property_name"] == "Group" and p["value"].get("object_id") == 309
                          for p in obj["properties"])]
        if len(labels) != 1:
            raise ValueError("Pinned frozen countdown label changed")
        variable_refs = _property(labels[0], "ListVariablesForFoldedText")["items"]
        _property(labels[0], "FoldedText")["value_hex"] = authored_text_key(campaign_id, "frozen", "countdown").hex()
        _property(labels[0], "Text")["value_hex"] = authored_text_key(campaign_id, "frozen", "empty").hex()
        if len(variable_refs) != 1:
            raise ValueError("Pinned frozen countdown variable changed")
        _property(objects[variable_refs[0]["object_id"]], "Value")["value"] = frozen_deployments[0]["frozen_turns"]
        frozen_sequences.append((timeline_id, "TGDDescriptorSequential"))
    startup["length"] = len(startup["items"])

    loss_actions = []
    for deployment in compiled["deployments"]:
        losses = deployment.get("initial_losses", {"budget": 0, "random_range": 0})
        if losses["budget"]:
            loss_actions.append(add("TGDDescriptorAddCasualtiesToPawn", [
                prop("TGDDescriptorAddCasualtiesToPawn", "Casualties", integer(losses["budget"])),
                prop("TGDDescriptorAddCasualtiesToPawn", "RandomRange", integer(losses["random_range"])),
                prop("TGDDescriptorAddCasualtiesToPawn", "TypeCasualties", integer(1)),
                prop("TGDDescriptorAddCasualtiesToPawn", "Group",
                     ref(unit_tag(deployment["adapter_slot"]["name"]), "TGDTagUnitGroup")),
            ]))
    loss_launch = []
    if loss_actions:
        container = add("TGDDescriptorSimultaneous", [
            prop("TGDDescriptorSimultaneous", "SubActions", listref([
                ref(item, "TGDDescriptorAddCasualtiesToPawn") for item in loss_actions])),
            prop("TGDDescriptorSimultaneous", "NbExecutions", uint(1)),
        ])
        loss_launch.append(ref(container, "TGDDescriptorSimultaneous"))

    # Existing choice-event builders already use valid native modal classes
    # and create exactly the four catalogued event battalions.  Retarget their
    # spawn/mission tags to authored coordinates and schedule them from the
    # campaign-content root, after its two-second kernel delay.
    launch = _property(objects[290], "SubActions")
    launch_ids = [item["object_id"] for item in launch["items"]]
    if 301 not in launch_ids:
        raise ValueError("Pinned strategic kernel is absent from launch")
    kernel = _property(objects[301], "SubActions")
    kernel_ids = [item.get("object_id") for item in kernel["items"]]
    if kernel_ids[:5] != [315, 316, 317, 318, 319]:
        raise ValueError("Pinned strategic kernel layout changed")
    # The compatibility bootstrap used by the old prototype appended a block
    # of five overlapping stock-group missions here.  It must not survive in
    # an authored campaign; each authored pawn receives its own group below.
    kernel["items"] = kernel["items"][:5]
    kernel["length"] = 5
    # Authored events must have their own modal variable and dispatch graph.
    # Reusing the two Bruderkrieg launch roots silently aliases a second
    # choice on the same side to the first event's branch state.

    imports = dict(graph["imports"])
    wing_groups={w['battalion']:add('TGDVariableUnitGroup') for w in compiled.get('aviation',{}).get('wings',[])}
    runtime_paths = {"$/GFX/Pawn/" + row["unit_export"] for row in compiled["battalions"]}
    claimed_imports = {index for index, path in imports.items() if path in runtime_paths}

    def pawn_import(path):
        matching = [index for index, value in imports.items() if value == path]
        if len(matching) > 1:
            raise ValueError(f"Duplicate Pawn import: {path}")
        if matching:
            return matching[0]
        for index in (4, 5, 6, 7, 8, 9, 10):
            if index not in claimed_imports and imports.get(index, "").startswith("$/GFX/Pawn/"):
                claimed_imports.add(index)
                imports[index] = path
                return index
        index = max(imports, default=-1) + 1
        imports[index] = path
        claimed_imports.add(index)
        return index

    def runtime_spawn(effect, side, aircraft=False):
        path = "$/GFX/Pawn/" + effect["unit_export"]
        index = pawn_import(path)
        group = wing_groups[effect['battalion']] if aircraft else add("TGDVariableUnitGroup")
        marker_id = next(row["id"] for row in compiled["map"]["runtime_positions"]
                         if row["guid"] == effect["position_guid"])
        camp = 284 if side == "nato" else 283
        create = add("TGDDescriptorCreateUnitOnPosition", [
            prop("TGDDescriptorCreateUnitOnPosition", "Camp", ref(camp, "TGDVariableCamp")),
            prop("TGDDescriptorCreateUnitOnPosition", "Group", ref(group, "TGDVariableUnitGroup")),
            prop("TGDDescriptorCreateUnitOnPosition", "NbUnit", integer(1)),
            prop("TGDDescriptorCreateUnitOnPosition", "Position",
                 ref(runtime_tags[marker_id], "TGDTagPosition")),
            prop("TGDDescriptorCreateUnitOnPosition", "TypeUnit", {
                "type_id": 2863311530, "type": "trans_ref", "reference_prefix": True,
                "index": index, "value": path,
            }),
        ])
        actions = [ref(create, "TGDDescriptorCreateUnitOnPosition")]
        if aircraft and effect.get('loss_budget'):
            damage=add('TGDDescriptorAddCasualtiesToPawn',[
                prop('TGDDescriptorAddCasualtiesToPawn','Group',ref(group,'TGDVariableUnitGroup')),
                prop('TGDDescriptorAddCasualtiesToPawn','Casualties',integer(effect['loss_budget'])),
                prop('TGDDescriptorAddCasualtiesToPawn','RandomRange',integer(0)),
                prop('TGDDescriptorAddCasualtiesToPawn','TypeCasualties',integer(1))])
            actions.append(ref(damage,'TGDDescriptorAddCasualtiesToPawn'))
        if not aircraft:
            mission, mission_class = strategic_mission(group, effect["ai"], side,[effect['spawn']])
            actions.append(ref(mission, mission_class))
        sequence = add("TGDDescriptorSequential", [
            prop("TGDDescriptorSequential", "SubActions", listref(actions)),
            prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
        ])
        return sequence

    def runtime_effect(effect, side):
        if 'spawn' in effect:
            action = runtime_spawn(effect, side)
            if 'at_turn' in effect:
                action = wait_then(action, 'TGDDescriptorSequential',
                                   turn_condition(effect['at_turn'], side))
            return action, 'TGDDescriptorSequential'
        if 'score' in effect:
            class_name = 'TGDDescriptorAddScoreCamp'
            action = add(class_name, [
                prop(class_name, 'AddToScore', integer(effect['score'])),
                prop(class_name, 'Camp', ref(284 if effect['side'] == 'nato' else 283,
                                             'TGDVariableCamp')),
                prop(class_name, 'ScoreType', integer(5)),
            ])
            return action, class_name
        if 'action_points' in effect:
            class_name = 'TGDDescriptorChangePawnActionPoint'
            group = unit_tag(effect['deployment_slot']['name'])
            action = add(class_name, [
                prop(class_name, 'ActionPointNumber', floating(effect['action_points'])),
                prop(class_name, 'UnitsGroup', ref(group, 'TGDTagUnitGroup')),
            ])
            return action, class_name
        if 'casualties' in effect:
            class_name = 'TGDDescriptorAddCasualtiesToPawn'
            group = unit_tag(effect['deployment_slot']['name'])
            action = add(class_name, [
                prop(class_name, 'Casualties', integer(effect['casualties'])),
                prop(class_name, 'RandomRange', integer(effect['random_range'])),
                prop(class_name, 'TypeCasualties', integer(1)),
                prop(class_name, 'Group', ref(group, 'TGDTagUnitGroup')),
            ])
            return action, class_name
        raise ValueError('Unsupported compiled campaign event effect')

    def cinematic_presentation(slides, side, keys, start_camera=False):
        """Show a numbered series of image-backed dialogs in one native flow."""
        camp = 284 if side == 'nato' else 283
        dialogs = []
        for slide, key in zip(slides, keys):
            body = add('TGDDescriptorCutsceneTextComponent', [
                prop('TGDDescriptorCutsceneTextComponent', 'UIComponentName', string('Text1')),
                prop('TGDDescriptorCutsceneTextComponent', 'LocalizedText', loc(key)),
            ])
            title = add('TGDDescriptorCutsceneTextComponent', [
                prop('TGDDescriptorCutsceneTextComponent', 'UIComponentName', string('Text2')),
                prop('TGDDescriptorCutsceneTextComponent', 'LocalizedText', loc(authored_text_key(campaign_id, 'cinematic_title', key.hex()))),
            ]) if compiled['cinematics'].get('layout') == 'briefing' else None
            picture = add('TGDDescriptorCutsceneTextureComponent', [
                prop('TGDDescriptorCutsceneTextureComponent', 'UIComponentName', string('Texture1')),
                prop('TGDDescriptorCutsceneTextureComponent', 'TextureFile',
                     string(slide['adapter_image'])),
            ])
            cls = 'TGDDescriptorCutsceneDialog'
            dialogs.append(add(cls, [
                prop(cls, 'AfficherBoutonPause', boolean(True)),
                prop(cls, 'AfficherDevantFlou', boolean(True)),
                prop(cls, 'CanBeSkippedWithEscape', boolean(True)),
                prop(cls, 'ComponentName', string(('AGF_BriefingSlideV2' if compiled['cinematics'].get('layout_version')==2 else 'AGF_BriefingSlide') if title is not None else 'ST_Component_1Texture_1Text')),
                prop(cls, 'DureePause', floating(-1)),
                prop(cls, 'Pause', boolean(True)),
                prop(cls, 'TextComponentsToFill', listref([
                    ref(body, 'TGDDescriptorCutsceneTextComponent')] + ([ref(title, 'TGDDescriptorCutsceneTextComponent')] if title is not None else []))),
                prop(cls, 'TextureComponentsToFill', listref([
                    ref(picture, 'TGDDescriptorCutsceneTextureComponent')])),
                prop(cls, 'TokenBoutonChoix0', loc(bytes.fromhex('9ef860e5d4010000'))),
                prop(cls, 'VisibleByAlliedOfSpecifiedCamp', boolean(True)),
                prop(cls, 'VisibleByCamp', ref(camp, 'TGDVariableCamp')),
            ]))
        play = add('TGDDescriptorCutscenePlayDialogList', [
            prop('TGDDescriptorCutscenePlayDialogList', 'DialogList', listref([
                ref(dialog, 'TGDDescriptorCutsceneDialog') for dialog in dialogs])),
            prop('TGDDescriptorCutscenePlayDialogList',
                 'DelayToWaitAfterEndingLastDialogSound', floating(1)),
        ])
        actions = [ref(play, 'TGDDescriptorCutscenePlayDialogList')]
        if start_camera and compiled['cinematics'].get('start_camera'):
            cls = 'TGDDescriptorCutsceneStartCameraPath'
            camera = add(cls, [
                prop(cls, 'CameraPathName', string('camera')),
                prop(cls, 'TimeInSecond', floating(0.01)),
                prop(cls, 'StartFromCurrentCameraPosition', boolean(False)),
                prop(cls, 'AccelerationActivated', boolean(False)),
                prop(cls, 'DecelerationActivated', boolean(False)),
                prop(cls, 'VisibleByCamp', ref(camp, 'TGDVariableCamp')),
            ])
            actions.insert(0, ref(camera, cls))
        return add('TGDDescriptorEncapsuleCutscene', [
            prop('TGDDescriptorEncapsuleCutscene', 'SubActions', listref(actions)),
            prop('TGDDescriptorEncapsuleCutscene', 'BlockPlayerActions', boolean(True)),
        ])

    intro_roots = []
    if compiled.get('cinematics') is not None:
        for side, slides in compiled['cinematics']['intro'].items():
            presentation = cinematic_presentation(slides, side, [
                authored_text_key(campaign_id, 'intro', side, str(index))
                for index in range(len(slides))], start_camera=True)
            camp = 284 if side == 'nato' else 283
            local = add('TGDConditionCutSceneIsCampControllableByLocalPlayer', [
                prop('TGDConditionCutSceneIsCampControllableByLocalPlayer',
                     'Camp', ref(camp, 'TGDVariableCamp'))])
            skip = add('TGDDescriptorWaitDuration', [
                prop('TGDDescriptorWaitDuration', 'Duree', floating(0))])
            visible = add('TGDDescriptorIfThenElse', [
                prop('TGDDescriptorIfThenElse', 'Condition', ref(
                    local, 'TGDConditionCutSceneIsCampControllableByLocalPlayer')),
                prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(
                    presentation, 'TGDDescriptorEncapsuleCutscene')),
                prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(
                    skip, 'TGDDescriptorWaitDuration')),
            ])
            release = add('TGDDescriptorModifieVariableInteger', [
                prop('TGDDescriptorModifieVariableInteger', 'Variable1', ref(
                    intro_ready[side], 'TGDVariableInteger')),
                prop('TGDDescriptorModifieVariableInteger', 'Value', integer(1)),
                prop('TGDDescriptorModifieVariableInteger', 'ModificationType', integer(2)),
            ])
            sequence = add('TGDDescriptorSequential', [
                prop('TGDDescriptorSequential', 'SubActions', listref([
                    ref(visible, 'TGDDescriptorIfThenElse'),
                    ref(release, 'TGDDescriptorModifieVariableInteger')])),
                prop('TGDDescriptorSequential', 'NbExecutions', uint(1)),
            ])
            intro_roots.append((wait_then(sequence, 'TGDDescriptorSequential',
                turn_condition(1, side)), 'TGDDescriptorSequential'))

    scheduled_events = []
    for event in compiled["events"]:
        if not event["choices"]:
            effects = [runtime_effect(effect, event["side"])
                       for effect in event["effects"]]
            if not effects:
                effect_class = 'TGDDescriptorWaitDuration'
                effect_action = add(effect_class, [prop(effect_class, 'Duree', floating(0))])
            elif len(effects) == 1:
                effect_action, effect_class = effects[0]
            else:
                effect_class = 'TGDDescriptorSimultaneous'
                effect_action = add(effect_class, [
                    prop(effect_class, 'SubActions',
                         listref([ref(item, kind) for item, kind in effects])),
                    prop(effect_class, 'NbExecutions', uint(1)),
                ])
            components = []
            for ui_name, key in (("Text1", "presentation"),):
                components.append(add("TGDDescriptorCutsceneTextComponent", [
                    prop("TGDDescriptorCutsceneTextComponent", "UIComponentName", string(ui_name)),
                    prop("TGDDescriptorCutsceneTextComponent", "LocalizedText", loc(
                        authored_text_key(campaign_id, "event", event["id"], key))),
                ]))
            texture = add("TGDDescriptorCutsceneTextureComponent", [
                prop("TGDDescriptorCutsceneTextureComponent", "UIComponentName", string("Texture1")),
                prop("TGDDescriptorCutsceneTextureComponent", "TextureFile",
                     string(event["adapter_image"])),
            ]) if event['adapter_image'] is not None else None
            camp = 284 if event["side"] == "nato" else 283
            dialog = add("TGDDescriptorCutsceneDialog", [
                prop("TGDDescriptorCutsceneDialog", "AfficherBoutonPause", boolean(True)),
                prop("TGDDescriptorCutsceneDialog", "AfficherDevantFlou", boolean(True)),
                prop("TGDDescriptorCutsceneDialog", "CanBeSkippedWithEscape", boolean(True)),
                prop("TGDDescriptorCutsceneDialog", "ComponentName", string("ST_Component_1Texture_1Text")),
                prop("TGDDescriptorCutsceneDialog", "DureePause", floating(-1)),
                prop("TGDDescriptorCutsceneDialog", "Pause", boolean(True)),
                prop("TGDDescriptorCutsceneDialog", "TextComponentsToFill",
                     listref([ref(item, "TGDDescriptorCutsceneTextComponent") for item in components])),
                prop("TGDDescriptorCutsceneDialog", "TextureComponentsToFill",
                     listref([ref(texture, "TGDDescriptorCutsceneTextureComponent")] if texture is not None else [])),
                prop("TGDDescriptorCutsceneDialog", "TokenBoutonChoix0",
                     loc(bytes.fromhex("9ef860e5d4010000"))),
                prop("TGDDescriptorCutsceneDialog", "VisibleByAlliedOfSpecifiedCamp", boolean(True)),
                prop("TGDDescriptorCutsceneDialog", "VisibleByCamp", ref(camp, "TGDVariableCamp")),
            ])
            play = add("TGDDescriptorCutscenePlayDialogList", [
                prop("TGDDescriptorCutscenePlayDialogList", "DialogList",
                     listref([ref(dialog, "TGDDescriptorCutsceneDialog")])),
                prop("TGDDescriptorCutscenePlayDialogList", "DelayToWaitAfterEndingLastDialogSound",
                     floating(1)),
            ])
            presentation = add("TGDDescriptorEncapsuleCutscene", [
                prop("TGDDescriptorEncapsuleCutscene", "SubActions",
                     listref([ref(play, "TGDDescriptorCutscenePlayDialogList")])),
                prop("TGDDescriptorEncapsuleCutscene", "BlockPlayerActions", boolean(True)),
            ])
            local_sequence = add("TGDDescriptorSequential", [
                prop("TGDDescriptorSequential", "SubActions", listref([
                    ref(presentation, "TGDDescriptorEncapsuleCutscene"),
                    ref(effect_action, effect_class),
                ])),
                prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
            ])
            local = add("TGDConditionCutSceneIsCampControllableByLocalPlayer", [
                prop("TGDConditionCutSceneIsCampControllableByLocalPlayer", "Camp",
                     ref(camp, "TGDVariableCamp")),
            ])
            root = add("TGDDescriptorIfThenElse", [
                prop("TGDDescriptorIfThenElse", "Condition", ref(
                    local, "TGDConditionCutSceneIsCampControllableByLocalPlayer")),
                prop("TGDDescriptorIfThenElse", "EffetIfTrue",
                     ref(local_sequence, "TGDDescriptorSequential")),
                prop("TGDDescriptorIfThenElse", "EffetIfFalse", ref(effect_action, effect_class)),
            ])
            scheduled_events.append(schedule_event(root, event))
            continue
        graphic = event.get('layout', 'text') == 'graphic_cards'
        component_name = ('AGF_GraphicCardsV2' if compiled.get('cinematics',{}).get('layout_version')==2 else 'ST_Popup_1Texture_5Text') if graphic else 'ST_Component_1Texture_1Text'
        component_keys = [('Text1', ('presentation',))]
        if graphic:
            component_keys += [
                ('Text2', ('card', '0', 'title')), ('Text3', ('card', '0', 'text')),
                ('Text4', ('card', '1', 'title')), ('Text5', ('card', '1', 'text')),
            ]
        text_components = []
        for ui_name, key_parts in component_keys:
            text_components.append(add('TGDDescriptorCutsceneTextComponent', [
                prop('TGDDescriptorCutsceneTextComponent', 'UIComponentName', string(ui_name)),
                prop('TGDDescriptorCutsceneTextComponent', 'LocalizedText', loc(
                    authored_text_key(campaign_id, 'event', event['id'], *key_parts))),
            ]))
        texture = add('TGDDescriptorCutsceneTextureComponent', [
            prop('TGDDescriptorCutsceneTextureComponent', 'UIComponentName', string('Texture1')),
            prop('TGDDescriptorCutsceneTextureComponent', 'TextureFile', string(event['adapter_image'])),
        ])
        camp = 284 if event['side'] == 'nato' else 283
        selected = add('TGDVariableInteger', [
            prop('TGDVariableInteger', 'Value', integer(99)),
        ])
        dialog_class = 'TGDDescriptorCutsceneDialogWithMultipleChoice'
        dialog = add(dialog_class, [
            prop(dialog_class, 'AfficherBoutonPause', boolean(True)),
            prop(dialog_class, 'AfficherDevantFlou', boolean(True)),
            prop(dialog_class, 'ComponentName', string(component_name)),
            prop(dialog_class, 'DureePause', floating(-1)),
            prop(dialog_class, 'Pause', boolean(True)),
            prop(dialog_class, 'TextComponentsToFill', listref([
                ref(item, 'TGDDescriptorCutsceneTextComponent') for item in text_components])),
            prop(dialog_class, 'TextureComponentsToFill', listref([
                ref(texture, 'TGDDescriptorCutsceneTextureComponent')])),
            prop(dialog_class, 'TokenBoutonChoix0', loc(authored_text_key(
                campaign_id, 'event', event['id'], 'choice', '0'))),
            prop(dialog_class, 'TokenBoutonChoix1', loc(authored_text_key(
                campaign_id, 'event', event['id'], 'choice', '1'))),
            prop(dialog_class, 'VisibleByAlliedOfSpecifiedCamp', boolean(True)),
            prop(dialog_class, 'VisibleByCamp', ref(camp, 'TGDVariableCamp')),
            prop(dialog_class, 'SelectedButton', ref(selected, 'TGDVariableInteger')),
            prop(dialog_class, 'DefaultButtonChoice', integer(0)),
        ])
        modal_class = 'TGDDescriptorEncapsuleCutsceneDialogListWithMultipleChoice'
        modal = add(modal_class, [
            prop(modal_class, 'DialogList', listref([ref(dialog, dialog_class)])),
        ])
        operator = add('TGDOperatorIntegerCompare', [
            prop('TGDOperatorIntegerCompare', 'OperatorType', integer(3)),
            prop('TGDOperatorIntegerCompare', 'Value', integer(0)),
        ])
        condition = add('TGDConditionVariable', [
            prop('TGDConditionVariable', 'Operator', ref(operator, 'TGDOperatorIntegerCompare')),
            prop('TGDConditionVariable', 'Variable', ref(selected, 'TGDVariableInteger')),
        ])
        branch_actions = []
        for index, choice in enumerate(event["choices"]):
            effects = [runtime_effect(effect, event["side"]) for effect in choice["effects"]]
            effects.extend((runtime_spawn(wing, wing['side'], aircraft=True), 'TGDDescriptorSequential')
                           for wing in compiled.get('aviation', {}).get('wings', [])
                           if wing['available'] == {'event': event['id'], 'choice': index})
            effect_action = add("TGDDescriptorSimultaneous", [
                prop("TGDDescriptorSimultaneous", "SubActions",
                     listref([ref(item, kind) for item, kind in effects])),
                prop("TGDDescriptorSimultaneous", "NbExecutions", uint(1)),
            ])
            branch_actions.append(effect_action)
        selection = add('TGDDescriptorIfThenElse', [
            prop('TGDDescriptorIfThenElse', 'Condition', ref(condition, 'TGDConditionVariable')),
            prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(branch_actions[0], 'TGDDescriptorSimultaneous')),
            prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(branch_actions[1], 'TGDDescriptorSimultaneous')),
        ])
        local_sequence = add('TGDDescriptorSequential', [
            prop('TGDDescriptorSequential', 'SubActions', listref([
                ref(modal, modal_class), ref(selection, 'TGDDescriptorIfThenElse')])),
            prop('TGDDescriptorSequential', 'NbExecutions', uint(1)),
        ])
        local = add('TGDConditionCutSceneIsCampControllableByLocalPlayer', [
            prop('TGDConditionCutSceneIsCampControllableByLocalPlayer', 'Camp',
                 ref(camp, 'TGDVariableCamp')),
        ])
        root = add('TGDDescriptorIfThenElse', [
            prop('TGDDescriptorIfThenElse', 'Condition', ref(
                local, 'TGDConditionCutSceneIsCampControllableByLocalPlayer')),
            prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(local_sequence, 'TGDDescriptorSequential')),
            prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(branch_actions[0], 'TGDDescriptorSimultaneous')),
        ])
        scheduled_events.append(schedule_event(root, event))

    # Scripted, automatic reinforcements use the same native create+mission
    # descriptors as event choices, but have no presentation.
    reinforcement_roots = []
    for reinforcement in compiled["reinforcements"]:
        path = "$/GFX/Pawn/" + reinforcement["unit_export"]
        index = pawn_import(path)
        group = add("TGDVariableUnitGroup")
        marker = runtime_tags[reinforcement["id"]]
        camp = 284 if reinforcement["side"] == "nato" else 283
        create = add("TGDDescriptorCreateUnitOnPosition", [
            prop("TGDDescriptorCreateUnitOnPosition", "Camp", ref(camp, "TGDVariableCamp")),
            prop("TGDDescriptorCreateUnitOnPosition", "Group", ref(group, "TGDVariableUnitGroup")),
            prop("TGDDescriptorCreateUnitOnPosition", "NbUnit", integer(1)),
            prop("TGDDescriptorCreateUnitOnPosition", "Position", ref(marker, "TGDTagPosition")),
            prop("TGDDescriptorCreateUnitOnPosition", "TypeUnit", {
                "type_id": 2863311530, "type": "trans_ref", "reference_prefix": True,
                "index": index, "value": path,
            }),
        ])
        mission, mission_class = strategic_mission(group, reinforcement["ai"], reinforcement['side'],[reinforcement['battalion']])
        effect = add("TGDDescriptorSequential", [
            prop("TGDDescriptorSequential", "SubActions", listref([
                ref(create, "TGDDescriptorCreateUnitOnPosition"), ref(mission, mission_class),
            ])),
            prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
        ])
        condition = turn_condition(reinforcement["turn"], reinforcement["side"])
        reinforcement_roots.append((wait_then(effect, "TGDDescriptorSequential", condition),
                                    "TGDDescriptorSequential"))

    content_items = [(384, "TGDDescriptorGereObjectif"), (385, "TGDDescriptorGereObjectif")]
    content_items += [(item, "TGDDescriptorGereObjectifWithVariableOwner") for item in objective_ids]
    content_items += mission_roots + frozen_sequences + intro_roots + scheduled_events + reinforcement_roots
    if deadline_rule:
        compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','OperatorType',integer(2)),
            prop('TGDOperatorIntegerCompare','Value',integer(deadline_rule['before_turn']))])
        before=add('TGDConditionVariable',[prop('TGDConditionVariable','Variable',ref(381,'TGDVariableInteger')),
            prop('TGDConditionVariable','Operator',ref(compare,'TGDOperatorIntegerCompare'))])
        ownership=flag_owner_condition(deadline_rule['flag'],deadline_rule['owner'])
        captured=add('TGDConditionAnd',[prop('TGDConditionAnd','SousConditions',listref([
            ref(before,'TGDConditionVariable'),ref(ownership,'TGDConditionPositionInInfluenceMap')]))])
        latch=add('TGDDescriptorModifieVariableInteger',[
            prop('TGDDescriptorModifieVariableInteger','Variable1',ref(deadline_variable,'TGDVariableInteger')),
            prop('TGDDescriptorModifieVariableInteger','Value',integer(1)),
            prop('TGDDescriptorModifieVariableInteger','ModificationType',integer(0))])
        capture_flow=wait_then(latch,'TGDDescriptorModifieVariableInteger',captured)
        end_compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','OperatorType',integer(5)),
            prop('TGDOperatorIntegerCompare','Value',integer(deadline_rule['before_turn']))])
        expired=add('TGDConditionVariable',[prop('TGDConditionVariable','Variable',ref(381,'TGDVariableInteger')),
            prop('TGDConditionVariable','Operator',ref(end_compare,'TGDOperatorIntegerCompare'))])
        stop=add('TGDDescriptorWaitCondition',[prop('TGDDescriptorWaitCondition','Condition',ref(expired,'TGDConditionVariable'))])
        monitor=add('TGDDescriptorCompetition',[prop('TGDDescriptorCompetition','SubActions',listref([
            ref(capture_flow,'TGDDescriptorSequential'),ref(stop,'TGDDescriptorWaitCondition')]))])
        content_items.append((monitor,'TGDDescriptorCompetition'))
    aircraft_startup = []
    for wing in compiled.get('aviation', {}).get('wings', []):
        if 'turn' in wing['available']:
            action = runtime_spawn(wing, wing['side'], aircraft=True)
            if wing['available']['turn'] == 1:
                aircraft_startup.append(ref(action, 'TGDDescriptorSequential'))
                continue
            condition = turn_condition(wing['available']['turn'], wing['side'])
            content_items.append((wait_then(action, 'TGDDescriptorSequential', condition),
                                  'TGDDescriptorSequential'))
    for wing in compiled.get('aviation',{}).get('wings',[]):
        if 'withdraw_turn' in wing:
            if compiled['aviation'].get('withdrawal_version') == 2:
                detector=next(oid for oid,path in graph['exports'].items()
                              if path=='$/GDScript/GdItems/CircularZones/AGFW_AirWingTracking')
                tag_constraint=add('TGDContrainteOnUnitTag',[
                    prop('TGDContrainteOnUnitTag','Tag',string(wing['tracking_tag']))])
                camp_constraint=add('TGDContrainteOnUnitTeam',[
                    prop('TGDContrainteOnUnitTeam','Camp',ref(284 if wing['side']=='nato' else 283,'TGDVariableCamp'))])
                constraints=add('TGDContrainteOnUnitAllContrainte',[
                    prop('TGDContrainteOnUnitAllContrainte','ContrainteList',listref([
                        ref(tag_constraint,'TGDContrainteOnUnitTag'),ref(camp_constraint,'TGDContrainteOnUnitTeam')]))])
                current=add('TGDConditionDetectUnitDansDetecteur',[
                    prop('TGDConditionDetectUnitDansDetecteur','Detecteur',ref(detector,'TGDTagDetecteur')),
                    prop('TGDConditionDetectUnitDansDetecteur','Contrainte',ref(constraints,'TGDContrainteOnUnitAllContrainte'))])
                retries=[]
                for turn in range(wing['withdraw_turn'],compiled['campaign']['turns']+1):
                    fresh=add('TGDVariableUnitGroup')
                    collect=add('TGDDescriptorAddDetectedUnitsToUnitGroup',[
                        prop('TGDDescriptorAddDetectedUnitsToUnitGroup','Detector',ref(current,'TGDConditionDetectUnitDansDetecteur')),
                        prop('TGDDescriptorAddDetectedUnitsToUnitGroup','Group',ref(fresh,'TGDVariableUnitGroup'))])
                    remove=add('TGDDescriptorKillAllUnit',[prop('TGDDescriptorKillAllUnit','GroupList',listref([
                        ref(fresh,'TGDVariableUnitGroup')]))])
                    action=add('TGDDescriptorSequential',[
                        prop('TGDDescriptorSequential','SubActions',listref([
                            ref(collect,'TGDDescriptorAddDetectedUnitsToUnitGroup'),ref(remove,'TGDDescriptorKillAllUnit')])),
                        prop('TGDDescriptorSequential','NbExecutions',uint(1))])
                    retries.append(ref(wait_then(action,'TGDDescriptorSequential',turn_condition(turn,wing['side'])),
                                       'TGDDescriptorSequential'))
                root=add('TGDDescriptorSimultaneous',[
                    prop('TGDDescriptorSimultaneous','SubActions',listref(retries)),
                    prop('TGDDescriptorSimultaneous','NbExecutions',uint(1))])
                content_items.append((root,'TGDDescriptorSimultaneous'))
                continue
            compare=add('TGDOperatorIntegerCompare',[prop('TGDOperatorIntegerCompare','OperatorType',integer(5)),
                prop('TGDOperatorIntegerCompare','Value',integer(wing['withdraw_turn']))])
            condition=add('TGDConditionVariable',[prop('TGDConditionVariable','Variable',ref(381,'TGDVariableInteger')),
                prop('TGDConditionVariable','Operator',ref(compare,'TGDOperatorIntegerCompare'))])
            remove=add('TGDDescriptorKillAllUnit',[prop('TGDDescriptorKillAllUnit','GroupList',listref([
                ref(wing_groups[wing['battalion']],'TGDVariableUnitGroup')]))])
            content_items.append((wait_then(remove,'TGDDescriptorKillAllUnit',condition),'TGDDescriptorSequential'))
    production = compiled.get("production", {"divisions": [], "groups": []})
    if production["groups"]:
        division_ids = {}
        actions = []
        actions_by_side = {"nato": [], "pact": []}
        for division in production["divisions"]:
            division_ids[division["id"]] = add("TGDStrategicReinforcementGroup", [
                prop("TGDStrategicReinforcementGroup", "DisplayName",
                     loc(authored_text_key(campaign_id, "division", division["id"], "name"))),
                prop("TGDStrategicReinforcementGroup", "ShortDisplayName",
                     loc(authored_text_key(campaign_id, "division", division["id"], "short_name"))),
                prop("TGDStrategicReinforcementGroup", "SpawnPositionsSortedByPriority",
                     listref([ref(runtime_tags[point], "TGDTagPosition") for point in division["deployment_points"]])),
            ])
        for side, camp in (("nato", 284), ("pact", 283)):
            groups = [division_ids[row["id"]] for row in production["divisions"] if row["side"] == side]
            if groups:
                class_name = "TGDDescriptorStrategicSetPossibleSpawnPositionsForProduction"
                action = (add(class_name, [
                    prop(class_name, "Camp", ref(camp, "TGDVariableCamp")),
                    prop(class_name, "ReinforcementGroups", listref([
                        ref(item, "TGDStrategicReinforcementGroup") for item in groups])),
                ]), class_name)
                actions.append(action)
                actions_by_side[side].append(action)
        for group in production["groups"]:
            turn = add("TGDVariableInteger", [prop("TGDVariableInteger", "Value", integer(group["turn"]))])
            pawns = []
            for export in group["unit_exports"]:
                path = "$/GFX/Pawn/" + export
                pawns.append({"type_id": 2863311530, "type": "trans_ref", "reference_prefix": True,
                              "index": pawn_import(path), "value": path})
            class_name = "TGDDescriptorStrategicAddPossibleProduction"
            action = (add(class_name, [
                prop(class_name, "Pawns", listref(pawns)),
                prop(class_name, "DisplayName", loc(authored_text_key(campaign_id, "regiment", group["id"]))),
                prop(class_name, "Camp", ref(284 if group["side"] == "nato" else 283, "TGDVariableCamp")),
                prop(class_name, "ReinforcementGroup", ref(division_ids[group["division"]], "TGDStrategicReinforcementGroup")),
                prop(class_name, "UnlockAtTurnVariable", ref(turn, "TGDVariableInteger")),
            ]), class_name)
            actions.append(action)
            human_action=action
            if deadline_rule and group['division']==deadline_rule['division']:
                idle=add('TGDDescriptorWaitDuration',[prop('TGDDescriptorWaitDuration','Duree',floating(0))])
                gate=add('TGDDescriptorIfThenElse',[
                    prop('TGDDescriptorIfThenElse','Condition',ref(deadline_status(False),'TGDConditionVariable')),
                    prop('TGDDescriptorIfThenElse','EffetIfTrue',ref(action[0],action[1])),
                    prop('TGDDescriptorIfThenElse','EffetIfFalse',ref(idle,'TGDDescriptorWaitDuration'))])
                delayed=wait_then(gate,'TGDDescriptorIfThenElse',turn_condition(deadline_rule['before_turn'],group['side']))
                human_action=(delayed,'TGDDescriptorSequential')
            actions_by_side[group["side"]].append(human_action)
        if production_ai_version == 1:
            production_root = add("TGDDescriptorSequential", [
                prop("TGDDescriptorSequential", "SubActions", listref([ref(item, kind) for item, kind in actions])),
                prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
            ])
            content_items.append((production_root, "TGDDescriptorSequential"))
        else:
            # Production's native queue exposes a choice to the human side, but
            # does not expose a unit-group handle for scripted strategic AI.
            # Keep that queue for humans.  An AI-controlled side receives the
            # same dated battalions via a mutually exclusive create+mission
            # branch, so its reserves do not remain idle at the spawn point.
            divisions = {row["id"]: row for row in production["divisions"]}

            def ai_production(group):
                points = divisions[group["division"]]["deployment_points"]
                member_groups = ([add("TGDVariableUnitGroup") for _ in group["unit_exports"]]
                                 if group.get('member_ai') else None)
                unit_group = (add("TGDVariableUnitGroup") if member_groups is None else None)

                def spawn_at(point_id):
                    creates = []
                    for member_index, export in enumerate(group["unit_exports"]):
                        path = "$/GFX/Pawn/" + export
                        class_name = "TGDDescriptorCreateUnitOnPosition"
                        creates.append(add(class_name, [
                            prop(class_name, "Camp", ref(284 if group["side"] == "nato" else 283,
                                                         "TGDVariableCamp")),
                            prop(class_name, "Group", ref(
                                unit_group if member_groups is None else member_groups[member_index],
                                "TGDVariableUnitGroup")),
                            prop(class_name, "NbUnit", integer(1)),
                            prop(class_name, "Position", ref(runtime_tags[point_id], "TGDTagPosition")),
                            prop(class_name, "TypeUnit", {
                                "type_id": 2863311530, "type": "trans_ref", "reference_prefix": True,
                                "index": pawn_import(path), "value": path,
                            }),
                        ]))
                    sequence = add("TGDDescriptorSequential", [
                        prop("TGDDescriptorSequential", "SubActions", listref([
                            ref(item, "TGDDescriptorCreateUnitOnPosition") for item in creates])),
                        prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
                    ])
                    return sequence, "TGDDescriptorSequential"

                spawn, spawn_class = spawn_at(points[-1])
                for point_id in reversed(points[:-1]):
                    preferred, preferred_class = spawn_at(point_id)
                    condition = position_owner_condition(runtime_tags[point_id], group["side"])
                    class_name = "TGDDescriptorIfThenElse"
                    spawn = add(class_name, [
                        prop(class_name, "Condition", ref(condition, "TGDConditionPositionInInfluenceMap")),
                        prop(class_name, "EffetIfTrue", ref(preferred, preferred_class)),
                        prop(class_name, "EffetIfFalse", ref(spawn, spawn_class)),
                    ])
                    spawn_class = class_name
                if member_groups is None:
                    mission, mission_class = strategic_mission(unit_group, group["ai"], group['side'],group['battalions'])
                else:
                    missions = [strategic_mission(member_group,
                        group['member_ai'].get(member, group['ai']), group['side'],[member])
                        for member, member_group in zip(group['battalions'], member_groups)]
                    mission_class = 'TGDDescriptorSimultaneous'
                    mission = add(mission_class, [
                        prop(mission_class, 'SubActions', listref([
                            ref(item, kind) for item, kind in missions])),
                        prop(mission_class, 'NbExecutions', uint(1)),
                    ])
                sequence = add("TGDDescriptorSequential", [
                    prop("TGDDescriptorSequential", "SubActions", listref([
                        ref(spawn, spawn_class), ref(mission, mission_class)])),
                    prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
                ])
                if group.get('required_flag'):
                    wait = add('TGDDescriptorWaitCondition', [
                        prop('TGDDescriptorWaitCondition', 'Condition', ref(
                            flag_owner_condition(group['required_flag'], group['side']),
                            'TGDConditionPositionInInfluenceMap'))])
                    steps = _property(objects[sequence], 'SubActions')
                    steps['items'].insert(0, ref(wait, 'TGDDescriptorWaitCondition'))
                    steps['length'] = len(steps['items'])
                if deadline_rule and group['division']==deadline_rule['division']:
                    wait=add('TGDDescriptorWaitCondition',[prop('TGDDescriptorWaitCondition','Condition',ref(deadline_status(False),'TGDConditionVariable'))])
                    steps=_property(objects[sequence],'SubActions')
                    steps['items'].insert(0,ref(wait,'TGDDescriptorWaitCondition'));steps['length']=len(steps['items'])
                return wait_then(sequence, "TGDDescriptorSequential",
                                 turn_condition(group["turn"], group["side"]))

            side_branches = []
            for side, camp in (("nato", 284), ("pact", 283)):
                side_groups = [row for row in production["groups"] if row["side"] == side]
                if not side_groups:
                    continue
                human = add("TGDDescriptorSequential", [
                    prop("TGDDescriptorSequential", "SubActions", listref([
                        ref(item, kind) for item, kind in actions_by_side[side]])),
                    prop("TGDDescriptorSequential", "NbExecutions", uint(1)),
                ])
                ai = add("TGDDescriptorSimultaneous", [
                    prop("TGDDescriptorSimultaneous", "SubActions", listref([
                        ref(ai_production(group), "TGDDescriptorSequential") for group in side_groups])),
                    prop("TGDDescriptorSimultaneous", "NbExecutions", uint(1)),
                ])
                local = add("TGDConditionCutSceneIsCampControllableByLocalPlayer", [
                    prop("TGDConditionCutSceneIsCampControllableByLocalPlayer", "Camp",
                         ref(camp, "TGDVariableCamp")),
                ])
                class_name = "TGDDescriptorIfThenElse"
                side_branches.append(add(class_name, [
                    prop(class_name, "Condition",
                         ref(local, "TGDConditionCutSceneIsCampControllableByLocalPlayer")),
                    prop(class_name, "EffetIfTrue", ref(human, "TGDDescriptorSequential")),
                    prop(class_name, "EffetIfFalse", ref(ai, "TGDDescriptorSimultaneous")),
                ]))
            production_root = add("TGDDescriptorSimultaneous", [
                prop("TGDDescriptorSimultaneous", "SubActions", listref([
                    ref(item, "TGDDescriptorIfThenElse") for item in side_branches])),
                prop("TGDDescriptorSimultaneous", "NbExecutions", uint(1)),
            ])
            content_items.append((production_root, "TGDDescriptorSimultaneous"))

    if compiled.get('cinematics') is not None:
        ending = compiled['cinematics']['endings']

        def ending_slide(side, axis, variant):
            slide = ending[side][axis][variant]
            key = authored_text_key(campaign_id, 'ending', side, axis, variant)
            return cinematic_presentation([slide], side, [key])

        def owner_chain(flag_ids, side):
            conditions = [flag_owner_condition(flag_id, side) for flag_id in flag_ids]
            if len(conditions) == 1:
                return conditions[0], 'TGDConditionPositionInInfluenceMap'
            return add('TGDConditionAnd', [
                prop('TGDConditionAnd', 'SousConditions', listref([
                    ref(item, 'TGDConditionPositionInInfluenceMap')
                    for item in conditions]))]), 'TGDConditionAnd'

        def choose(condition, condition_class, yes, yes_class, no, no_class):
            return add('TGDDescriptorIfThenElse', [
                prop('TGDDescriptorIfThenElse', 'Condition', ref(condition, condition_class)),
                prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(yes, yes_class)),
                prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(no, no_class)),
            ])

        def side_ending(side, outcome):
            result = ending_slide(side, 'result', outcome)
            taken = ending_slide(side, 'sevastopol', 'taken')
            surrounded = ending_slide(side, 'sevastopol', 'surrounded')
            held = ending_slide(side, 'sevastopol', 'held')
            corridor, corridor_class = owner_chain(compiled['cinematics'].get('encirclement_flags', (
                'kacha_beach', 'kacha_crossroads', 'orlovka', 'belbek',
                'inkerman', 'balaklava')), 'nato')
            circle = choose(corridor, corridor_class, surrounded,
                            'TGDDescriptorEncapsuleCutscene', held,
                            'TGDDescriptorEncapsuleCutscene')
            city, city_class = owner_chain(('sevastopol',), 'nato')
            city_status = choose(city, city_class, taken,
                                 'TGDDescriptorEncapsuleCutscene', circle,
                                 'TGDDescriptorIfThenElse')

            lost = ending_slide(side, 'invasion', 'lost')
            beachhead = ending_slide(side, 'invasion', 'beachhead')
            breakthrough = ending_slide(side, 'invasion', 'breakthrough')
            both, both_class = owner_chain(('kacha_beach', 'simferopol'), 'nato')
            landing_held = choose(both, both_class, breakthrough,
                                  'TGDDescriptorEncapsuleCutscene', beachhead,
                                  'TGDDescriptorEncapsuleCutscene')
            lost_condition, lost_class = owner_chain(('kacha_beach',), 'pact')
            landing_status = choose(lost_condition, lost_class, lost,
                                    'TGDDescriptorEncapsuleCutscene', landing_held,
                                    'TGDDescriptorIfThenElse')
            sequence = add('TGDDescriptorSequential', [
                prop('TGDDescriptorSequential', 'SubActions', listref([
                    ref(result, 'TGDDescriptorEncapsuleCutscene'),
                    ref(city_status, 'TGDDescriptorIfThenElse'),
                    ref(landing_status, 'TGDDescriptorIfThenElse')])),
                prop('TGDDescriptorSequential', 'NbExecutions', uint(1)),
            ])
            camp = 284 if side == 'nato' else 283
            local = add('TGDConditionCutSceneIsCampControllableByLocalPlayer', [
                prop('TGDConditionCutSceneIsCampControllableByLocalPlayer',
                     'Camp', ref(camp, 'TGDVariableCamp'))])
            skip = add('TGDDescriptorWaitDuration', [
                prop('TGDDescriptorWaitDuration', 'Duree', floating(0))])
            return choose(local, 'TGDConditionCutSceneIsCampControllableByLocalPlayer',
                          sequence, 'TGDDescriptorSequential', skip,
                          'TGDDescriptorWaitDuration')

        # The pinned generic dispatcher reads the current NATO victory type:
        # 3 is a draw; 4–6 are NATO victories; lower types are NATO defeats.
        for sequence_id, nato_result, pact_result in (
                (588, 'stagnation', 'stagnation'),
                (690, 'victory', 'defeat'),
                (691, 'defeat', 'victory')):
            actions = _property(objects[sequence_id], 'SubActions')
            if len(actions['items']) != 1:
                raise ValueError('Pinned end-game dispatch is not isolated')
            actions['items'] = [
                ref(side_ending('nato', nato_result), 'TGDDescriptorIfThenElse'),
                ref(side_ending('pact', pact_result), 'TGDDescriptorIfThenElse'),
                actions['items'][0],
            ]
            actions['length'] = 3

    if 'victory' in compiled['campaign']:
        policy = compiled['campaign']['victory']
        def capture_end(winner):
            cls = 'TGDDescriptorTriggerEndGame'
            end = add(cls, [prop(cls, 'VictoryReason', integer(6)),
                prop(cls, 'VictoryType', integer(6)),
                prop(cls, 'WinningAlliance', integer(1 if winner == 'nato' else 0))])
            actions = []
            if compiled.get('cinematics'):
                actions = [ref(side_ending('nato', 'victory' if winner == 'nato' else 'defeat'), 'TGDDescriptorIfThenElse'),
                           ref(side_ending('pact', 'victory' if winner == 'pact' else 'defeat'), 'TGDDescriptorIfThenElse')]
            actions.append(ref(end, cls))
            return add('TGDDescriptorSequential', [
                prop('TGDDescriptorSequential', 'SubActions', listref(actions)),
                prop('TGDDescriptorSequential', 'NbExecutions', uint(1))])
        nato_end, pact_end = capture_end('nato'), capture_end('pact')
        nato_condition = flag_owner_condition(policy['nato_capture'], 'nato')
        pact_condition = flag_owner_condition(policy['pact_capture'], 'pact')
        _property(objects[384], 'Condition').update(ref(nato_condition, 'TGDConditionPositionInInfluenceMap'))
        _property(objects[385], 'Condition').update(ref(pact_condition, 'TGDConditionPositionInInfluenceMap'))
        _property(objects[384], 'ActionsReussi').update(ref(nato_end, 'TGDDescriptorSequential'))
        failure = add('TGDConditionOr', [prop('TGDConditionOr', 'SousConditions', listref([
            ref(pact_condition, 'TGDConditionPositionInInfluenceMap'), ref(409, 'TGDConditionVariable')]))])
        _property(objects[384], 'ConditionEchec').update(ref(failure, 'TGDConditionOr'))
        dispatcher = add('TGDDescriptorIfThenElse', [
            prop('TGDDescriptorIfThenElse', 'Condition', ref(pact_condition, 'TGDConditionPositionInInfluenceMap')),
            prop('TGDDescriptorIfThenElse', 'EffetIfTrue', ref(pact_end, 'TGDDescriptorSequential')),
            prop('TGDDescriptorIfThenElse', 'EffetIfFalse', ref(448, 'TGDDescriptorSequential'))])
        _property(objects[402], 'SubActions').update(items=[ref(dispatcher, 'TGDDescriptorIfThenElse')], length=1)
        no_op = add('TGDDescriptorWaitDuration', [prop('TGDDescriptorWaitDuration', 'Duree', floating(0))])
        _property(objects[385], 'ActionsReussi').update(ref(no_op, 'TGDDescriptorWaitDuration'))
        for objective in (384, 385):
            _property(objects[objective], 'BonusScoreMission')['value'] = 0
            _property(objects[objective], 'ObjectiveEtiquetteText')['value_hex'] = authored_text_key(campaign_id, 'frozen', 'empty').hex()
        # If neither decisive capture occurred by the time limit, both sides
        # receive a stalemate. Score ratios cannot silently override it.
        objects[586]['properties'] = [prop('TGDVariableInteger', 'Value', integer(
            {'draw':3,'nato':6,'pact':0}[policy['time_limit']]))]
        _property(objects[448], 'SubActions').update(items=[ref(514, 'TGDDescriptorIfThenElse')], length=1)
        _property(objects[688], 'VictoryReason')['value'] = 6
        _property(objects[688], 'VictoryType')['value'] = 3
        if policy['time_limit'] != 'draw':
            # Stock deadlines use Tour > TourMax. The carrier withdrawal
            # requires exactly turns 15--19: twenty hours, then turn 20 closes
            # the operation before another player turn can extend the window.
            _property(objects[454],'OperatorType')['value']=0
            end = objects[920 if policy['time_limit']=='nato' else 924]
            _property(end,'VictoryReason')['value']=6
            _property(end,'VictoryType')['value']=6
            _property(end,'WinningAlliance')['value']=1 if policy['time_limit']=='nato' else 0

    content = _property(objects[353], "SubActions")
    content["items"] = [ref(item, class_name) for item, class_name in content_items]
    content["length"] = len(content["items"])

    # The launch contains only authored group setup, the one proven AP clear
    # (when configured), and the shared strategic kernel.  No stock aircraft,
    # intro, casualty experiment or event root remains reachable here.
    aircraft_launch = []
    if aircraft_startup:
        container = add('TGDDescriptorSimultaneous', [
            prop('TGDDescriptorSimultaneous', 'SubActions', listref(aircraft_startup)),
            prop('TGDDescriptorSimultaneous', 'NbExecutions', uint(1)),
        ])
        aircraft_launch.append(ref(container, 'TGDDescriptorSimultaneous'))
    launch["items"] = [ref(291, "TGDDescriptorSequential"), *aircraft_launch, *frozen_launch, *loss_launch,
                       ref(301, "TGDDescriptorSimultaneous")]
    launch["length"] = len(launch["items"])

    base = {"classes": graph["classes"], "properties": graph["properties"],
            "objects": objects[:original_count]}
    string_doc, _ = decode(rebuild_sections(doc, {"STRG": encode_strings(graph["strings"])}))
    import_doc, _ = decode(_rebuild_imports(string_doc, graph, imports))
    result = append_graph_objects(import_doc, base, objects[original_count:], (), ())
    if dynamic_tags:
        tag_document, tag_graph = decode(result)
        result = _rebuild_imports(tag_document, tag_graph, graph['exports'], 'EXPR')
        tag_document, tag_graph = decode(result)
        top = [obj['id'] for obj in tag_graph['objects'] if obj['is_top_object']] + dynamic_tags
        result = rebuild_sections(tag_document, {'TOPO': struct.pack('<' + 'I' * len(top), *top)})
    _, check = decode(result)
    reachable = set()
    pending = [282]
    while pending:
        item = pending.pop()
        if item in reachable:
            continue
        reachable.add(item)
        for property_row in check["objects"][item]["properties"]:
            value = property_row["value"]
            if "object_id" in value:
                pending.append(value["object_id"])
            elif value.get("type") == "list":
                pending.extend(x["object_id"] for x in value["items"] if "object_id" in x)
    legacy_content = {386, 387, 388, 389, 390, 391}
    if reachable & legacy_content:
        raise ValueError("Authored script retains reachable Bruderkrieg content")
    semantic = authored_script_contract(result, compiled)
    return result, {
        "reachable_objects": len(reachable), "legacy_content_reachable": 0,
        "initial_groups": len(collectors), "ai_orders": len(mission_roots),
        "flags": len(objective_ids), "events": len(scheduled_events),
        "reinforcements": len(reinforcement_roots),
        "frozen_groups": len(frozen_sequences), "old_aircraft_spawns": 0,
        "old_presentations": 0, "old_objectives": 0,
        "semantic_contract": semantic,
    }


def build_authored_definition(compiled, localisation_root, source=DEFAULT_DEFINITION,
                              config_path=DEFAULT_CONFIG):
    """Build a renamed Definition archive with only authored campaign content."""
    localisation_root = Path(localisation_root).resolve()
    prototype, prototype_report = build_current_definition(
        source, config_path, _dictionary_keys(localisation_root))
    _, entries, _ = read_directory(prototype)
    payloads = _payloads(prototype)
    name = "NDF/Scenarios/GDScript/CampagneStrat_RedLine1989.ndfbin"
    if name not in payloads:
        raise ValueError("Prototype Definition lacks renamed GDScript")
    script, script_report = compile_authored_script(payloads[name], compiled)
    from .campaign_menu import patch_map_configuration
    replacements = {name: script}
    for key, data in payloads.items():
        if '/MapConfiguration/' in key and key.endswith('ndfbin'):
            replacements[key] = patch_map_configuration(data, compiled)
    result = clone_v3(prototype, replacements, {})
    out_header, out_entries, _ = read_directory(result)
    if out_header.version != 3 or {entry.path for entry in out_entries} != {
            entry.path for entry in entries}:
        raise ValueError("Authored Definition archive contract changed")
    from .campaign_identity import isolate_definition_identity
    result = isolate_definition_identity(result, compiled)
    return result, {"prototype": prototype_report, "script": script_report}


def compile_authored_definition(prototype, compiled):
    """Replace only the content graph in an already isolated Definition."""
    prototype = bytes(prototype)
    _, entries, _ = read_directory(prototype)
    payloads = _payloads(prototype)
    name = f"NDF/Scenarios/GDScript/{SCENARIO}.ndfbin"
    if name not in payloads:
        raise ValueError("Isolated Definition lacks its GDScript payload")
    script, report = compile_authored_script(payloads[name], compiled)
    from .authored_compaction import release_script
    script, compaction = release_script(script)
    report = {**report, 'compaction': compaction}
    from .campaign_menu import patch_map_configuration
    replacements = {name: script}
    for key, data in payloads.items():
        if '/MapConfiguration/' in key and key.endswith('ndfbin'):
            replacements[key] = patch_map_configuration(data, compiled)
    result = clone_v3(prototype, replacements, {})
    _, after, _ = read_directory(result)
    if {entry.path for entry in after} != {entry.path for entry in entries}:
        raise ValueError("Authored Definition resource set changed")
    return result, report


def pawn_state_contract(raw, compiled):
    """Read back AP/fatigue values for every initial authored descriptor."""
    _, graph = decode(raw)
    result = {}
    for row in compiled["deployments"]:
        path = "$/GFX/Pawn/" + row["unit_export"]
        found = [item for item, value in graph["exports"].items() if value == path]
        if len(found) != 1:
            raise ValueError(f"Missing authored Pawn export: {path}")
        pawn = graph["objects"][found[0]]
        modules = [graph["objects"][item["object_id"]]
                   for item in _property(pawn, "ModulesDescriptors")["items"]
                   if "object_id" in item]
        ap, = [item for item in modules if item["class"] == "TActionPointsModuleDescriptor"]
        fatigue, = [item for item in modules
                    if item["class"] == "TStrategicFatigueModuleDescriptor"]
        initial_fatigue = next((p["value"]["value"] for p in fatigue["properties"]
                                if p["property_name"] == "InitialFatigue"), 0)
        actual = {
            "fatigue": initial_fatigue,
            "initial_action_points": _property(ap, "InitialActionPoint")["value"],
            "recovery_action_points": _property(ap, "ActionPointRecoveryPerTurn")["value"],
        }
        if (actual["fatigue"] != row["fatigue"]
                or actual["initial_action_points"] != (0 if row['frozen_turns'] and
                    2 <= compiled['adapter'].get('frozen_lifecycle_version', 1) < 4 else row["action_points"])
                or actual["recovery_action_points"] != row["action_points"]):
            raise ValueError(f"Authored Pawn state mismatch: {row['id']}")
        result[row["id"]] = actual
    return result


def _dictionary_language(path):
    languages = ("DEV", "FR", "GER", "POL", "RU", "SC", "SPA", "US")
    for language in languages:
        if path.stem.endswith("-" + language) or language in path.parts:
            return language
    raise ValueError(f"Cannot infer dictionary language: {path}")


def _unique_localized_names(names):
    """A division/regiment may own many battalions but only one name token."""
    unique = {}
    for token, original, localized in names:
        prior = unique.get(token)
        if prior is not None and prior != (original, localized):
            raise ValueError('Shared formation name token has conflicting authored text')
        unique[token] = (original, localized)
    return unique


def patch_authored_localisation(root, compiled):
    """Publish authored UI strings and remove reachable-content wording from Bruderkrieg."""
    root = Path(root).resolve()
    from .localisation import field as localized_field
    languages = ("DEV", "FR", "GER", "POL", "RU", "SC", "SPA", "US")
    old_event_keys = {row[0] for row in EVENT_TEXT.values()}
    authored_keys = set(authored_text(compiled, "ru"))
    reports = {"runtime": 0, "maps": 0, "labels": 0}

    runtime_targets = []
    for path in root.rglob("*.dic"):
        normalized = path.as_posix()
        if f"/{SCENARIO}/" in normalized and path.stem.rsplit("-", 1)[0] in {
                "TROPHIES", "Dialog", "Localization"}:
            runtime_targets.append(path)
    for path in runtime_targets:
        language = _dictionary_language(path)
        values = _trad_data(path.read_bytes())
        for key in old_event_keys:
            values.pop(key, None)
        localized = authored_text(compiled, language)
        if set(values) & set(localized):
            raise ValueError(f"Authored runtime localisation collision: {path}")
        path.write_bytes(_pack_trad({**values, **localized}))
        reports["runtime"] += 1

    map_targets = [path for path in root.rglob("MAPS*.dic")
                   if "/Core/" in path.as_posix()]
    title_keys = set()
    for path in map_targets:
        if _dictionary_language(path) == "US":
            title_keys.update(key for key, value in _trad_data(path.read_bytes()).items()
                              if value == "Red Line 1989")
    if not title_keys:
        raise ValueError("Cannot identify isolated campaign-title keys")
    for path in runtime_targets:
        language = _dictionary_language(path)
        values = _trad_data(path.read_bytes())
        for key in values:
            if key.startswith(b'RDLN'):
                field = 'title' if key in title_keys else 'summary'
                values[key] = localized_field(compiled,compiled['campaign'][field],language)
        path.write_bytes(_pack_trad(values))
    for path in map_targets:
        language = _dictionary_language(path)
        values = _trad_data(path.read_bytes())
        localized = authored_text(compiled, language)
        title = localized_field(compiled,compiled['campaign']['title'],language)
        summary = localized_field(compiled,compiled['campaign']['summary'],language)
        for key in list(values):
            if key in old_event_keys:
                del values[key]
            elif key.startswith(b"RDLN"):
                values[key] = title if key in title_keys else summary
        for key, value in localized.items():
            if key in values:
                raise ValueError(f"Authored MAPS localisation collision: {path}")
            values[key] = value
        path.write_bytes(_pack_trad(values))
        reports["maps"] += 1

    label_folder = root / "Gen/Localisation/Localisation" / authored_build_name(root)
    label_keys = None
    for language in languages:
        path = label_folder / f"UNITS-{language}.dic"
        if not path.is_file():
            raise ValueError(f"Compiled campaign-label dictionary is missing: {path}")
        values = _trad_data(path.read_bytes())
        current = {}
        for label in compiled["map"]["labels"]:
            sentinel = f"__AGF_LABEL_{label['id'].upper()}__"
            matches = [key for key, value in values.items() if value == sentinel]
            if len(matches) != 1:
                raise ValueError(f"ModGen did not compile campaign label token: {label['id']}")
            current[label["id"]] = matches[0]
            values[matches[0]] = localized_field(compiled,label['text'],language)
        if label_keys is None:
            label_keys = current
        elif current != label_keys:
            raise ValueError("Campaign label hashes differ between languages")
        path.write_bytes(_pack_trad(values))
        reports["labels"] += len(current)
        for maps_path in map_targets:
            if _dictionary_language(maps_path) != language:
                continue
            maps_values = _trad_data(maps_path.read_bytes())
            for label in compiled["map"]["labels"]:
                key = current[label["id"]]
                if key in maps_values:
                    raise ValueError("Campaign label collides with an existing MAPS entry")
                maps_values[key] = localized_field(compiled,label['text'],language)
            maps_path.write_bytes(_pack_trad(maps_values))
    reports["authored_keys"] = len(authored_keys)
    reports["label_keys"] = {name: key.hex() for name, key in label_keys.items()}
    from .label_tokens import label_token_key

    names = []
    for row in compiled['battalions']:
        oob = row.get('oob', {})
        if 'localized_name' in oob:
            names.append((oob['name_token'], oob['name'], oob['localized_name']))
        organization = oob.get('organization', {})
        if 'localized_name' in organization:
            names.append((organization['name_token'], organization['name'],
                          organization['localized_name']))
        command = oob.get('command', {})
        if 'localized_name' in command:
            names.append((command['name_token'], command['name'], command['localized_name']))
    unique_names = _unique_localized_names(names)
    for language in languages:
        path = label_folder / f'UNITS-{language}.dic'
        values = _trad_data(path.read_bytes())
        for token, (original, localized) in unique_names.items():
            key = bytes.fromhex(label_token_key(token))
            if values.get(key) != original:
                raise ValueError('Compiled battalion name token differs from its authored source')
            values[key] = localized_field(compiled,localized,language)
        if unique_names:
            path.write_bytes(_pack_trad(values))
    reports['localized_battalion_names'] = len(unique_names)
    for kind,items in [('COMPANIES',[c for b in compiled['battalions'] for c in b.get('oob',{}).get('companies',[])]),
                       ('PLATOONS',[p for b in compiled['battalions'] for c in b.get('oob',{}).get('companies',[]) for p in c['platoons']])]:
        for language in languages:
            path=label_folder/f'{kind}-{language}.dic';values=_trad_data(path.read_bytes())
            for item in items:
                if 'localized_name' in item:
                    values[bytes.fromhex(label_token_key(item['name_token']))]=localized_field(compiled,item['localized_name'],language)
            path.write_bytes(_pack_trad(values))
    return reports


def authored_oob_contract(root, compiled):
    """Compare actual compiled company/platoon packs against public YAML."""
    root = Path(root)
    _, graph = decode((root / "Gen/NDF/GFX/Deck.ndfbin").read_bytes())
    exports = {path: oid for oid, path in graph["exports"].items()}
    loc = root / "Gen/Localisation/Localisation" / authored_build_name(root)
    texts = {}
    for name in ("UNITS", "COMPANIES", "PLATOONS"):
        texts.update(_trad_data((loc / f"{name}-RU.dic").read_bytes()))
    authored_rows = [row['oob'] for row in compiled['battalions'] if 'oob' in row
                     and 'division_definition' in row['oob']]
    if authored_rows:
        _, divisions = decode((root / 'Gen/NDF/GFX/Division.ndfbin').read_bytes())
        _, commands = decode((root / 'Gen/NDF/UI/BattleOrder.ndfbin').read_bytes())
        division_exports = {path: divisions['objects'][oid] for oid, path in divisions['exports'].items()}
        command_exports = {path: commands['objects'][oid] for oid, path in commands['exports'].items()}
        for oob in authored_rows:
            division_path = '$/GFX/Division/' + oob['division']
            deck = graph['objects'][exports['$/GFX/Deck/' + oob['deck_export']]]
            if _property(deck, 'DeckDivision').get('value') != division_path:
                raise ValueError('Authored division deck binding mismatch: ' + oob['id'])
            division = division_exports.get(division_path)
            if division is None or division['class'] != 'TDeckDivisionDescriptor':
                raise ValueError('Authored division descriptor missing: ' + oob['id'])
            definition = oob['division_definition']
            division_name = definition.get('localized_name', {}).get('ru', definition['name'])
            if texts.get(bytes.fromhex(_property(division, 'DivisionName')['value_hex'])) != division_name:
                raise ValueError('Authored division name mismatch: ' + oob['id'])
            tags = [value['value'] for value in _property(division, 'DivisionTags')['items']]
            if tags != ['STRAT', definition['coalition']]:
                raise ValueError('Authored division coalition tags mismatch: ' + oob['id'])
            for organization in ([oob['command']] if 'command' in oob else []) + [oob['organization']]:
                command = command_exports.get('$/UI/BattleOrder/' + organization['export'])
                if command is None or command['class'] != 'TBattleOrderSubordination':
                    raise ValueError('Authored command descriptor missing: ' + oob['id'])
                expected_name = organization.get('localized_name', {}).get('ru', organization['name'])
                if texts.get(bytes.fromhex(_property(command, 'NameToken')['value_hex'])) != expected_name:
                    raise ValueError('Authored command name mismatch: ' + oob['id'])
                parents = [prop['value'] for prop in command['properties'] if prop['property_name'] == 'Superior']
                if organization['superior'] is None:
                    if parents:
                        raise ValueError('Authored command root inherits a parent: ' + oob['id'])
                else:
                    parent = command_exports.get('$/UI/BattleOrder/' + organization['superior'])
                    if parent is None or len(parents) != 1 or parents[0].get('object_id') != parent['id']:
                        raise ValueError('Authored command regiment parent mismatch: ' + oob['id'])
    report = {}
    for row in compiled["battalions"]:
        if "oob" not in row:
            continue
        oob = row["oob"]
        path = "$/GFX/Deck/" + oob["deck_export"]
        if path not in exports:
            raise ValueError("Authored deck is absent: " + row["id"])
        deck = graph["objects"][exports[path]]
        expected_packs = [pack["signature"] for company in oob["companies"]
                          for platoon in company["platoons"] for pack in platoon["packs"]
                          for _ in range(pack["count"])]
        actual_packs = []
        for item in _property(deck, "DeckPackList")["items"]:
            pack = {p["property_name"]: p["value"].get("value")
                    for p in graph["objects"][item["object_id"]]["properties"]}
            actual_packs.append({"unit": pack["UnitDescriptor"],
                                 "transport": pack.get("TransporterDescriptor", ""),
                                 "experience": pack.get("ExperienceLevel", 0),
                                 "number": pack.get("Number", 1)})
        if actual_packs != expected_packs:
            raise ValueError("Authored deck composition mismatch: " + row["id"])
        companies = _property(deck, "DeckCombatGroupList")["items"]
        if len(companies) != len(oob["companies"]):
            raise ValueError("Authored company count mismatch")
        index = 0
        for company_ref, company in zip(companies, oob["companies"]):
            obj = graph["objects"][company_ref["object_id"]]
            if texts.get(bytes.fromhex(_property(obj, "Name")["value_hex"])) != company["name"]:
                raise ValueError("Authored company name mismatch")
            platoons = _property(obj, "SmartGroupList")["items"]
            if len(platoons) != len(company["platoons"]):
                raise ValueError("Authored platoon count mismatch")
            for platoon_ref, platoon in zip(platoons, company["platoons"]):
                obj = graph["objects"][platoon_ref["object_id"]]
                if texts.get(bytes.fromhex(_property(obj, "Name")["value_hex"])) != platoon["name"]:
                    raise ValueError("Authored platoon name mismatch")
                expected = []
                for pack in platoon["packs"]:
                    expected.append((index, pack["count"]))
                    index += pack["count"]
                actual = [(item["key"]["value"], item["value"]["value"])
                          for item in _property(obj, "PackIndexUnitNumberList")["items"]]
                if actual != expected:
                    raise ValueError("Authored platoon pack assignment mismatch")
        report[row["id"]] = {"companies": len(companies), "packs": index}
    return report


def validate_authored_candidate(root, compiled):
    """Run binary-level acceptance checks on one complete candidate tree."""
    from .battleground_policy import validate_authored_battleground_policy
    validate_authored_battleground_policy(compiled)
    root = Path(root).resolve()
    from .modconfig import validate_scenario_config
    from .campaign_identity import campaign_identity, definition_identity_contract
    identity = campaign_identity(compiled)
    scenario = identity['scenario']
    from .current_campaign import VANILLA_MAPS, _vanilla_maps
    validate_scenario_config((root / "Config.ini").read_bytes(), identity['display_name'],
                             local_mod_id=identity.get('local_mod_id'))
    if {path.name for path in (root / "Scenarios").glob("*.dat")} != {
            f"{scenario}_Definition.dat", f"{scenario}_Details.dat"}:
        raise ValueError("Authored candidate has unexpected scenario archives")
    declared = set((root / "Gen/DeclaredFiles.txt").read_text(encoding="utf-8").splitlines())
    for language in VANILLA_MAPS:
        maps_path = root / f"Gen/Localisation/Localisation/Core/MAPS-{language}.dic"
        values = _trad_data(maps_path.read_bytes())
        vanilla = _trad_data(_vanilla_maps(language))
        if any(values.get(key) != text for key, text in vanilla.items()):
            raise ValueError("Authored candidate changes vanilla localisation")
        for relative in (f"Gen/AllPlatforms/Localisation/Localisation/Core/MAPS-{language}.dic",
                         f"Gen/AllPlatforms/Localisation/{language}/Localisation/Core/MAPS.dic"):
            if (root / relative).read_bytes() != maps_path.read_bytes():
                raise ValueError("Authored MAPS language projection mismatch")
        if language != "DEV" and f"ZZ:/Localisation/Localisation/Core/MAPS-{language}.dic" not in declared:
            raise ValueError("Authored MAPS dictionary is not mounted")
        expected_text = authored_text(compiled, language)
        if any(values.get(key) != text for key, text in expected_text.items()):
            raise ValueError("Authored campaign text mismatch")
        map_values = values
        for part in ("TROPHIES", "Scripting/Dialog", "Scripting/Localization"):
            resource = f"Localisation/Localisation/{scenario}/{part}-{language}.dic"
            values = _trad_data((root / "Gen" / resource).read_bytes())
            shared = {key for key in values.keys() & map_values.keys()
                      if key.startswith((b'RDLN', b'AGF1'))}
            if any(values[key] != map_values[key] for key in shared):
                raise ValueError('Authored bootstrap/runtime text differs from MAPS')
            if language != "DEV" and "ZZ:/" + resource not in declared:
                raise ValueError("Authored runtime dictionary is not mounted")
            if any(values.get(key) != text for key, text in expected_text.items()):
                raise ValueError("Authored runtime text mismatch")
    definition = root / f"Scenarios/{scenario}_Definition.dat"
    details = root / f"Scenarios/{scenario}_Details.dat"
    pawn = root / "Gen/NDF/GFX/Pawn.ndfbin"
    for path in (definition, details, pawn):
        if not path.is_file():
            raise ValueError(f"Authored candidate resource is missing: {path}")
    definition_payloads = _payloads(definition.read_bytes())
    definition_identity_contract(definition.read_bytes(), compiled)
    script = definition_payloads[f"NDF/Scenarios/GDScript/{scenario}.ndfbin"]
    script_report = authored_script_contract(script, compiled)
    _, script_graph = decode(script)
    from .authored_compaction import script_root, validate_pawn_imports
    _, pawn_graph = decode(pawn.read_bytes())
    validate_pawn_imports(script_graph, pawn_graph)
    runtime_compiled = copy.deepcopy(compiled)
    runtime_compiled['adapter']['script']['root'] = script_root(script_graph)
    from .prototype_audit import prototype_dependency_contract
    prototype_report = prototype_dependency_contract(script_graph, runtime_compiled)
    choice_localisation = validate_ingame_choices(root, script_choice_keys(
        script_graph, _reachable_objects(script_graph, runtime_compiled['adapter']['script']['root'])),
                                                  authored_choice_text(compiled))
    ingame_text = authored_ingame_text(compiled)
    production_localisation = validate_ingame_choices(root, set(ingame_text['US']), ingame_text)
    state_report = pawn_state_contract(pawn.read_bytes(), compiled)
    from .pawn import pawn_strategy_contract, ghost_mimetic_contract
    strategy_report = pawn_strategy_contract(pawn.read_bytes(), compiled)
    from .aviation import airfield_descriptor_contract
    airfield_report = airfield_descriptor_contract(pawn.read_bytes(), compiled)
    depiction = root / 'Gen/NDF/GFX/Depiction.ndfbin'
    if not depiction.is_file():
        raise ValueError('Missing ghost mimetic registry binary')
    ghost_report = ghost_mimetic_contract(depiction.read_bytes(), compiled)
    oob_report = authored_oob_contract(root, compiled)
    detail_payloads = _payloads(details.read_bytes())
    expected_details, _ = build_authored_details(compiled)
    if details.read_bytes() != expected_details:
        raise ValueError("Authored geography content differs from compiled config")
    runtime = detail_payloads["out/LevelDesign.ndfbin"]
    expected = {row["adapter_slot"]["name"]: row for row in compiled["deployments"]}
    active = [row for row in spawn_inventory(runtime)
              if row["auto_spawn"] and ("_pion_" in row["name"] or row['name'] in expected)]
    if set(row["name"] for row in active) != set(expected):
        raise ValueError("Authored candidate active spawn set mismatch")
    for row in active:
        wanted = expected[row["name"]]
        if (any(not math.isclose(row['position'][i],wanted['position'][i],rel_tol=0,abs_tol=.125) for i in (0,1))
                or row["class_name"] != "$/GFX/Pawn/" + wanted["unit_export"]):
            raise ValueError(f"Authored spawn mismatch: {row['name']}")
    initial_exports = [row["class_name"].rsplit("/", 1)[-1] for row in active]
    runtime_exports = [effect["unit_export"] for event in compiled["events"]
                       for effects in ([event["effects"]] if not event["choices"] else
                                       [choice["effects"] for choice in event["choices"]])
                       for effect in effects if 'spawn' in effect]
    runtime_exports += [row["unit_export"] for row in compiled["reinforcements"]]
    runtime_exports += [row['unit_export'] for row in compiled.get('aviation', {}).get('wings', [])]
    runtime_exports += [export for group in compiled.get('production', {}).get('groups', [])
                        for export in group['unit_exports']]
    if len(initial_exports + runtime_exports) != len(set(initial_exports + runtime_exports)):
        raise ValueError("Candidate reuses a mutable strategic battalion descriptor")
    map_runtime = None
    from .campaign_assets import validate_candidate_assets
    asset_report = validate_candidate_assets(root, compiled)
    from .division_emblems import verify_runtime_emblems
    emblem_report = verify_runtime_emblems(root / 'Gen', compiled.get('emblems', []))
    from .cinematic_layout import verify_cinematic_layout
    layout_report = verify_cinematic_layout(root / 'Gen', compiled)
    from .campaign_menu import verify_menu
    menu_report = verify_menu(root, compiled)
    if 'strategic_map' in compiled['adapter']:
        from .strategic_map_package import validate_strategic_map_runtime
        map_runtime = validate_strategic_map_runtime(root, compiled['adapter']['strategic_map'],
            world_assets=compiled.get('assets', {}).get('world'), strategic_grid=compiled['map'].get('strategic_grid'))
    return {
        "script": script_report,
        "choice_localisation": choice_localisation,
        "production_localisation": production_localisation,
        "pawn_states": state_report,
        "pawn_strategies": strategy_report,
        **({'airfields': airfield_report} if airfield_report else {}),
        "ghost_mimetics": ghost_report,
        "order_of_battle": oob_report,
        "prototype_dependencies": prototype_report,
        "active_spawns": len(active),
        "definition_sha256": sha256(definition.read_bytes()),
        "details_sha256": sha256(details.read_bytes()),
        "pawn_sha256": sha256(pawn.read_bytes()),
        **({'strategic_map': map_runtime} if map_runtime is not None else {}),
        **({'assets': asset_report} if asset_report else {}),
        **({'emblems': emblem_report} if compiled.get('emblems') else {}),
        **({'cinematic_layout':layout_report} if layout_report else {}),
        **({'menu':menu_report} if menu_report else {}),
    }


def assemble_authored_candidate(base_candidate, destination, compiled, *, event_images=None, map_runtime=None):
    """Create a complete immutable candidate from current ModGen output."""
    from .battleground_policy import validate_authored_battleground_policy
    validate_authored_battleground_policy(compiled)
    base_candidate = Path(base_candidate).resolve()
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Refusing to replace candidate: {destination}")
    shutil.copytree(base_candidate, destination, ignore=lambda directory, names: (
        {'GenerationReport.txt'} if Path(directory) == base_candidate / 'Gen' else set()))
    definition_path = destination / f"Scenarios/{SCENARIO}_Definition.dat"
    definition, definition_report = compile_authored_definition(
        definition_path.read_bytes(), compiled)
    definition_path.write_bytes(definition)
    details, details_report = build_authored_details(compiled)
    (destination / f"Scenarios/{SCENARIO}_Details.dat").write_bytes(details)
    pawn_path = destination / "Gen/NDF/GFX/Pawn.ndfbin"
    pawn, state_report = patch_authored_pawn_states(pawn_path.read_bytes(), compiled)
    pawn_path.write_bytes(pawn)
    localisation_report = patch_authored_localisation(destination, compiled)
    localisation_report['ingame'] = publish_ingame_choices(destination, authored_ingame_text(compiled))
    from .campaign_identity import isolate_candidate_identity
    isolate_candidate_identity(destination, compiled)
    from .registry_localisation import validate_registry_localisation
    validate_registry_localisation(destination)
    from .campaign_assets import stage_candidate_event_images, write_candidate_asset_metadata
    staged_event_art = stage_candidate_event_images(destination, compiled, event_images)
    write_candidate_asset_metadata(destination, compiled)
    if 'strategic_map' in compiled['adapter']:
        from .strategic_map_package import publish_strategic_map_runtime
        map_name = compiled['adapter']['strategic_map']['map_name']
        runtime = Path(map_runtime).resolve() if map_runtime is not None else None
        publish_strategic_map_runtime(destination, compiled['adapter']['strategic_map'],
            datas_map=runtime / 'DatasMap' if runtime is not None else None,
            maps=runtime / 'Maps' if runtime is not None else None,
            texture_root=runtime / 'Gen/PC/Texture' / map_name if runtime is not None else None,
            world_assets=compiled.get('assets', {}).get('world'), strategic_grid=compiled['map'].get('strategic_grid'))
    contract = validate_authored_candidate(destination, compiled)
    return {"definition": definition_report, "details": details_report,
            "states": state_report, "localisation": localisation_report,
            "contract": contract, "staged_event_art": staged_event_art}


def package_authored_campaign(source, profile, modgen_output, destination, *,
                              world_source=None, event_images=None, map_runtime=None):
    """Build a complete release from public YAML and official compiler output."""
    from .authoring import compile_campaign
    from .current_campaign import assemble_current_candidate
    from .full_campaign import write_full_bundle
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError("Build destination already exists: " + str(destination))
    from .battleground_policy import validate_authored_battleground_policy
    preview, _ = compile_campaign(source, profile)
    validate_authored_battleground_policy(preview)
    from .campaign_assets import attach_campaign_assets
    attach_campaign_assets(preview, world_source=world_source, event_images=event_images)
    if event_images is not None:
        from .event_images import verify_cooked_event_images
        verify_cooked_event_images(event_images, Path(modgen_output) / 'Gen')
    from .division_emblems import verify_cooked_emblems
    verify_cooked_emblems(source, modgen_output)
    from .campaign_menu import verify_menu
    verify_menu(modgen_output, preview, source)
    from .cinematic_layout import verify_cinematic_layout
    verify_cinematic_layout(Path(modgen_output) / 'Gen', preview, require_graphic_caption_bounds=True)
    destination.mkdir(parents=True)
    compiled, compile_report = compile_campaign(source, profile, destination / "compiled")
    assets = attach_campaign_assets(compiled, world_source=world_source, event_images=event_images)
    if assets:
        encoded = json.dumps(compiled, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        (destination / 'compiled/campaign.compiled.json').write_bytes(encoded + b'\n')
        compile_report['compiled_sha256'] = sha256(encoded)
        (destination / 'compiled/compile-report.json').write_text(
            json.dumps(compile_report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    corpus = Path(__file__).resolve().parents[1] / "artifacts/full-campaign-work/RedLine1989-v12"
    base = destination / "base"
    assemble_current_candidate(modgen_output, corpus, base, DEFAULT_CONFIG, validate=False)
    candidate = destination / "candidate"
    build_report = assemble_authored_candidate(base, candidate, compiled,
                                               event_images=event_images, map_runtime=map_runtime)
    config = destination / "compiled/campaign.compiled.json"
    bundle = write_full_bundle(candidate, config)
    report = {"candidate": str(candidate), "config": str(config), "bundle": str(bundle),
              "compile": compile_report, "build": build_report,
              "runtime_verified": False}
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
