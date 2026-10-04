"""Read-only EDAT index, preserving source and revision for every resource.

Payload and dictionary digests are checked independently here. Revision order
is an offline hypothesis, not a proven runtime loader contract.
"""
import hashlib
import mmap
import struct
import zlib
from collections import OrderedDict
from pathlib import Path
from . import binary_codec as edat
from .storage import write_json


def dictionary_v3(dictionary, base):
    """Strict current-format tree reader, bounded to checksummed bytes only."""
    cursor, dirs, endings, entries = 0, [], [], []
    while cursor < len(dictionary):
        start = cursor
        limit = endings[-1] if endings else len(dictionary)
        if cursor + 8 > limit:
            raise ValueError("Truncated EDAT dictionary record")
        group, length = struct.unpack_from('<II', dictionary, cursor)
        cursor += 8
        if group == 0:
            if cursor + 32 > limit:
                raise ValueError("Truncated EDAT file record")
            offset, size = struct.unpack_from('<QQ', dictionary, cursor)
            offset_field, size_field, checksum = base+cursor, base+cursor+8, base+cursor+16
            cursor += 32
        end_name = dictionary.find(b'\0', cursor, limit)
        if end_name < 0:
            raise ValueError("Unterminated EDAT dictionary name")
        name = dictionary[cursor:end_name].decode('latin1')
        cursor = end_name + 1
        if group:
            if group != cursor-start:
                raise ValueError("Invalid EDAT directory header length")
            end = start+length if length else limit
            if end < cursor or end > limit:
                raise ValueError("Invalid EDAT directory boundary")
            dirs.append(name)
            endings.append(end)
        else:
            end = start+length if length else cursor
            if end != cursor:
                raise ValueError("Unsupported EDAT file record padding")
            entries.append(edat.EdatEntry(len(entries), ''.join(dirs)+name, offset, size,
                                          checksum, offset_field, size_field))
        while endings and cursor == endings[-1]:
            dirs.pop()
            endings.pop()
    if cursor != len(dictionary) or endings:
        raise ValueError("Incomplete EDAT dictionary")
    return entries


def dictionary_v2(dictionary, base, alignment):
    cursor = 0
    directories, endings, entries = [], [], []
    while cursor < len(dictionary):
        limit = endings[-1] if endings else len(dictionary)
        start = cursor
        if cursor + 8 > limit:
            raise ValueError("Truncated EDAT v2 record")
        group, length = struct.unpack_from('<II', dictionary, cursor)
        cursor += 8
        if not group:
            if cursor + 32 > limit:
                raise ValueError("Truncated EDAT v2 file record")
            offset, size = struct.unpack_from('<QQ', dictionary, cursor)
            offset_field, size_field = base + cursor, base + cursor + 8
            checksum = base + cursor + 16
            cursor += 32
        end_name = dictionary.find(b'\0', cursor, limit)
        if end_name < 0:
            raise ValueError("Unterminated EDAT v2 name")
        name = dictionary[cursor:end_name].decode('latin1')
        cursor = end_name + 1
        padding = (-(cursor - start)) % alignment
        if cursor + padding > limit or dictionary[cursor:cursor + padding] != bytes(padding):
            raise ValueError("Invalid EDAT v2 record padding")
        cursor += padding
        if group:
            if group != cursor - start:
                raise ValueError("Invalid EDAT v2 directory header length")
            end = start + length if length else limit
            if end < cursor or end > limit:
                raise ValueError("Invalid EDAT v2 directory boundary")
            directories.append(name)
            endings.append(end)
        else:
            if length and start + length != cursor:
                raise ValueError("Invalid EDAT v2 file record length")
            path = ''.join(directories) + name
            if not path or any(ord(char) < 32 for char in path):
                raise ValueError("Invalid EDAT v2 resource name")
            entries.append(edat.EdatEntry(len(entries), path, offset, size,
                                          checksum, offset_field, size_field))
        while endings and cursor == endings[-1]:
            directories.pop()
            endings.pop()
    if cursor != len(dictionary) or endings:
        raise ValueError("Incomplete EDAT v2 dictionary")
    return entries


def read_directory(data):
    if data[:4] != b"edat" or len(data) < 36:
        raise ValueError("Not EDAT")
    version = struct.unpack_from("<I", data, 4)[0]
    if version == 3:
        dictionary_offset, dictionary_size, file_offset, file_size, checksum = struct.unpack_from("<IIQQI", data, 8)
        if dictionary_offset < 36 or dictionary_offset + dictionary_size > file_offset or file_offset + file_size != len(data):
            raise ValueError("Invalid EDAT v3 ranges")
        dictionary = data[dictionary_offset:dictionary_offset + dictionary_size]
        if zlib.crc32(dictionary) != checksum:
            raise ValueError("EDAT v3 dictionary CRC32 mismatch")
        header = edat.EdatHeader(version, dictionary_offset, dictionary_size, file_offset, file_size, 8192)
        # The nine-byte initial empty-directory record is a record, NOT an
        # extension of every directory. Skipping nine bytes at each level
        # silently drops prefixes such as GDScript/ and MapConfiguration/.
        entries = dictionary_v3(dictionary, dictionary_offset) if dictionary_size else []
        if any(not v.path or any(ord(ch) < 32 for ch in v.path)
               or file_offset + v.offset + v.size > len(data)
               or data[v.checksum_offset + 4:v.checksum_offset + 16] != bytes(12)
               for v in entries):
            raise ValueError("Unsupported EDAT v3 dictionary layout")
    elif version in (1, 2):
        # v2 has a uint64 payload length at offset 37, needed for large
        # installed texture archives.
        header = (edat.EdatHeader(version, *struct.unpack_from('<IIIQI', data, 25))
                  if version == 2 and len(data) >= 65 else edat.parse_edat_header(data))
        if (header.dict_offset < 65 or
                header.dict_offset + header.dict_length > header.file_offset or
                header.file_offset + header.file_length != len(data)):
            raise ValueError("Invalid legacy EDAT ranges")
        dictionary = data[header.dict_offset:header.dict_offset + header.dict_length]
        if version == 2 and hashlib.md5(dictionary).digest() != data[49:65]:
            raise ValueError("Dictionary MD5 mismatch")
        if version == 2 and header.dict_length:
            candidates = []
            for alignment in (1, 2):
                try:
                    parsed = dictionary_v2(dictionary, header.dict_offset, alignment)
                except ValueError:
                    continue
                if (len({entry.path for entry in parsed}) == len(parsed)
                        and all(entry.offset + entry.size <= header.file_length for entry in parsed)):
                    if parsed not in candidates:
                        candidates.append(parsed)
            if len(candidates) != 1:
                raise ValueError("Invalid or ambiguous EDAT v2 dictionary")
            entries = candidates[0]
        else:
            entries = edat.parse_edat_entries(data, header) if header.dict_length else []
    else:
        raise ValueError(f"Unsupported EDAT version {version}")
    names = set()
    for entry in entries:
        if entry.path in names or header.file_offset + entry.offset + entry.size > len(data):
            raise ValueError("EDAT duplicate name or out-of-bounds entry")
        names.add(entry.path)
    return header, entries, dictionary


def revision_key(path, data_root):
    return tuple(int(p) for p in path.relative_to(data_root).parts[:-1] if p.isdecimal())


def scan(game_root, output):
    data_root = Path(game_root).resolve() / "Data" / "PC"
    candidates = []
    for path in data_root.rglob("*.dat"):
        rel = path.relative_to(data_root)
        if "Maps" in rel.parts or "DecorsSets" in rel.parts:
            continue
        if "Scenarios" in rel.parts and not path.name.startswith("CampagneStrat_"):
            continue
        candidates.append(path)
    candidates.sort(key=lambda p: (revision_key(p, data_root), str(p)))
    resources, failures, packs = {}, [], []
    for number, path in enumerate(candidates, 1):
        try:
            with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                header, entries, dictionary = read_directory(data)
                if not header.dict_length:
                    continue
                selected = 0
                for entry in entries:
                    name = entry.path.replace("\\", "/")
                    if not name.lower().endswith(".xyz"):
                        continue
                    start = header.file_offset + entry.offset
                    if start < header.file_offset or start + entry.size > len(data):
                        raise ValueError(f"Entry out of bounds: {name}")
                    record = {
                        "pack": str(path), "revision": list(revision_key(path, data_root)),
                        "path": name, "offset": start, "size": entry.size,
                        "edat_version": header.version,
                        "checksum": (data[entry.checksum_offset:entry.checksum_offset + (4 if header.version == 3 else 16)].hex()
                                     if entry.checksum_offset is not None else None),
                    }
                    resources.setdefault(name, []).append(record)
                    selected += 1
                if selected:
                    packs.append({"path": str(path), "xyz_count": selected,
                                  "dictionary_sha256": hashlib.sha256(dictionary).hexdigest()})
        except Exception as exc:
            failures.append({"pack": str(path), "error": str(exc)})
        if number % 100 == 0:
            print(f"Indexed {number}/{len(candidates)} packs; {len(resources)} XYZ paths", flush=True)
    conflicts = []
    for name, layers in resources.items():
        latest = layers[-1]
        peers = [v for v in layers if v["revision"] == latest["revision"]]
        if len({(v["checksum"], v["size"]) for v in peers}) > 1:
            conflicts.append({"path": name, "sources": peers})
    result = {"schema": 1, "game_root": str(Path(game_root).resolve()),
              "precedence": "numeric revision tuple; inferred, runtime unverified",
              "scope": "global packs and Army General scenario packs; excludes Maps/DecorsSets",
              "pack_count": len(candidates), "packs_with_xyz": packs,
              "resources": resources, "errors": failures, "conflicts": conflicts}
    write_json(output, result)
    print(f"Index: {len(resources)} resources, {len(failures)} errors, {len(conflicts)} conflicts")
    return result


def read_entry(record):
    with Path(record["pack"]).open("rb") as stream:
        stream.seek(record["offset"])
        data = stream.read(record["size"])
    if len(data) != record["size"]:
        raise ValueError("Truncated archive payload")
    checksum = struct.pack("<I", zlib.crc32(data)).hex() if record["edat_version"] == 3 else hashlib.md5(data).hexdigest()
    if record["checksum"] and checksum != record["checksum"]:
        raise ValueError("Archive payload changed or checksum mismatch")
    return data


def repack_v3(raw, replacements):
    header,entries,_ = read_directory(raw)
    if header.version != 3:
        raise ValueError("Only EDAT v3 output supported")
    if set(replacements) - {e.path for e in entries}:
        raise ValueError("Unknown EDAT replacement resource")
    payloads = {}
    for entry in entries:
        start = header.file_offset + entry.offset
        value = raw[start:start+entry.size]
        if zlib.crc32(value) != struct.unpack_from("<I",raw,entry.checksum_offset)[0]:
            raise ValueError(f"Input payload CRC32 mismatch: {entry.path}")
        payloads[entry.path] = value
    if all(payloads[name] == data for name,data in replacements.items()):
        return raw
    prefix = bytearray(raw[:header.file_offset])
    body = bytearray()
    for entry in sorted(entries,key=lambda e:e.offset):
        data = replacements.get(entry.path,payloads[entry.path])
        if not isinstance(data,bytes):
            raise ValueError("EDAT replacement must be bytes")
        offset = len(body)
        body.extend(data)
        body.extend(bytes((-len(body)) % 8192))
        struct.pack_into("<Q",prefix,entry.offset_field_offset,offset)
        struct.pack_into("<Q",prefix,entry.size_field_offset,len(data))
        struct.pack_into("<I",prefix,entry.checksum_offset,zlib.crc32(data))
    struct.pack_into("<Q",prefix,24,len(body))
    dictionary = prefix[header.dict_offset:header.dict_offset+header.dict_length]
    struct.pack_into("<I",prefix,32,zlib.crc32(dictionary))
    result = bytes(prefix+body)
    h,check,_ = read_directory(result)
    if {e.path for e in check} != set(payloads):
        raise ValueError("EDAT resource set changed during repack")
    for e in check:
        value = result[h.file_offset+e.offset:h.file_offset+e.offset+e.size]
        if value != replacements.get(e.path,payloads[e.path]):
            raise ValueError("EDAT repack verification failed")
    return result


def _v3_dictionary(records):
    """Serialize a deterministic EDAT v3 path tree from (path, offset, data)."""
    root={'directories':OrderedDict(),'files':[]}
    for path,offset,data in records:
        if not isinstance(path,str) or not path or '\0' in path:
            raise ValueError('Invalid EDAT virtual path')
        parts=path.replace('\\','/').split('/')
        if any(not part or part in ('.','..') for part in parts):
            raise ValueError('Invalid EDAT virtual path')
        node=root
        for part in parts[:-1]:
            if any(name==part for name,_,_ in node['files']):
                raise ValueError('EDAT file/directory path collision')
            node=node['directories'].setdefault(part,{'directories':OrderedDict(),'files':[]})
        if parts[-1] in node['directories'] or any(name==parts[-1] for name,_,_ in node['files']):
            raise ValueError('Duplicate EDAT virtual path')
        node['files'].append((parts[-1],offset,data))
    def directory(name,node,root_record=False):
        children=bytearray()
        for child_name,child in node['directories'].items():
            children.extend(directory(child_name+'/',child))
        for filename,offset,data in node['files']:
            encoded=filename.encode('latin1')+b'\0'
            length=40+len(encoded)
            children.extend(struct.pack('<IIQQ',0,length,offset,len(data)))
            children.extend(struct.pack('<I',zlib.crc32(data))+bytes(12)+encoded)
        encoded=name.encode('latin1')+b'\0'
        group=8+len(encoded)
        length=0 if root_record else group+len(children)
        return struct.pack('<II',group,length)+encoded+children
    return bytes(directory('',root,True))


def pack_v3(payloads):
    """Build one self-contained current EDAT from verified resource payloads."""
    if (not isinstance(payloads,dict) or not payloads
            or any(not isinstance(name,str) or not isinstance(data,bytes)
                   for name,data in payloads.items())):
        raise ValueError('EDAT v3 payload map must contain named byte strings')
    normalized = {name.replace('\\', '/'): data for name, data in payloads.items()}
    if len(normalized) != len(payloads):
        raise ValueError('Duplicate normalized EDAT virtual path')
    payloads = normalized
    body=bytearray(); records=[]
    for name in sorted(payloads):
        data=payloads[name]; offset=len(body); records.append((name,offset,data))
        body.extend(data); body.extend(bytes((-len(body))%8192))
    dictionary=_v3_dictionary(records)
    dictionary_offset=256
    file_offset=(dictionary_offset+len(dictionary)+8191)&~8191
    prefix=bytearray(file_offset)
    prefix[:36]=b'edat'+struct.pack('<IIIQQI',3,dictionary_offset,len(dictionary),
                                    file_offset,len(body),zlib.crc32(dictionary))
    prefix[dictionary_offset:dictionary_offset+len(dictionary)]=dictionary
    result=bytes(prefix+body)
    header,entries,checked=read_directory(result)
    if (header.version!=3 or checked!=dictionary
            or {entry.path for entry in entries}!=set(payloads)):
        raise ValueError('EDAT v3 construction verification failed')
    for entry in entries:
        actual=result[header.file_offset+entry.offset:header.file_offset+entry.offset+entry.size]
        if actual!=payloads[entry.path]:
            raise ValueError('EDAT v3 constructed payload mismatch')
    return result


def clone_v3(raw,replacements,renames):
    """Clone v3 while preserving the engine-produced dictionary record layout."""
    header,entries,dictionary=read_directory(raw)
    if header.version!=3: raise ValueError('EDAT path cloning supports v3 only')
    names={e.path for e in entries}
    if set(replacements)-names or set(renames)-names:
        raise ValueError('Unknown EDAT clone resource')
    if not isinstance(renames,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in renames.items()):
        raise ValueError('EDAT renames must map paths to paths')
    payloads={}
    for entry in entries:
        start=header.file_offset+entry.offset
        data=raw[start:start+entry.size]
        if zlib.crc32(data)!=struct.unpack_from('<I',raw,entry.checksum_offset)[0]:
            raise ValueError(f'Input payload CRC32 mismatch: {entry.path}')
        payloads[entry.path]=data
    targets=[renames.get(e.path,e.path) for e in entries]
    if len(set(targets))!=len(targets) or len({v.casefold() for v in targets})!=len(targets):
        raise ValueError('EDAT clone path collision')
    token_renames={}
    for source,target in renames.items():
        before,after=source.replace('\\','/'),target.replace('\\','/')
        if len(before.encode('latin1'))!=len(after.encode('latin1')):
            raise ValueError('EDAT engine dictionary renames must be equal-length')
        prefix=0
        while prefix<len(before) and before[prefix]==after[prefix]: prefix+=1
        suffix=0
        while suffix<len(before)-prefix and before[-suffix-1]==after[-suffix-1]: suffix+=1
        old=before[prefix:len(before)-suffix if suffix else None]
        new=after[prefix:len(after)-suffix if suffix else None]
        if not old or not new or len(old.encode('latin1'))!=len(new.encode('latin1')):
            raise ValueError('Invalid EDAT path rename span')
        if old in token_renames and token_renames[old]!=new:
            raise ValueError('Inconsistent EDAT path token rename')
        token_renames[old]=new
    # Repack first so payload offsets, sizes and CRCs are changed in the original
    # dictionary records. Never synthesize records accepted only by our parser.
    result=bytearray(repack_v3(raw,replacements))
    rebuilt_header,_,rebuilt_dictionary=read_directory(result)
    if (rebuilt_header.dict_offset!=header.dict_offset or
            rebuilt_header.dict_length!=header.dict_length):
        raise ValueError('EDAT repack changed dictionary layout')
    changed=bytes(rebuilt_dictionary)
    for old,new in token_renames.items():
        needle,replacement=old.encode('latin1'),new.encode('latin1')
        count=changed.count(needle)
        if not count: raise ValueError('EDAT rename component missing from dictionary')
        changed=changed.replace(needle,replacement)
    start=header.dict_offset
    result[start:start+header.dict_length]=changed
    struct.pack_into('<I',result,32,zlib.crc32(changed))
    result=bytes(result)
    check_header,check_entries,check_dictionary=read_directory(result)
    if {e.path for e in check_entries}!=set(targets) or zlib.crc32(check_dictionary)!=struct.unpack_from('<I',result,32)[0]:
        raise ValueError('EDAT clone dictionary verification failed')
    expected={renames.get(entry.path,entry.path):replacements.get(entry.path,payloads[entry.path]) for entry in entries}
    for entry in check_entries:
        actual=result[check_header.file_offset+entry.offset:check_header.file_offset+entry.offset+entry.size]
        if actual!=expected[entry.path]: raise ValueError('EDAT clone payload verification failed')
    return result


def repack_v2(raw, replacements):
    """Rebuild a checksummed EDAT v2 in memory; preserve its virtual resource set."""
    header, entries, dictionary = read_directory(raw)
    if header.version != 2:
        raise ValueError("Only EDAT v2 output supported")
    if set(replacements) - {e.path for e in entries}:
        raise ValueError("Unknown EDAT replacement resource")
    payloads = {}
    for entry in entries:
        start = header.file_offset + entry.offset
        value = raw[start:start+entry.size]
        if hashlib.md5(value).digest() != raw[entry.checksum_offset:entry.checksum_offset+16]:
            raise ValueError(f"Input payload MD5 mismatch: {entry.path}")
        payloads[entry.path] = value
    if all(payloads[name] == data for name,data in replacements.items()):
        return raw
    prefix, body = bytearray(raw[:header.file_offset]), bytearray()
    alignment = header.padding if 0 < header.padding <= 1024*1024 and header.padding & (header.padding-1) == 0 else 1
    for entry in sorted(entries,key=lambda e:e.offset):
        data = replacements.get(entry.path,payloads[entry.path])
        if not isinstance(data,bytes):
            raise ValueError("EDAT replacement must be bytes")
        offset = len(body)
        body.extend(data)
        body.extend(bytes((-len(body)) % alignment))
        struct.pack_into('<Q',prefix,entry.offset_field_offset,offset)
        struct.pack_into('<Q',prefix,entry.size_field_offset,len(data))
        prefix[entry.checksum_offset:entry.checksum_offset+16] = hashlib.md5(data).digest()
    struct.pack_into('<Q',prefix,37,len(body))
    prefix[49:65] = hashlib.md5(prefix[header.dict_offset:header.dict_offset+header.dict_length]).digest()
    result = bytes(prefix+body)
    check_header, check_entries, check_dictionary = read_directory(result)
    if hashlib.md5(check_dictionary).digest() != result[49:65] or {e.path for e in check_entries} != set(payloads):
        raise ValueError("EDAT v2 dictionary/resource verification failed")
    for entry in check_entries:
        value = result[check_header.file_offset+entry.offset:check_header.file_offset+entry.offset+entry.size]
        if (value != replacements.get(entry.path,payloads[entry.path]) or
                hashlib.md5(value).digest() != result[entry.checksum_offset:entry.checksum_offset+16]):
            raise ValueError("EDAT v2 repack verification failed")
    return result


def repack(raw, replacements):
    version = struct.unpack_from('<I',raw,4)[0] if len(raw)>=8 and raw[:4]==b'edat' else None
    if version == 3:
        return repack_v3(raw,replacements)
    if version == 2:
        return repack_v2(raw,replacements)
    raise ValueError('Only checksummed EDAT v2/v3 output supported')
