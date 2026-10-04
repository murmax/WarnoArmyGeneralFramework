"""Typed, source-pinned offline transformations with complete semantic checks."""
import copy
import math
import struct
from .storage import sha256
from .xyz import XYZ
from .marshal26 import loads, dumps, Node
from .scriptgraph import decode_script, semantic_graph
from .cndf import decode, encode_objects, rebuild_objects
from .selectors import native_target


def check_spec(raw, spec, allowed):
    if set(spec) != {"source_sha256", "operations"}:
        raise ValueError("Unknown or missing module manifest fields")
    if spec["source_sha256"] != sha256(raw):
        raise ValueError("Module source fingerprint mismatch")
    if not isinstance(spec["operations"], list):
        raise ValueError("Module operations must be a list")
    for op in spec["operations"]:
        alternatives = allowed if isinstance(allowed, tuple) else (allowed,)
        if not isinstance(op,dict) or set(op) not in alternatives:
            raise ValueError("Unknown or missing operation fields")


def check_value(actual, op):
    if type(actual) is not type(op["expected"]) or actual != op["expected"]:
        raise ValueError("Property expected-value precondition failed")
    if type(actual) is not type(op["value"]):
        raise ValueError("Property type cannot change")
    if isinstance(actual,float) and (not math.isfinite(actual) or not math.isfinite(op["value"])):
        raise ValueError("Non-finite property value")


def report(raw, changed, operations, mode):
    return {"source_sha256":sha256(raw),"output_sha256":sha256(changed),
            "operations":copy.deepcopy(operations),"backend":mode,
            "semantic_diff_verified":True,"runtime_verified":False,
            "installable":False,
            "limitations":["Runtime load path and save compatibility not tested"]}


def patch_script(raw, spec):
    by_name = {"editor_name","constructor","argument","expected","value"}
    by_id = {"object_id","constructor","argument","expected","value"}
    check_spec(raw,spec,(by_name,by_id))
    xyz = XYZ.read(raw)
    tree = loads(xyz.payload)
    if dumps(tree) != xyz.payload:
        raise ValueError("Marshal lossless baseline failed")
    graph = decode_script(tree)
    expected = copy.deepcopy(semantic_graph(graph))
    code = bytearray(tree.value["code"].value)
    consts = tree.value["consts"].value
    targets = set()
    for op in spec["operations"]:
        if "editor_name" in op:
            found = [o for o in graph["objects"].values()
                     if o["properties"].get("EditorName",{}).get("value") == op["editor_name"]]
        else:
            found = [graph["objects"][op["object_id"]]] if op["object_id"] in graph["objects"] else []
        if len(found) != 1 or found[0]["constructor"] != op["constructor"]:
            raise ValueError("Module selector does not uniquely match the expected constructor")
        obj = found[0]
        key = (obj["id"],op["argument"])
        if key in targets:
            raise ValueError("Duplicate module target")
        targets.add(key)
        value = obj["kwargs"].get(op["argument"])
        if not value or value["kind"] != "literal" or "instruction" not in value:
            raise ValueError("Only direct constructor literals can be edited")
        check_value(value["value"],op)
        position = value["instruction"]
        if code[position] != 100 or struct.unpack_from("<H",code,position+1)[0] != value["constant"]:
            raise ValueError("Literal provenance mismatch")
        if value["value"] == op["value"]:
            continue
        old = consts[value["constant"]]
        if old.tag == "i":
            if not -(2**31) <= op["value"] < 2**31:
                raise ValueError("int32 property overflow")
            new = Node("i",op["value"])
        elif old.tag == "g":
            new = Node("g",struct.pack("<d",op["value"]))
        elif old.tag in ("s","u"):
            new = Node(old.tag,op["value"].encode("utf-8"))
        else:
            raise ValueError("Unsupported typed literal mutation")
        if len(consts) >= 65536:
            raise ValueError("Extended constant operands require a full assembler")
        struct.pack_into("<H",code,position+1,len(consts))
        consts.append(new)
        expected["objects"][obj["id"]]["kwargs"][op["argument"]]["value"] = op["value"]
    tree.value["code"].value = bytes(code)
    payload = dumps(tree)
    changed = xyz.research_envelope(payload)
    decoded = XYZ.read(changed)
    if semantic_graph(decode_script(loads(decoded.payload))) != expected:
        raise ValueError("Unexpected script semantic changes")
    # Independent library must also accept the resulting Python 2 code object.
    if decoded.code().co_code != bytes(code):
        raise ValueError("Independent bytecode parser disagrees")
    result = report(raw,changed,spec["operations"],"python26-descriptor-data")
    result["limitations"].append("XYZ opaque source field preserved; its engine validation contract is unresolved")
    return changed,result


def patch_native(raw, spec):
    fields = {"export","class","property","expected","value"}
    check_spec(raw,spec,(fields, fields | {'root_class','traverse'}))
    doc, graph = decode(raw)
    section = next(s for s in doc.sections if s.name == "OBJE")
    if encode_objects(graph["objects"]) != doc.full_data[section.offset:section.offset+section.size]:
        raise ValueError("CNDF lossless baseline failed")
    expected = copy.deepcopy(graph)
    targets = set()
    for op in spec["operations"]:
        obj = native_target(expected, op)
        key = (obj["id"],op["property"])
        if key in targets:
            raise ValueError("Duplicate module target")
        targets.add(key)
        props = [p for p in obj["properties"] if p["property_name"] == op["property"]]
        if len(props) != 1 or props[0]["value"]["type_id"] not in (0,1,2,3,5,6,0x13,0x18,0x19):
            raise ValueError("Only existing numeric/bool native properties are supported")
        value = props[0]["value"]
        check_value(value["value"],op)
        value["value"] = op["value"]
    changed = rebuild_objects(doc,expected)
    _, after = decode(changed)
    for key in ("objects","classes","properties","strings","translations","imports","exports"):
        if after[key] != expected[key]:
            raise ValueError(f"Unexpected native semantic changes in {key}")
    return changed,report(raw,changed,spec["operations"],"native-gdscript")
