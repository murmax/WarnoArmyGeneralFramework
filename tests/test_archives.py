from pathlib import Path
import struct
import unittest
import zlib
from warno_ag import archives
import hashlib

PACK = Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC\197351\201602\Scenarios\CampagneStrat_Bruderkrieg_Assets.dat')
DEFINITION = Path(r'C:\Program Files (x86)\Steam\steamapps\common\WARNO\Data\PC\201602\Scenarios\CampagneStrat_Bruderkrieg_Definition.dat')


@unittest.skipUnless(PACK.exists(), 'Local EDAT v3 fixture required')
class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.raw = PACK.read_bytes()
        self.header,self.entries,_ = archives.read_directory(self.raw)

    def payloads(self,raw):
        h,entries,_=archives.read_directory(raw)
        return {e.path:raw[h.file_offset+e.offset:h.file_offset+e.offset+e.size] for e in entries}

    def test_empty_repack_preserves_every_byte(self):
        self.assertEqual(archives.repack_v3(self.raw,{}),self.raw)

    def test_constructed_v3_is_deterministic_and_self_contained(self):
        payloads={'out/CommandZone.ndfbin':b'zone','Items.sav':b'items'}
        first=archives.pack_v3(payloads)
        self.assertEqual(archives.pack_v3(dict(reversed(list(payloads.items())))),first)
        self.assertEqual(self.payloads(first),payloads)
        damaged=bytearray(first); damaged[-8192]^=1
        with self.assertRaisesRegex(ValueError,'CRC32'):
            archives.repack_v3(bytes(damaged),{})

    def test_shortened_checksummed_dictionary_rejected(self):
        for trim in (1,2,4,8):
            with self.subTest(trim=trim):
                raw=bytearray(self.raw)
                size=self.header.dict_length-trim
                struct.pack_into('<I',raw,12,size)
                struct.pack_into('<I',raw,32,zlib.crc32(raw[self.header.dict_offset:self.header.dict_offset+size]))
                with self.assertRaises(ValueError): archives.read_directory(raw)

    def test_resized_repack_preserves_other_resources_and_checksums(self):
        before=self.payloads(self.raw)
        first=self.entries[0].path
        replacement=b'new independently checked resource payload'*1500
        result=archives.repack_v3(self.raw,{first:replacement})
        after=self.payloads(result)
        self.assertEqual(after[first],replacement)
        self.assertEqual({k:v for k,v in after.items() if k!=first},{k:v for k,v in before.items() if k!=first})
        h,entries,d=archives.read_directory(result)
        self.assertEqual(struct.unpack_from('<I',result,32)[0],zlib.crc32(d))
        for e in entries:
            self.assertEqual(struct.unpack_from('<I',result,e.checksum_offset)[0],zlib.crc32(after[e.path]))

    def test_unknown_resource_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError,'Unknown'):
            archives.repack_v3(self.raw,{'missing.xyz':b'x'})

    def test_corrupt_input_payload_is_rejected_even_for_noop(self):
        raw=bytearray(self.raw)
        raw[self.header.file_offset+self.entries[0].offset]^=1
        with self.assertRaisesRegex(ValueError,'CRC32'):
            archives.repack_v3(bytes(raw),{})

    @unittest.skipUnless(DEFINITION.exists(), 'Local campaign Definition required')
    def test_clone_preserves_engine_dictionary_layout_and_rejects_resizing(self):
        raw = DEFINITION.read_bytes()
        header, entries, dictionary = archives.read_directory(raw)
        old, new = 'CampagneStrat_Bruderkrieg', 'CampagneStrat_AGFramework'
        renames = {e.path:e.path.replace(old,new) for e in entries}
        result = archives.clone_v3(raw, {}, renames)
        changed_header, changed_entries, changed_dictionary = archives.read_directory(result)
        self.assertEqual(changed_header.file_offset, header.file_offset)
        self.assertEqual(changed_header.dict_length, header.dict_length)
        self.assertEqual(changed_dictionary, dictionary.replace(old.encode(), new.encode()))
        self.assertEqual(result[header.file_offset:], raw[header.file_offset:])
        self.assertEqual({e.path for e in changed_entries}, set(renames.values()))
        bad = dict(renames)
        bad[entries[0].path] += 'X'
        with self.assertRaisesRegex(ValueError, 'equal-length'):
            archives.clone_v3(raw, {}, bad)


if __name__=='__main__':unittest.main()


class ArchiveV2Tests(unittest.TestCase):
    def fixture(self):
        payloads={'a.bin':b'abc','b.bin':b'other'}
        records=[]
        offset=0
        for name,payload in payloads.items():
            records.append(struct.pack('<IIQQ',0,0,offset,len(payload))+hashlib.md5(payload).digest()+name.encode()+b'\0')
            offset+=len(payload)
        dictionary=b''.join(records); file_offset=256
        raw=bytearray(file_offset+offset);raw[:4]=b'edat';struct.pack_into('<I',raw,4,2)
        struct.pack_into('<IIII',raw,25,65,len(dictionary),file_offset,offset);struct.pack_into('<I',raw,45,1)
        raw[49:65]=hashlib.md5(dictionary).digest();raw[65:65+len(dictionary)]=dictionary
        cursor=file_offset
        for payload in payloads.values():raw[cursor:cursor+len(payload)]=payload;cursor+=len(payload)
        return bytes(raw),payloads

    def test_v2_resized_repack_checks_every_payload_and_dictionary(self):
        raw,payloads=self.fixture()
        self.assertEqual(archives.repack_v2(raw,{}),raw)
        result=archives.repack_v2(raw,{'a.bin':b'long replacement'})
        header,entries,dictionary=archives.read_directory(result)
        actual={e.path:result[header.file_offset+e.offset:header.file_offset+e.offset+e.size] for e in entries}
        self.assertEqual(actual,{'a.bin':b'long replacement','b.bin':payloads['b.bin']})
        self.assertEqual(result[49:65],hashlib.md5(dictionary).digest())
        self.assertEqual(struct.unpack_from('<I',result,37)[0],len(result)-header.file_offset)

    def test_v2_corruption_unknown_resource_and_wrong_version_rejected(self):
        raw,_=self.fixture(); header,entries,_=archives.read_directory(raw)
        corrupt=bytearray(raw);corrupt[header.file_offset+entries[0].offset]^=1
        with self.assertRaisesRegex(ValueError,'MD5'):archives.repack_v2(bytes(corrupt),{})
        with self.assertRaisesRegex(ValueError,'Unknown'):archives.repack_v2(raw,{'missing':b'x'})
        with self.assertRaises(ValueError):archives.repack_v3(raw,{})
        for changed_length in (header.file_length-1,header.file_length+1):
            malformed=bytearray(raw);struct.pack_into('<I',malformed,37,changed_length)
            with self.subTest(length=changed_length),self.assertRaisesRegex(ValueError,'ranges'):
                archives.read_directory(malformed)
