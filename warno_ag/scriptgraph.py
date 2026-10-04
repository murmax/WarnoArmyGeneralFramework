"""Passive symbolic decoding of generated scenario bytecode.

No eval, imports, descriptors, callbacks or game code are executed. Only the
observed straight-line constructor language is accepted; arbitrary Python is
rejected. Literal provenance identifies a SINGLE use, not a shared constant.
"""
from collections import Counter
import struct
from .marshal26 import scalar

OPS = {83:"RETURN_VALUE",90:"STORE_NAME",91:"DELETE_NAME",95:"STORE_ATTR",
       100:"LOAD_CONST",101:"LOAD_NAME",103:"BUILD_LIST",105:"LOAD_ATTR",
       107:"IMPORT_NAME",131:"CALL_FUNCTION",132:"MAKE_FUNCTION"}


def instructions(code):
    pos = 0
    while pos < len(code):
        start = pos
        op = code[pos]
        pos += 1
        if op not in OPS:
            raise ValueError(f"Unsupported generated-script opcode {op} at {start}")
        arg = None
        if op >= 90:
            if pos + 2 > len(code):
                raise ValueError("Truncated bytecode argument")
            arg = struct.unpack_from("<H", code, pos)[0]
            pos += 2
        yield start, OPS[op], arg


def decode_script(root):
    if root.tag != "c":
        raise ValueError("Scenario payload must be a code object")
    co = root.value
    code = co["code"].value
    consts = co["consts"].value
    names = [scalar(n) for n in co["names"].value]
    stack, bindings, objects, imports, functions = [], {}, {}, [], {}
    bindings.update({k:{"kind":"literal", "value":v, "marshal_type":"builtin"}
                     for k,v in (("True",True),("False",False),("None",None))})
    max_stack, count, returned = 0, 0, False
    def popn(n):
        if n > len(stack):
            raise ValueError("Scenario bytecode stack underflow")
        result = stack[-n:] if n else []
        if n:
            del stack[-n:]
        return result
    for offset, op, arg in instructions(code):
        count += 1
        if returned:
            raise ValueError("Instructions after module return")
        if op == "LOAD_CONST":
            node = consts[arg]
            if node.tag == "c":
                value = {"kind":"code", "name":scalar(node.value["name"]), "constant":arg}
            else:
                value = {"kind":"literal", "value":scalar(node), "marshal_type":node.tag,
                         "constant":arg, "instruction":offset}
            stack.append(value)
        elif op == "IMPORT_NAME":
            level, fromlist = popn(2)
            if level.get("value") not in (0,-1) or fromlist.get("value") is not None:
                raise ValueError("Unsupported import form")
            name = names[arg]
            imports.append(name)
            stack.append({"kind":"symbol", "path":name.split(".")[0]})
        elif op == "LOAD_NAME":
            name = names[arg]
            if name not in bindings:
                raise ValueError(f"Unbound script name {name} at {offset}")
            stack.append(bindings[name])
        elif op == "LOAD_ATTR":
            value = popn(1)[0]
            if value["kind"] == "symbol":
                stack.append({"kind":"symbol", "path":value["path"]+"."+names[arg]})
            else:
                stack.append({"kind":"attribute", "owner":value, "name":names[arg]})
        elif op == "BUILD_LIST":
            stack.append({"kind":"list", "items":popn(arg)})
        elif op == "CALL_FUNCTION":
            positional, keywords = arg & 255, arg >> 8
            pairs = popn(keywords*2)
            kwargs = {}
            for i in range(0,len(pairs),2):
                key = pairs[i]
                if key["kind"] != "literal" or not isinstance(key["value"], str) or key["value"] in kwargs:
                    raise ValueError("Invalid constructor keyword")
                kwargs[key["value"]] = pairs[i+1]
            args = popn(positional)
            target = popn(1)[0]
            if target["kind"] != "symbol":
                raise ValueError("Only descriptor constructors accepted")
            stack.append({"kind":"call", "constructor":target["path"], "args":args,
                          "kwargs":kwargs, "instruction":offset})
        elif op == "STORE_NAME":
            name = names[arg]
            value = popn(1)[0]
            if value["kind"] == "call":
                if name in objects:
                    raise ValueError("Descriptor assigned twice")
                objects[name] = dict(value, id=name, properties={})
                bindings[name] = {"kind":"ref", "id":name}
            else:
                bindings[name] = value
        elif op == "STORE_ATTR":
            value, target = popn(2)
            if target["kind"] != "ref":
                raise ValueError("Property owner is not a descriptor")
            obj = objects[target["id"]]
            key = names[arg]
            if key in obj["properties"]:
                raise ValueError("Property assigned twice")
            obj["properties"][key] = value
        elif op == "DELETE_NAME":
            if names[arg] not in bindings:
                raise ValueError("Deleting an unbound script name")
            del bindings[names[arg]]
        elif op == "MAKE_FUNCTION":
            value = popn(1)[0]
            if arg or value["kind"] != "code":
                raise ValueError("Only a no-default launch function is supported")
            functions[value["name"]] = value
            stack.append(dict(value, kind="function"))
        elif op == "RETURN_VALUE":
            value = popn(1)[0]
            if value.get("kind") != "literal" or value.get("value") is not None or stack:
                raise ValueError("Unexpected scenario return/stack residue")
            returned = True
        max_stack = max(max_stack, len(stack))
    if not returned or max_stack > co["stacksize"]:
        raise ValueError("Invalid script stack or missing return")
    def refs(value):
        if isinstance(value, dict):
            if value.get("kind") == "ref":
                yield value["id"]
            else:
                for child in value.values():
                    yield from refs(child)
        elif isinstance(value,list):
            for child in value:
                yield from refs(child)
    edges = []
    for name,obj in objects.items():
        for target in refs(obj):
            if target not in objects:
                raise ValueError(f"Unresolved descriptor reference: {target}")
            edges.append([name,target])
    return {"schema":1,"filename":scalar(co["filename"]),"imports":imports,
            "objects":objects,"edges":edges,"functions":functions,
            "live_bindings":bindings,"instruction_count":count,"max_stack":max_stack,
            "constructors":dict(Counter(v["constructor"] for v in objects.values()))}


def semantic_graph(graph):
    """Remove bytecode source locations, retaining typed data and graph links."""
    def clean(v):
        if isinstance(v, dict):
            return {k:clean(x) for k,x in v.items() if k not in ("constant","instruction")}
        if isinstance(v,list):
            return [clean(x) for x in v]
        return v
    return clean(graph)
