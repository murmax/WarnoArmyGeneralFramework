"""Fixture-free checks for the independently implemented public byte reader."""

import struct
import unittest

from warno_ag.archives import read_directory
from warno_ag.binary_codec import ValueCursor, parse_cndf_value
from warno_ag.cndf import encode_value


class PublicCodecTests(unittest.TestCase):
    def test_cndf_values_round_trip_without_third_party_reader(self):
        cases = [
            {"type_id": 2, "reference_prefix": False, "value": -19},
            {"type_id": 0x1A, "reference_prefix": False,
             "value_hex": "0123456789abcdef" * 2},
            {"type_id": 7, "reference_prefix": True, "index": 0, "value": "sample"},
            {"type_id": 0x11, "reference_prefix": False, "length": 2, "items": [
                {"type_id": 0, "reference_prefix": False, "value": True},
                {"type_id": 0xBBBBBBBB, "reference_prefix": True,
                 "object_id": 3, "class_id": 4},
            ]},
        ]
        for value in cases:
            with self.subTest(type_id=value["type_id"]):
                encoded = encode_value(value)
                cursor = ValueCursor(encoded)
                decoded = parse_cndf_value(cursor, ["sample"], [], 20)
                self.assertEqual(cursor.pos, len(encoded))
                self.assertEqual(encode_value(decoded), encoded)

    def test_legacy_edat_tree_uses_own_bounded_reader(self):
        payload = b"ABC"
        name = b"a.bin\0"
        record = struct.pack("<IIII", 0, 0, 0, len(payload)) + b"\0" + name + b"\0"
        data = bytearray(128 + len(payload))
        data[:4] = b"edat"
        struct.pack_into("<I", data, 4, 1)
        struct.pack_into("<I", data, 25, 65)
        struct.pack_into("<I", data, 29, len(record))
        struct.pack_into("<I", data, 33, 128)
        struct.pack_into("<I", data, 37, len(payload))
        struct.pack_into("<I", data, 45, 1)
        data[65:65 + len(record)] = record
        data[128:] = payload
        header, entries, _ = read_directory(bytes(data))
        self.assertEqual(header.version, 1)
        self.assertEqual([(entry.path, entry.offset, entry.size) for entry in entries],
                         [("a.bin", 0, 3)])
        broken = bytearray(data)
        broken[65 + 17 + len(name) - 1] = ord("X")
        broken[65 + len(record) - 1] = ord("X")
        with self.assertRaises(ValueError):
            read_directory(bytes(broken))


if __name__ == "__main__":
    unittest.main()
