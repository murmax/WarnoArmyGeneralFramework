from pathlib import Path
import copy
import struct
import unittest
import zlib
import zstandard
from warno_ag.cndf import append_graph_objects, decode, rebuild_objects

FIXTURE = Path(__file__).resolve().parents[1] / 'artifacts/definition/NDF/Scenarios/GDScript/CampagneStrat_Bruderkrieg.ndfbin'


@unittest.skipUnless(FIXTURE.exists(), 'Local CNDF fixture required')
class NativeValidationTests(unittest.TestCase):
    def setUp(self):
        self.doc, self.graph = decode(FIXTURE.read_bytes())
        self.full = bytearray(self.doc.full_data)
        self.sections = {s.name: s for s in self.doc.sections}

    def packed(self):
        return bytes(self.full[:40]) + struct.pack('<I', len(self.full)-40) + zstandard.ZstdCompressor().compress(self.full[40:])

    def test_invalid_class_and_property_ids_rejected(self):
        for offset in (40, 44):
            with self.subTest(offset=offset):
                self.full = bytearray(self.doc.full_data)
                struct.pack_into('<I', self.full, offset, 999999)
                with self.assertRaises(ValueError): decode(self.packed())

    def test_native_null_object_reference_requires_both_sentinels(self):
        from warno_ag.binary_codec import OBJECT_REFERENCE

        def references(value):
            if isinstance(value, dict):
                if value.get('type_id') == OBJECT_REFERENCE:
                    yield value
                for child in value.values():
                    yield from references(child)
            elif isinstance(value, list):
                for child in value:
                    yield from references(child)

        for object_id, class_id, valid in ((0xffffffff, 0xffffffff, True),
                                           (0xffffffff, 0, False), (0, 0xffffffff, False)):
            graph = copy.deepcopy(self.graph)
            reference = next(references(graph['objects']))
            reference.update(object_id=object_id, class_id=class_id)
            if valid:
                raw = rebuild_objects(self.doc, graph)
                _, decoded = decode(raw)
                self.assertEqual(next(references(decoded['objects'])), reference)
            else:
                with self.assertRaisesRegex(ValueError, 'object/class reference'):
                    rebuild_objects(self.doc, graph)

    def test_invalid_property_owner_rejected(self):
        offset = self.sections['PROP'].offset
        length = struct.unpack_from('<I', self.full, offset)[0]
        struct.pack_into('<I', self.full, offset+4+length, 999999)
        with self.assertRaises(ValueError): decode(self.packed())

    def test_invalid_top_object_rejected(self):
        struct.pack_into('<I', self.full, self.sections['TOPO'].offset, 999999)
        with self.assertRaises(ValueError): decode(self.packed())

    def test_shortened_object_section_rejected(self):
        offset = self.doc.header.footer_offset + 8 + 16
        struct.pack_into('<Q', self.full, offset, self.sections['OBJE'].size - 4)
        with self.assertRaises(ValueError): decode(self.packed())

    def test_unconsumed_object_bytes_rejected(self):
        struct.pack_into('<I', self.full, self.sections['CHNK'].offset+4, self.graph['object_count']-1)
        with self.assertRaises(ValueError): decode(self.packed())

    def test_unknown_compression_mode_rejected(self):
        struct.pack_into('<I', self.full, 12, 777)
        with self.assertRaises(ValueError): decode(bytes(self.full))

    def test_legacy_zlib_not_silently_guessed(self):
        struct.pack_into('<I', self.full, 12, 128)
        raw = bytes(self.full[:40]) + struct.pack('<I', len(self.full)-40) + zlib.compress(self.full[40:]) + b'junk'
        with self.assertRaises(ValueError): decode(raw)

    def test_explicit_mode3_zlib_roundtrip_preserves_graph_and_mode(self):
        struct.pack_into('<I', self.full, 12, 3)
        raw = bytes(self.full[:40]) + struct.pack('<I', len(self.full)-40) + zlib.compress(self.full[40:])
        document, graph = decode(raw)
        self.assertEqual(graph['objects'], self.graph['objects'])
        template = copy.deepcopy(next(obj for obj in graph['objects'] if obj['class'] == 'TGDVariableInteger'))
        template['id'] = len(graph['objects'])
        output = append_graph_objects(document, graph, [template])
        rebuilt, decoded = decode(output)
        self.assertEqual(rebuilt.header.compression_mode, 3)
        self.assertEqual(len(decoded['objects']), len(graph['objects']) + 1)
        for invalid in (raw + b'junk', raw[:-1], raw[:44] + b'not-zlib'):
            with self.assertRaises(ValueError):
                decode(invalid)

    def test_append_graph_object_preserves_old_ids_and_round_trips(self):
        template=copy.deepcopy(next(obj for obj in self.graph['objects']
                                    if obj['class']=='TGDVariableInteger'))
        template['id']=len(self.graph['objects'])
        value=next(prop for prop in template['properties'] if prop['property_name']=='Value')
        value['value']['value']=1989
        output=append_graph_objects(self.doc,self.graph,[template])
        _,graph=decode(output)
        self.assertEqual(len(graph['objects']),len(self.graph['objects'])+1)
        self.assertEqual(graph['objects'][:-1],self.graph['objects'])
        appended=graph['objects'][-1]
        self.assertEqual((appended['id'],appended['class']),
                         (len(self.graph['objects']),'TGDVariableInteger'))
        self.assertEqual(next(prop['value']['value'] for prop in appended['properties']
                              if prop['property_name']=='Value'),1989)
