"""Lossless, bounded CPython 2.x marshal syntax tree (no code execution).

Raw type tags, interned-string references and their ordering are preserved.
Unlike the host marshal module, this reader knows the Python 2 code layout.
"""
from dataclasses import dataclass
import struct


@dataclass
class Node:
    tag: str
    value: object = None


FIELDS = ("code", "consts", "names", "varnames", "freevars", "cellvars", "filename", "name")


class Reader:
    def __init__(self, data):
        self.data, self.pos, self.interned, self.count = data, 0, [], 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError("Marshal field outside input")
        value = self.data[self.pos:self.pos+n]
        self.pos += n
        return value

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def node(self, depth=0):
        self.count += 1
        if depth > 100 or self.count > 2_000_000:
            raise ValueError("Marshal structural limit exceeded")
        tag = chr(self.take(1)[0])
        if tag in "0NFTS.":
            return Node(tag)
        if tag == "i":
            return Node(tag, self.i32())
        if tag == "I":
            return Node(tag, struct.unpack("<q", self.take(8))[0])
        if tag == "l":
            length = self.i32()
            return Node(tag, (length, self.take(abs(length) * 2)))
        if tag in "g y".replace(" ", ""):
            return Node(tag, self.take(8 if tag == "g" else 16))
        if tag in "fx":
            parts = [self.take(self.take(1)[0]) for _ in range(1 if tag == "f" else 2)]
            return Node(tag, parts)
        if tag in "stu":
            node = Node(tag, self.take(self.i32()))
            if tag == "u":
                node.value.decode("utf-8", errors="strict")
            if tag == "t":
                self.interned.append(node)
            return node
        if tag == "R":
            index = self.i32()
            if not 0 <= index < len(self.interned):
                raise ValueError("Bad marshal interned reference")
            return Node(tag, (index, self.interned[index]))
        if tag in "([<>":
            n = self.i32()
            if n < 0 or n > len(self.data) - self.pos:
                raise ValueError("Invalid marshal sequence length")
            return Node(tag, [self.node(depth+1) for _ in range(n)])
        if tag == "{":
            values = []
            while True:
                key = self.node(depth+1)
                if key.tag == "0":
                    break
                values.append((key, self.node(depth+1)))
            return Node(tag, values)
        if tag == "c":
            value = dict(zip(("argcount", "nlocals", "stacksize", "flags"), [self.i32() for _ in range(4)]))
            value.update({name: self.node(depth+1) for name in FIELDS})
            value["firstlineno"] = self.i32()
            value["lnotab"] = self.node(depth+1)
            return Node(tag, value)
        raise ValueError(f"Unsupported marshal type {tag!r} at {self.pos-1}")


def loads(data):
    reader = Reader(data)
    result = reader.node()
    if reader.pos != len(data):
        raise ValueError("Trailing marshal bytes")
    return result


def dumps(node):
    tag, value = node.tag, node.value
    prefix = tag.encode("ascii")
    i32 = lambda v: struct.pack("<i", v)
    if tag in "0NFTS.":
        return prefix
    if tag == "i":
        return prefix + i32(value)
    if tag == "I":
        return prefix + struct.pack("<q", value)
    if tag == "l":
        return prefix + i32(value[0]) + value[1]
    if tag in "gy":
        return prefix + value
    if tag in "fx":
        return prefix + b"".join(bytes([len(v)]) + v for v in value)
    if tag in "stu":
        return prefix + i32(len(value)) + value
    if tag == "R":
        return prefix + i32(value[0])
    if tag in "([<>":
        return prefix + i32(len(value)) + b"".join(dumps(v) for v in value)
    if tag == "{":
        return prefix + b"".join(dumps(k) + dumps(v) for k,v in value) + b"0"
    if tag == "c":
        return (prefix + b"".join(i32(value[k]) for k in ("argcount", "nlocals", "stacksize", "flags"))
                + b"".join(dumps(value[k]) for k in FIELDS) + i32(value["firstlineno"]) + dumps(value["lnotab"]))
    raise ValueError(f"Unsupported marshal tag {tag}")


def scalar(node):
    tag, v = node.tag, node.value
    if tag == "R":
        return scalar(v[1])
    if tag in "st":
        return v.decode("utf-8", errors="strict")
    if tag == "u":
        return v.decode("utf-8")
    if tag in "iI":
        return v
    if tag == "l":
        n = sum(struct.unpack_from("<H", v[1], k*2)[0] << (15*k) for k in range(abs(v[0])))
        return -n if v[0] < 0 else n
    if tag == "g":
        return struct.unpack("<d", v)[0]
    if tag == "f":
        return float(v[0])
    if tag == "N":
        return None
    if tag in "FT":
        return tag == "T"
    if tag in "([":
        return [scalar(n) for n in v]
    raise ValueError(f"Not a supported scalar: {tag}")


def literal(value):
    if value is None:
        return Node("N")
    if type(value) is bool:
        return Node("T" if value else "F")
    if type(value) is int and -(2**31) <= value < 2**31:
        return Node("i", value)
    if type(value) is float:
        return Node("g", struct.pack("<d", value))
    if type(value) is str:
        return Node("u", value.encode("utf-8"))
    raise ValueError("Only explicit scalar literals supported")
