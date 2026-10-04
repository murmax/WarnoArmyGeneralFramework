"""Typed edits for Army General editor and compiled LevelDesign spawn graphs."""
import copy
import re

from .cndf import decode, encode_objects, encode_strings, rebuild_sections
from .storage import sha256


def _properties(obj):
    return {item['property_name']: item['value'] for item in obj['properties']}


def spawn_inventory(raw):
    _, graph = decode(raw)
    spawns = {obj['id']: _properties(obj) for obj in graph['objects']
              if obj['class'] == 'TGameDesignAddOn_Spawn'}
    points = {}
    representations = {'TSaveDescriptorItemPoint':'AxeT',
                       'TGameDesignItem':'Position'}
    present={obj['class'] for obj in graph['objects'] if obj['class'] in representations}
    if len(present)!=1:
        raise ValueError('Expected exactly one strategic item representation')
    item_class,=present; position_property=representations[item_class]
    for obj in graph['objects']:
        if obj['class'] != item_class:
            continue
        props = _properties(obj)
        addon = props.get('AddOn', {})
        if addon.get('type') == 'obj_ref' and addon['object_id'] in spawns:
            if addon['object_id'] in points:
                raise ValueError('Spawn is linked to multiple strategic points')
            position=props[position_property]
            if ((item_class=='TSaveDescriptorItemPoint' and position['type']!='vec3')
                    or (item_class=='TGameDesignItem' and position['type']!='float2')):
                raise ValueError('Unexpected strategic position type')
            points[addon['object_id']] = position['value']
    if set(points) != set(spawns):
        raise ValueError('Every strategic spawn must be linked to exactly one point')
    result=[]
    for object_id,props in spawns.items():
        count=props.get('NbOfUnitToSpawn', {}).get('value', 1)
        auto=(not props.get('DisableAutoSpawn', {}).get('value', False)
              if item_class=='TGameDesignItem' else count!=0)
        result.append({'object_id':object_id,'name':props['Name']['value'],
                       'class_name':props['ClassName']['value'],
                       'spawn_count':count,'auto_spawn':auto,
                       'position':points[object_id]})
    return result


def map_feature_inventory(raw):
    """Return stable, human-readable strategic map points for verification."""
    _, graph = decode(raw)
    representations = {"TSaveDescriptorItemPoint": "AxeT", "TGameDesignItem": "Position"}
    present = {obj["class"] for obj in graph["objects"] if obj["class"] in representations}
    if len(present) != 1:
        raise ValueError("Expected exactly one strategic item representation")
    item_class, = present
    position_property = representations[item_class]
    result = []
    listed_points = {item.get("object_id") for obj in graph["objects"] if obj["is_top_object"]
                     for prop in obj["properties"] for item in prop["value"].get("items", [])}
    for obj in graph["objects"]:
        if obj["class"] != item_class or obj["id"] not in listed_points:
            continue
        props = _properties(obj)
        reference = props.get("AddOn", {})
        if reference.get("type") != "obj_ref":
            continue
        addon = graph["objects"][reference["object_id"]]
        if addon["class"] not in {
            "TGameDesignAddOn_Name", "TGameDesignAddOn_InfluencePoint",
            "TGameDesignAddOn_LabelOnMap",
        }:
            continue
        values = _properties(addon)
        result.append({
            "class": addon["class"], "name": values["Name"]["value"],
            "guid": values.get("GUID", {}).get("value_hex"),
            "position": props[position_property]["value"][:2],
            "alliance": values.get("NumAlliance", {}).get("value", 0),
            "influence": values.get("InfluenceValue", {}).get("value"),
            "commands_influence": values.get("CommandsInfluenceZone", {}).get("value"),
            "token": values.get("Token", {}).get("value"),
            "component": values.get("ComponentName", {}).get("value"),
        })
    return result


def patch_items(raw, spec):
    required = {'source_sha256', 'keep', 'disable_auto_spawn',
                'disabled_position_base', 'disabled_position_step'}
    if isinstance(spec, dict) and 'disable_names' in spec:
        required.add('disable_names')
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError('Unknown or missing Items patch fields')
    if (not isinstance(spec['source_sha256'], str)
            or not re.fullmatch('[0-9a-f]{64}', spec['source_sha256'])
            or sha256(raw) != spec['source_sha256']):
        raise ValueError('Items source fingerprint mismatch')
    if (not isinstance(spec['keep'], list) or not spec['keep']
            or set(spec['disabled_position_base']) != {'x', 'y'}
            or spec['disable_auto_spawn'] is not True
            or type(spec['disabled_position_step']) not in (int, float)):
        raise ValueError('Invalid Items patch specification')
    doc, graph = decode(raw)
    changed = copy.deepcopy(graph)
    objects = changed['objects']
    spawn_objects = { _properties(obj)['Name']['value']: obj for obj in objects
                     if obj['class'] == 'TGameDesignAddOn_Spawn'}
    if len(spawn_objects) != len([obj for obj in objects if obj['class'] == 'TGameDesignAddOn_Spawn']):
        raise ValueError('Duplicate strategic spawn name')
    disable_names = spec.get('disable_names', [])
    if (not isinstance(disable_names, list)
            or any(not isinstance(name, str) or name not in spawn_objects for name in disable_names)
            or len(disable_names) != len(set(disable_names))):
        raise ValueError('Invalid explicit disabled spawn names')
    representations = {'TSaveDescriptorItemPoint':'AxeT',
                       'TGameDesignItem':'Position'}
    present={obj['class'] for obj in objects if obj['class'] in representations}
    if len(present)!=1:
        raise ValueError('Expected exactly one strategic item representation')
    item_class,=present; position_property=representations[item_class]
    disable_schema_name=('DisableAutoSpawn' if item_class=='TGameDesignItem'
                         else 'NbOfUnitToSpawn')
    disable_properties=[item for item in graph['properties']
                        if item['class']=='TGameDesignAddOn_Spawn'
                        and item['name']==disable_schema_name]
    if len(disable_properties)!=1:
        raise ValueError(f'Missing or ambiguous {disable_schema_name} schema property')
    disable_property_id=disable_properties[0]['id']
    point_objects = {}
    for obj in objects:
        if obj['class'] == item_class:
            props = _properties(obj)
            addon = props.get('AddOn', {})
            if addon.get('type') == 'obj_ref' and addon['object_id'] in {o['id'] for o in spawn_objects.values()}:
                point_objects[addon['object_id']] = obj
    keep = {}
    for row in spec['keep']:
        if (not isinstance(row, dict) or set(row) != {'name', 'x', 'y', 'class_name'}
                or not isinstance(row['name'], str) or not isinstance(row['class_name'], str)
                or type(row['x']) not in (int, float) or type(row['y']) not in (int, float)
                or row['name'] in keep):
            raise ValueError('Invalid or duplicate configured spawn')
        if row['name'] not in spawn_objects:
            raise ValueError(f'Missing configured spawn: {row["name"]}')
        keep[row['name']] = row
    string_indices = {value: index for index, value in enumerate(changed['strings'])}
    string_uses = {}

    def count_strings(value):
        if isinstance(value, dict):
            if value.get('type') == 'strg_ref':
                index = value['index']
                string_uses[index] = string_uses.get(index, 0) + 1
            for child in value.values():
                count_strings(child)
        elif isinstance(value, list):
            for child in value:
                count_strings(child)

    count_strings(objects)
    disabled_index = 0
    for name, obj in spawn_objects.items():
        props = _properties(obj)
        class_value = props['ClassName']
        point = _properties(point_objects[obj['id']])[position_property]
        if name in keep:
            row = keep[name]
            target_class = row['class_name']
            target_position = [float(row['x']), float(row['y'])]
            if point['type']=='vec3': target_position.append(0.0)
            disable=[p for p in obj['properties'] if p['property_name']==disable_schema_name]
            if disable:
                expected_type=0 if item_class=='TGameDesignItem' else 2
                if len(disable)!=1 or disable[0]['value']['type_id']!=expected_type:
                    raise ValueError(f'Unexpected {disable_schema_name} property layout')
                disable[0]['value']['value']=(False if item_class=='TGameDesignItem' else 1)
        elif '_pion_' in name or name in disable_names:
            # This is the engine-authored switch used by existing disabled
            # spawns. NbOfUnitToSpawn=0 is deliberately not used: WARNO treats
            # an absent/zero count as the default one pawn in Army General.
            target_class = class_value['value']
            disable=[p for p in obj['properties'] if p['property_name']==disable_schema_name]
            if disable:
                expected_type=0 if item_class=='TGameDesignItem' else 2
                if len(disable)!=1 or disable[0]['value']['type_id']!=expected_type:
                    raise ValueError(f'Unexpected {disable_schema_name} property layout')
                disable[0]['value']['value']=(True if item_class=='TGameDesignItem' else 0)
            else:
                obj['properties'].append({'property_id':disable_property_id,
                                          'property_name':disable_schema_name,
                                          'value':({'type_id':0,'type':'bool',
                                                    'reference_prefix':False,'value':True}
                                                   if item_class=='TGameDesignItem' else
                                                   {'type_id':2,'type':'int32',
                                                    'reference_prefix':False,'value':0})})
            base, step = spec['disabled_position_base'], float(spec['disabled_position_step'])
            target_position = [float(base['x']) + disabled_index*step,
                               float(base['y'])]
            if point['type']=='vec3': target_position.append(0.0)
            disabled_index += 1
        else:
            continue
        index = class_value['index']
        if string_uses.get(index) == 1:
            previous = changed['strings'][index]
            if string_indices.get(previous) == index:
                del string_indices[previous]
            changed['strings'][index] = target_class
            string_indices[target_class] = index
        elif target_class not in string_indices:
            string_indices[target_class] = len(changed['strings'])
            changed['strings'].append(target_class)
        if string_uses.get(index) != 1:
            class_value['index'] = string_indices[target_class]
            if class_value['index'] != index:
                string_uses[index] -= 1
                destination_index = class_value['index']
                string_uses[destination_index] = string_uses.get(destination_index, 0) + 1
        class_value['value'] = target_class
        point['value'] = target_position
    if not keep:
        raise ValueError('Campaign requires at least one active battalion')
    rebuilt = rebuild_sections(doc, {'STRG': encode_strings(changed['strings']),
                                     'OBJE': encode_objects(objects)})
    after = spawn_inventory(rebuilt)
    report = {'source_sha256': sha256(raw), 'output_sha256': sha256(rebuilt),
              'active_battalions': len(keep), 'disabled_battalions': disabled_index,
              'spawn_count': len(after),
              'disable_mechanism':disable_schema_name,
              'spec': copy.deepcopy(spec)}
    if rebuilt == raw:
        raise ValueError('Items patch unexpectedly made no changes')
    return rebuilt, report


def patch_map_features(raw, spec):
    """Patch author-visible map content while preserving the geographic mesh.

    ``spec`` is produced by :mod:`warno_ag.authoring`; callers cannot provide
    template names directly in campaign YAML.  The adapter reuses current
    LevelDesign shells because those are the objects registered by WARNO's
    strategic map loader, but replaces their positions, ownership and GUIDs.
    """
    required = {"source_sha256", "flags", "influence_sources", "labels", "runtime_positions"}
    if not isinstance(spec, dict) or set(spec) != required:
        raise ValueError("Unknown or missing map-feature patch fields")
    if sha256(raw) != spec["source_sha256"]:
        raise ValueError("Map-feature source fingerprint mismatch")
    doc, graph = decode(raw)
    changed = copy.deepcopy(graph)
    objects = changed["objects"]
    representations = {"TSaveDescriptorItemPoint": "AxeT", "TGameDesignItem": "Position"}
    present = {obj["class"] for obj in objects if obj["class"] in representations}
    if len(present) != 1:
        raise ValueError("Expected exactly one strategic item representation")
    item_class, = present
    position_property = representations[item_class]
    points = {}
    for obj in objects:
        if obj["class"] != item_class:
            continue
        props = _properties(obj)
        addon = props.get("AddOn", {})
        if addon.get("type") == "obj_ref":
            points[addon["object_id"]] = props[position_property]
    named = {}
    for obj in objects:
        if obj["class"].startswith("TGameDesignAddOn_"):
            name = _properties(obj).get("Name", {}).get("value")
            if name is not None:
                key = (obj["class"], name)
                if key in named:
                    raise ValueError(f"Duplicate map add-on shell: {key}")
                named[key] = obj

    property_ids = {(row["class"], row["name"]): row["id"] for row in changed["properties"]}

    def set_scalar(obj, name, value, type_id, type_name):
        found = [prop for prop in obj["properties"] if prop["property_name"] == name]
        if len(found) > 1:
            raise ValueError(f"Ambiguous map property {obj['class']}.{name}")
        if found:
            found[0]["value"]["value"] = value
            return
        key = (obj["class"], name)
        if key not in property_ids:
            raise ValueError(f"Missing map property schema {obj['class']}.{name}")
        obj["properties"].append({
            "property_id": property_ids[key], "property_name": name,
            "value": {"type_id": type_id, "type": type_name,
                      "reference_prefix": False, "value": value},
        })

    def set_string(obj, name, value):
        prop = _properties(obj).get(name)
        if prop is None or prop.get("type") != "strg_ref":
            raise ValueError(f"Missing map string property {obj['class']}.{name}")
        if prop["value"] == value:
            return
        # Label tokens and styles are heavily interned in vanilla data.  Give
        # an authored label its own string-table entry instead of modifying a
        # shared entry and accidentally renaming unrelated geography.
        prop["index"] = len(changed["strings"])
        changed["strings"].append(value)
        prop["value"] = value

    def set_position(obj, position):
        if obj["id"] not in points:
            raise ValueError(f"Map add-on has no point: {obj['id']}")
        target = [float(position[0]), float(position[1])]
        point = points[obj["id"]]
        if point["type"] == "vec3":
            target.append(0.0)
        point["value"] = target

    used_flags = set()
    for row in spec["flags"]:
        slot = row["adapter_slot"]["name"]
        obj = named.get(("TGameDesignAddOn_Name", slot))
        if obj is None or slot in used_flags:
            raise ValueError(f"Missing or duplicate flag shell: {slot}")
        used_flags.add(slot)
        set_position(obj, row["position"])
        guid = _properties(obj).get("GUID")
        if guid is None or guid.get("type") != "guid":
            raise ValueError(f"Flag shell has no GUID: {slot}")
        guid["value_hex"] = row["guid"]

    used_positions = set()
    for row in spec["runtime_positions"]:
        slot = row["adapter_slot"]["name"]
        obj = named.get(("TGameDesignAddOn_Name", slot))
        if obj is None or slot in used_positions or slot in used_flags:
            raise ValueError(f"Missing or duplicate runtime-position shell: {slot}")
        used_positions.add(slot)
        set_position(obj, row["position"])
        guid = _properties(obj).get("GUID")
        if guid is None or guid.get("type") != "guid":
            raise ValueError(f"Runtime-position shell has no GUID: {slot}")
        guid["value_hex"] = row["guid"]

    influence_shells = [name for cls, name in named if cls == "TGameDesignAddOn_InfluencePoint"]
    configured_influence = {}
    for row in spec["influence_sources"]:
        slot = row["adapter_slot"]["name"]
        if slot in configured_influence:
            raise ValueError(f"Duplicate influence shell: {slot}")
        configured_influence[slot] = row
    for slot in influence_shells:
        obj = named[("TGameDesignAddOn_InfluencePoint", slot)]
        row = configured_influence.get(slot)
        if row is None:
            set_scalar(obj, "CommandsInfluenceZone", False, 0, "bool")
            set_scalar(obj, "InfluenceValue", 0.0, 5, "float32")
            continue
        set_position(obj, row["position"])
        set_scalar(obj, "CommandsInfluenceZone", True, 0, "bool")
        set_scalar(obj, "NumAlliance", 1 if row["side"] == "nato" else 0, 2, "int32")
        set_scalar(obj, "InfluenceValue", float(row["value"]), 5, "float32")

    size_component = {"large": "LabelVille_01", "medium": "LabelVille_02", "small": "LabelVille_03"}
    used_labels = set()
    for row in spec["labels"]:
        slot = row["adapter_slot"]["name"]
        obj = named.get(("TGameDesignAddOn_LabelOnMap", slot))
        if obj is None or slot in used_labels:
            raise ValueError(f"Missing or duplicate label shell: {slot}")
        used_labels.add(slot)
        set_position(obj, row["position"])
        set_string(obj, "Token", row["token"])
        set_string(obj, "ComponentName", size_component[row["size"]])

    # Remove stock labels from the actual database/editor item list. Merely
    # replacing the configured labels leaves every other town caption alive.
    removed_labels = {obj["id"] for (cls, name), obj in named.items()
                      if cls == "TGameDesignAddOn_LabelOnMap" and name not in used_labels}
    removed_points = {obj["id"] for obj in objects if obj["class"] == item_class
                      and _properties(obj).get("AddOn", {}).get("object_id") in removed_labels}
    for obj in objects:
        if not obj["is_top_object"]:
            continue
        for property_row in obj["properties"]:
            value = property_row["value"]
            if value.get("type") == "list":
                value["items"] = [item for item in value["items"]
                                  if item.get("object_id") not in removed_points]
                value["length"] = len(value["items"])

    rebuilt = rebuild_sections(doc, {
        "STRG": encode_strings(changed["strings"]),
        "OBJE": encode_objects(objects),
    })
    # Decode the output immediately.  CNDF canonicalisation can deduplicate
    # appended strings, so semantic inventories are verified by the adapter
    # rather than comparing internal string-table indices byte-for-byte.
    decode(rebuilt)
    return rebuilt, {
        "output_sha256": sha256(rebuilt), "flags": len(spec["flags"]),
        "influence_sources": len(spec["influence_sources"]), "labels": len(spec["labels"]),
        "runtime_positions": len(spec["runtime_positions"]),
    }
