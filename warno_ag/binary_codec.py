"""Small EDAT/CNDF readers for the public authoring toolchain.

This module implements the byte layouts used by the framework directly. It
contains no game resources and has no dependency on third-party unpackers.
The higher-level readers in :mod:`archives` and :mod:`cndf` enforce additional
checks before a decoded resource can be used to build a campaign.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from pathlib import Path


class ParseError(ValueError):
    """A binary record is truncated or has an unsupported layout."""


@dataclass(frozen=True)
class EdatHeader:
    version: int
    dict_offset: int
    dict_length: int
    file_offset: int
    file_length: int
    padding: int


@dataclass(frozen=True)
class EdatEntry:
    id: int
    path: str
    offset: int
    size: int
    checksum_offset: int | None = None
    offset_field_offset: int | None = None
    size_field_offset: int | None = None


@dataclass(frozen=True)
class CndfHeader:
    version: int
    compression_mode: int
    footer_offset: int
    header_size: int
    full_size: int


@dataclass(frozen=True)
class CndfSection:
    name: str
    offset: int
    size: int


@dataclass(frozen=True)
class CndfFile:
    source: Path
    raw_data: bytes
    full_data: bytes
    header: CndfHeader
    body_uncompressed_size: int | None
    compressed: bool
    sections: list[CndfSection]


def _unpack(fmt: str, data: bytes, offset: int):
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise ParseError("Truncated binary field")
    return struct.unpack_from(fmt, data, offset)


def parse_edat_header(data: bytes) -> EdatHeader:
    """Read the fixed legacy archive header; range checks follow in archives."""
    if len(data) < 65 or data[:4] != b"edat":
        raise ParseError("Not a complete EDAT header")
    return EdatHeader(
        _unpack("<I", data, 4)[0],
        _unpack("<I", data, 25)[0],
        _unpack("<I", data, 29)[0],
        _unpack("<I", data, 33)[0],
        _unpack("<I", data, 37)[0],
        _unpack("<I", data, 45)[0],
    )


def parse_edat_entries(data: bytes, header: EdatHeader) -> list[EdatEntry]:
    """Read the version-one directory tree used by legacy research inputs.

    Current v2/v3 dictionaries have stricter readers in ``archives.py``.
    """
    if header.version != 1:
        raise ParseError("Legacy tree reader only accepts EDAT v1")
    end = header.dict_offset + header.dict_length
    if header.dict_offset < 65 or end > len(data):
        raise ParseError("EDAT directory outside archive")
    cursor = header.dict_offset
    prefixes: list[str] = []
    boundaries: list[int] = []
    entries: list[EdatEntry] = []
    while cursor < end:
        start = cursor
        limit = boundaries[-1] if boundaries else end
        marker, record_size = _unpack("<II", data, cursor)
        cursor += 8
        if marker == 0:
            offset_field = cursor
            relative, length = _unpack("<II", data, cursor)
            cursor += 8
            size_field = offset_field + 4
            if cursor >= limit:
                raise ParseError("Truncated EDAT v1 file record")
            cursor += 1  # legacy file record marker
        else:
            relative = length = offset_field = size_field = None
        name_end = data.find(b"\0", cursor, limit)
        if name_end < 0:
            raise ParseError("Unterminated EDAT v1 name")
        name = data[cursor:name_end].decode("latin1")
        cursor = name_end + 1
        if marker == 0:
            if (len(name) + 1) % 2 == 0:
                cursor += 1
            if cursor > limit:
                raise ParseError("File record crossed directory boundary")
            entries.append(EdatEntry(len(entries), "".join(prefixes) + name,
                                     relative, length, None, offset_field, size_field))
        else:
            if (len(name) + 1) % 2:
                cursor += 1
            if cursor > limit:
                raise ParseError("Directory record crossed parent boundary")
            child_end = start + record_size if record_size else limit
            if child_end < cursor or child_end > limit:
                raise ParseError("Invalid EDAT v1 directory length")
            prefixes.append(name)
            boundaries.append(child_end)
        while boundaries and cursor == boundaries[-1]:
            boundaries.pop()
            prefixes.pop()
        if boundaries and cursor > boundaries[-1]:
            raise ParseError("EDAT v1 directory overrun")
    if cursor != end or boundaries:
        raise ParseError("Incomplete EDAT v1 directory")
    return entries


def parse_cndf_header(data: bytes) -> CndfHeader:
    if len(data) < 40 or data[:4] != b"EUG0" or data[8:12] != b"CNDF":
        raise ParseError("Not a CNDF header")
    version, mode = _unpack("<II", data, 4)[0], _unpack("<I", data, 12)[0]
    footer, header_size, full_size = _unpack("<QQQ", data, 16)
    return CndfHeader(version, mode, footer, header_size, full_size)


def parse_cndf_sections(full: bytes, footer: int) -> list[CndfSection]:
    if footer < 0 or footer + 8 > len(full) or full[footer:footer + 4] != b"TOC0":
        raise ParseError("CNDF footer is absent")
    count = _unpack("<I", full, footer + 4)[0]
    if count > (len(full) - footer - 8) // 24:
        raise ParseError("Truncated CNDF section table")
    sections = []
    for number in range(count):
        at = footer + 8 + number * 24
        try:
            name = full[at:at + 8].split(b"\0", 1)[0].decode("ascii")
        except UnicodeDecodeError as exc:
            raise ParseError("Invalid CNDF section name") from exc
        offset, size = _unpack("<QQ", full, at + 8)
        if offset > len(full) or size > len(full) - offset:
            raise ParseError("CNDF section exceeds file bounds")
        sections.append(CndfSection(name, offset, size))
    return sections


def section_map(sections: list[CndfSection]) -> dict[str, CndfSection]:
    return {item.name: item for item in sections}


def read_len_prefixed_strings(data: bytes, section: CndfSection) -> list[str]:
    cursor = section.offset
    end = cursor + section.size
    if cursor < 0 or end > len(data):
        raise ParseError("String table outside file")
    values = []
    while cursor < end:
        if cursor + 4 > end:
            raise ParseError("Truncated string length")
        length = _unpack("<I", data, cursor)[0]
        cursor += 4
        if length > end - cursor:
            raise ParseError("String crosses section boundary")
        values.append(data[cursor:cursor + length].decode("latin1"))
        cursor += length
    return values


def parse_classes(data: bytes, sections: dict[str, CndfSection]) -> list[str]:
    item = sections.get("CLAS")
    return read_len_prefixed_strings(data, item) if item else []


def parse_properties(data: bytes, sections: dict[str, CndfSection],
                     classes: list[str]) -> list[dict]:
    item = sections.get("PROP")
    if item is None:
        return []
    cursor, end = item.offset, item.offset + item.size
    result = []
    while cursor < end:
        if cursor + 4 > end:
            raise ParseError("Truncated property name length")
        length = _unpack("<I", data, cursor)[0]
        cursor += 4
        if length + 4 > end - cursor:
            raise ParseError("Property record exceeds section")
        name = data[cursor:cursor + length].decode("latin1")
        cursor += length
        owner = _unpack("<I", data, cursor)[0]
        cursor += 4
        result.append({"id": len(result), "name": name,
                       "class_id": owner,
                       "class": classes[owner] if owner < len(classes) else f"#{owner}"})
    return result


def parse_u32_list(data: bytes, section: CndfSection | None) -> list[int]:
    if section is None:
        return []
    if section.size % 4 or section.offset < 0 or section.offset + section.size > len(data):
        raise ParseError("Invalid integer section")
    return list(struct.unpack_from(f"<{section.size // 4}I", data, section.offset))


def parse_chunk_count(data: bytes, section: CndfSection | None) -> int:
    if section is None:
        return 0
    if section.size >= 8:
        return _unpack("<I", data, section.offset + 4)[0]
    return section.size // 4


@dataclass
class ValueCursor:
    data: bytes
    pos: int = 0

    def read_bytes(self, count: int) -> bytes:
        if count < 0 or count > len(self.data) - self.pos:
            raise ParseError("Truncated CNDF value")
        result = self.data[self.pos:self.pos + count]
        self.pos += count
        return result

    def read_format(self, fmt: str):
        raw = self.read_bytes(struct.calcsize(fmt))
        return struct.unpack(fmt, raw)[0]

    def read_u32(self) -> int:
        return self.read_format("<I")


OBJECT_END_MARKER = 0xABABABAB
OBJECT_REFERENCE = 0xBBBBBBBB
TRANS_REFERENCE = 0xAAAAAAAA

_VALUE_NAMES = {
    0: "bool", 1: "int8", 2: "int32", 3: "uint32", 4: "time64",
    5: "float32", 6: "float64", 7: "strg_ref", 8: "wide_string",
    0x0B: "vec3", 0x0C: "color128", 0x0D: "color32", 0x0E: "int3",
    0x11: "list", 0x12: "map_list", 0x13: "int64", 0x14: "blob",
    0x18: "int16", 0x19: "uint16", 0x1A: "guid", 0x1C: "file_strg_ref",
    0x1D: "loc_hash", 0x1E: "zip_blob", 0x1F: "int2", 0x21: "float2",
    0x22: "map", 0x25: "hash16", OBJECT_REFERENCE: "obj_ref",
    TRANS_REFERENCE: "trans_ref",
}

_SCALAR_FORMATS = {
    0: "<?", 1: "<b", 2: "<i", 3: "<I", 4: "<Q", 5: "<f",
    6: "<d", 0x13: "<q", 0x18: "<h", 0x19: "<H",
}
_TUPLE_FORMATS = {0x0B: "<3f", 0x0E: "<3i", 0x1F: "<2i", 0x21: "<2f"}
_HEX_LENGTHS = {0x0C: 16, 0x1A: 16, 0x1D: 8, 0x25: 16}


def parse_cndf_value(cursor: ValueCursor, strings: list[str], trans: list[str],
                     max_depth: int, depth: int = 0) -> dict:
    if depth > max_depth:
        raise ParseError("CNDF value nesting exceeds limit")
    kind = cursor.read_u32()
    prefixed = kind == 9
    if prefixed:
        kind = cursor.read_u32()
    if kind not in _VALUE_NAMES:
        raise ParseError(f"Unsupported CNDF value type {kind:#x}")
    result = {"type_id": kind, "type": _VALUE_NAMES[kind],
              "reference_prefix": prefixed}
    child = lambda: parse_cndf_value(cursor, strings, trans, max_depth, depth + 1)
    if kind in (0x11, 0x12):
        length = cursor.read_u32()
        if length > (len(cursor.data) - cursor.pos) // 4:
            raise ParseError("CNDF collection length exceeds available data")
        result["length"] = length
        result["items"] = ([child() for _ in range(length)] if kind == 0x11 else
                           [{"key": child(), "value": child()} for _ in range(length)])
    elif kind == 0x22:
        result.update(key=child(), value=child())
    elif kind in (0x14, 0x1E):
        length = cursor.read_u32()
        if kind == 0x1E:
            result["zip_marker"] = cursor.read_format("<B")
        blob = cursor.read_bytes(length)
        result.update(length=length,
                      preview_hex=(blob.hex() if length <= 48 else
                                   blob[:48].hex() + f"...(+{length - 48} bytes)"))
    elif kind == 8:
        length = cursor.read_u32()
        result.update(length=length,
                      value=cursor.read_bytes(length).decode("utf-16le", errors="replace"))
    elif kind in _SCALAR_FORMATS:
        result["value"] = cursor.read_format(_SCALAR_FORMATS[kind])
    elif kind in _TUPLE_FORMATS:
        fmt = _TUPLE_FORMATS[kind]
        result["value"] = list(struct.unpack(fmt, cursor.read_bytes(struct.calcsize(fmt))))
    elif kind in _HEX_LENGTHS:
        result["value_hex"] = cursor.read_bytes(_HEX_LENGTHS[kind]).hex()
    elif kind == 0x0D:
        result["value"] = dict(zip("rgba", cursor.read_bytes(4)))
    elif kind in (7, 0x1C, TRANS_REFERENCE):
        index = cursor.read_u32()
        table = trans if kind == TRANS_REFERENCE else strings
        result.update(index=index, value=table[index] if index < len(table) else None)
    elif kind == OBJECT_REFERENCE:
        result.update(object_id=cursor.read_u32(), class_id=cursor.read_u32())
    return result
