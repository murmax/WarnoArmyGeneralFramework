"""Version-aware CNDF decoding; never silently accepts a partial object graph."""
from pathlib import Path
import struct
import zlib
import zstandard
import lz4.block
from . import binary_codec as ndf
from .archives import read_directory, repack_v3
from .storage import safe_child, write_json, sha256


def path_tree(full, section, segments):
    if section is None or not section.size:
        return {}
    data = full[section.offset:section.offset + section.size]
    result, occupied = {}, set()
    def visit(offset, prefix, depth=0):
        if depth > 100 or offset < 0 or offset + 12 > len(data):
            raise ValueError("Invalid CNDF path tree")
        segment, index, count = struct.unpack_from("<III", data, offset)
        end = offset + 12 + count*4
        if segment >= len(segments) or end > len(data):
            raise ValueError("Invalid CNDF path tree node")
        positions = set(range(offset,end))
        if positions & occupied:
            raise ValueError("Overlapping/cyclic CNDF path tree")
        occupied.update(positions)
        path = prefix + [segments[segment]]
        if index != 0xFFFFFFFF:
            if index in result:
                raise ValueError("Duplicate CNDF path target")
            result[index] = "/".join(path)
        for i in range(count):
            child = offset + 12 + struct.unpack_from("<I",data,offset+12+4*i)[0]
            visit(child,path,depth+1)
    visit(0,[])
    if len(occupied) != len(data):
        raise ValueError("Unvisited CNDF path tree bytes")
    return result


def decode(raw, source="<memory>"):
    if len(raw) < 44:
        raise ValueError("Truncated CNDF header")
    h = ndf.parse_cndf_header(raw)
    if h.version != 1 or h.header_size != 40 or h.full_size > 256 * 1024 * 1024:
        raise ValueError("Unsupported CNDF header")
    if h.compression_mode in (1, 2, 3, 128):
        size = struct.unpack_from("<I", raw, 40)[0]
        if size + 40 != h.full_size or size > 256*1024*1024:
            raise ValueError("CNDF compressed size mismatch")
        if h.compression_mode == 2:
            if zstandard.frame_content_size(raw[44:]) != size:
                raise ValueError("CNDF/zstd size mismatch")
            body = zstandard.ZstdDecompressor(max_window_size=256 * 1024).decompress(
                raw[44:], max_output_size=size, allow_extra_data=False)
        elif h.compression_mode == 1:
            try:
                body = lz4.block.decompress(raw[44:], uncompressed_size=size)
            except lz4.block.LZ4BlockError as exc:
                raise ValueError("Invalid CNDF/LZ4 block") from exc
            if len(body) != size:
                raise ValueError("CNDF/LZ4 size mismatch")
        else:
            stream = zlib.decompressobj()
            try:
                body = stream.decompress(raw[44:], size + 1)
            except zlib.error as exc:
                raise ValueError("Invalid CNDF/zlib stream") from exc
            if (len(body) != size or not stream.eof or stream.unused_data
                    or stream.unconsumed_tail):
                raise ValueError("CNDF/zlib size or trailing data mismatch")
        full = raw[:40] + body
        compressed = True
    else:
        raise ValueError("Unsupported CNDF compression mode; legacy guessing is disabled")
    if len(full) != h.full_size:
        raise ValueError("CNDF full size mismatch")
    sections = ndf.parse_cndf_sections(full, h.footer_offset)
    if h.footer_offset + 8 + 24*len(sections) != len(full):
        raise ValueError("Trailing CNDF footer bytes")
    if len({s.name for s in sections}) != len(sections):
        raise ValueError("Duplicate CNDF section")
    ordered = sorted(sections, key=lambda s: s.offset)
    for i, section in enumerate(ordered):
        if section.offset < h.header_size or section.offset + section.size > h.footer_offset:
            raise ValueError("CNDF section outside body")
        if i and ordered[i-1].offset + ordered[i-1].size > section.offset:
            raise ValueError("Overlapping CNDF sections")
    doc = ndf.CndfFile(Path(source), raw, full, h, size, compressed, sections)
    sec = ndf.section_map(sections)
    if not {"OBJE", "CHNK", "CLAS", "PROP"} <= set(sec):
        raise ValueError("Missing CNDF graph section")
    classes = ndf.parse_classes(full, sec)
    props = ndf.parse_properties(full, sec, classes)
    strings = ndf.read_len_prefixed_strings(full, sec["STRG"]) if "STRG" in sec else []
    trans = ndf.read_len_prefixed_strings(full, sec["TRAN"]) if "TRAN" in sec else []
    if any(p['class_id'] >= len(classes) for p in props):
        raise ValueError("Invalid CNDF property owner class")
    if sec['CHNK'].size != 8:
        raise ValueError("Unsupported CNDF CHNK layout")
    count = ndf.parse_chunk_count(full, sec['CHNK'])
    top = ndf.parse_u32_list(full, sec.get('TOPO'))
    if len(top) != len(set(top)) or any(i >= count for i in top):
        raise ValueError("Invalid CNDF top object index")
    top = set(top)
    obje = sec['OBJE']
    cur = ndf.ValueCursor(full[obje.offset:obje.offset+obje.size], 0)
    parsed = []
    try:
        for object_id in range(count):
            start = cur.pos + obje.offset
            class_id = cur.read_u32()
            if class_id >= len(classes):
                raise ValueError("Invalid CNDF object class")
            values, seen = [], set()
            while True:
                prop_id = cur.read_u32()
                if prop_id == ndf.OBJECT_END_MARKER:
                    break
                if prop_id >= len(props) or prop_id in seen:
                    raise ValueError("Invalid/duplicate CNDF object property")
                seen.add(prop_id)
                value = ndf.parse_cndf_value(cur, strings, trans, 100)
                values.append({'property_id':prop_id, 'property_name':props[prop_id]['name'], 'value':value})
            parsed.append({'id':object_id, 'offset':start, 'class_id':class_id,
                           'class':classes[class_id], 'is_top_object':object_id in top, 'properties':values})
    except ndf.ParseError as e:
        raise ValueError(f"Invalid CNDF object section: {e}") from e
    if cur.pos != len(cur.data):
        raise ValueError("Unconsumed CNDF object section bytes")
    objects = {'objects':parsed, 'objects_parsed':len(parsed)}
    imports = path_tree(full, sec.get("IMPR"), trans)
    exports = path_tree(full, sec.get("EXPR"), trans)
    if any(i >= count for i in exports):
        raise ValueError("Invalid CNDF export object index")
    def resolve(value):
        if isinstance(value,dict):
            if value.get('type_id') in (7, 0x1c) and value['index'] >= len(strings):
                raise ValueError("Invalid CNDF string table reference")
            if value.get("type_id") == ndf.TRANS_REFERENCE:
                if value["index"] not in imports:
                    raise ValueError("Unresolved CNDF import index")
                value["value"] = imports[value["index"]]
            if value.get("type_id") == ndf.OBJECT_REFERENCE:
                index = value["object_id"]
                if index == 0xffffffff and value["class_id"] == 0xffffffff:
                    return
                if index >= len(objects["objects"]) or objects["objects"][index]["class_id"] != value["class_id"]:
                    raise ValueError("Unresolved CNDF object/class reference")
            for v in value.values(): resolve(v)
        elif isinstance(value,list):
            for v in value: resolve(v)
    resolve(objects["objects"])
    return doc, {"source": str(source), "sha256": sha256(raw), "classes": classes,
                 "properties": props, "strings": strings, "translations": trans,
                 "imports": imports, "exports": exports,
                 "objects": objects["objects"], "object_count": objects["objects_parsed"]}


def encode_value(v):
    t = v["type_id"]
    u32 = lambda x: struct.pack("<I",x)
    prefix = (u32(9) if v["reference_prefix"] else b"") + u32(t)
    scalar_formats = {0:"?",1:"b",2:"i",3:"I",4:"Q",5:"f",6:"d",0x13:"q",0x18:"h",0x19:"H"}
    if t in scalar_formats:
        return prefix + struct.pack("<"+scalar_formats[t],v["value"])
    if t in (7,0x1c,ndf.TRANS_REFERENCE):
        return prefix + u32(v["index"])
    if t == ndf.OBJECT_REFERENCE:
        return prefix + u32(v["object_id"]) + u32(v["class_id"])
    if t in (0x0c,0x1a,0x1d,0x25):
        return prefix + bytes.fromhex(v["value_hex"])
    if t in (0x1f,0x21,0x0b,0x0e):
        return prefix + struct.pack({0x1f:"<2i",0x21:"<2f",0x0b:"<3f",0x0e:"<3i"}[t],*v["value"])
    if t == 0x0d:
        return prefix + bytes(v["value"][k] for k in "rgba")
    if t == 0x08:
        data = v["value"].encode("utf-16le")
        return prefix + u32(len(data)) + data
    if t in (0x11,0x12):
        if len(v["items"]) != v["length"]:
            raise ValueError("NDF collection length mismatch")
        return prefix + u32(v["length"]) + b"".join(encode_value(x) if t==0x11 else encode_value(x["key"])+encode_value(x["value"]) for x in v["items"])
    if t == 0x22:
        return prefix + encode_value(v["key"]) + encode_value(v["value"])
    raise ValueError(f"No lossless writer for CNDF value type {t:#x}")


def encode_strings(values):
    output=bytearray()
    for value in values:
        if not isinstance(value,str): raise ValueError('CNDF string must be text')
        try: raw=value.encode('latin1')
        except UnicodeEncodeError as exc: raise ValueError('CNDF STRG text must be latin-1') from exc
        if len(raw)>16*1024*1024: raise ValueError('CNDF string is unreasonably large')
        output.extend(struct.pack('<I',len(raw)))
        output.extend(raw)
    return bytes(output)


def encode_objects(objects):
    output = bytearray()
    for expected,obj in enumerate(objects):
        if obj["id"] != expected:
            raise ValueError("NDF object numbering changed")
        output.extend(struct.pack("<I",obj["class_id"]))
        for prop in obj["properties"]:
            output.extend(struct.pack("<I",prop["property_id"]))
            output.extend(encode_value(prop["value"]))
        output.extend(struct.pack("<I",ndf.OBJECT_END_MARKER))
    return bytes(output)


def rebuild_objects(doc, decoded):
    """Replace a FULL reserialized OBJE section. Other sections remain opaque."""
    objects = encode_objects(decoded["objects"])
    original = next(s for s in doc.sections if s.name == "OBJE")
    if objects == doc.full_data[original.offset:original.offset+original.size]:
        return doc.raw_data
    return rebuild_sections(doc,{'OBJE':objects})


def empty_objects(doc):
    """Remove every object while retaining the verified CNDF schema tables."""
    if any(section.name not in {"OBJE", "TOPO", "CHNK", "CLAS", "PROP", "STRG", "TRAN", "IMPR", "EXPR"}
           for section in doc.sections):
        raise ValueError('Unsupported CNDF section in empty-object rewrite')
    chnk = struct.pack('<II', 0, 0)
    return rebuild_sections(doc, {'OBJE': b'', 'TOPO': b'', 'CHNK': chnk})


def append_graph_objects(doc, decoded, new_objects, new_classes=(), new_properties=()):
    """Append typed graph objects and extend CLAS/PROP/CHNK coherently.

    This is intentionally append-only: existing object/class/property indices
    and opaque sections never move semantically.  ``new_properties`` contains
    ``(name, class_name)`` pairs for classes in either the old or appended
    class table.  The full decoder validates the resulting graph.
    """
    if not isinstance(new_objects, list) or not new_objects:
        raise ValueError('At least one appended graph object is required')
    existing_classes = list(decoded['classes'])
    if len(set(new_classes)) != len(new_classes) or any(not isinstance(x, str) or not x for x in new_classes):
        raise ValueError('Invalid appended CNDF classes')
    if set(new_classes) & set(existing_classes):
        raise ValueError('Appended CNDF class already exists')
    classes = existing_classes + list(new_classes)
    class_ids = {name:index for index,name in enumerate(classes)}
    existing_props = {(x['name'], x['class']) for x in decoded['properties']}
    if len(set(new_properties)) != len(new_properties):
        raise ValueError('Duplicate appended CNDF property')
    for name, owner in new_properties:
        if not isinstance(name, str) or not name or owner not in class_ids or (name, owner) in existing_props:
            raise ValueError('Invalid appended CNDF property')
    objects = decoded['objects'] + list(new_objects)
    for index, obj in enumerate(objects):
        if obj.get('id') != index or obj.get('class') not in class_ids:
            raise ValueError('Invalid appended CNDF object identity')
        obj['class_id'] = class_ids[obj['class']]
    clas_section=next(s for s in doc.sections if s.name=='CLAS')
    clas=bytearray(doc.full_data[clas_section.offset:clas_section.offset+clas_section.size])
    for value in new_classes:
        raw=value.encode('latin1'); clas.extend(struct.pack('<I',len(raw))+raw)
    prop_section=next(s for s in doc.sections if s.name=='PROP')
    prop=bytearray(doc.full_data[prop_section.offset:prop_section.offset+prop_section.size])
    for name,owner in new_properties:
        raw=name.encode('latin1'); prop.extend(struct.pack('<I',len(raw))+raw+struct.pack('<I',class_ids[owner]))
    chnk_section=next(s for s in doc.sections if s.name=='CHNK')
    chnk=bytearray(doc.full_data[chnk_section.offset:chnk_section.offset+chnk_section.size])
    struct.pack_into('<I',chnk,4,len(objects))
    return rebuild_sections(doc, {'CLAS':bytes(clas), 'PROP':bytes(prop), 'CHNK':bytes(chnk),
                                  'OBJE':encode_objects(objects)})


def rebuild_sections(doc, replacements):
    if set(replacements)-{s.name for s in doc.sections}:
        raise ValueError('Unknown CNDF replacement section')
    full = bytearray(doc.full_data[:doc.header.header_size])
    toc=[]
    for section in doc.sections:
        data=replacements.get(section.name,doc.full_data[section.offset:section.offset+section.size])
        if not isinstance(data,bytes): raise ValueError('CNDF replacement section must be bytes')
        toc.append((section.name,len(full),len(data)))
        full.extend(data)
    footer=len(full)
    full.extend(b'TOC0'+struct.pack('<I',len(toc)))
    for name,offset,size in toc:
        full.extend(name.encode('ascii')[:8].ljust(8,b'\0')+struct.pack('<QQ',offset,size))
    struct.pack_into('<Q',full,16,footer)
    struct.pack_into('<Q',full,32,len(full))
    body=bytes(full[doc.header.header_size:])
    if doc.header.compression_mode == 2:
        packed=zstandard.ZstdCompressor().compress(body)
    elif doc.header.compression_mode == 1:
        packed=lz4.block.compress(body,store_size=False)
    elif doc.header.compression_mode == 3:
        packed=zlib.compress(body)
    else:
        raise ValueError('Writer supports explicit CNDF zstd(2), LZ4(1) and zlib(3) only')
    result=bytes(full[:doc.header.header_size])+struct.pack('<I',len(body))+packed
    # Independent full parser validates section ranges and the complete object graph.
    decode(result)
    return result


def inspect_pack(pack, output):
    raw = Path(pack).read_bytes()
    h, entries, _ = read_directory(raw)
    # Only the current, verified package format is accepted for native extraction.
    repack_v3(raw,{})
    report = []
    for entry in entries:
        if not entry.path.endswith(".ndfbin"):
            continue
        data = raw[h.file_offset + entry.offset:h.file_offset + entry.offset + entry.size]
        doc, decoded = decode(data, f"{pack}:{entry.path}")
        target = safe_child(output, entry.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        write_json(target.with_suffix(".json"), decoded)
        report.append({"path": entry.path, "objects": len(decoded["objects"]), "classes": len(decoded["classes"])})
    write_json(Path(output) / "manifest.json", report)
    return report
