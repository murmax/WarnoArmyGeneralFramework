"""Strict XYZ envelope reader. Changed envelopes remain research-only.

Legacy layout: signature, big-endian length, opaque16, zlib.
Current layout: signature, opaque16, little-endian length, zstd.
The opaque field is NOT a payload digest:
some F0/F1 modules have different payloads but the same value.
"""
from dataclasses import dataclass
import io
import struct
import zlib
import zstandard
from xdis.unmarshal import load_code

MAGIC_26 = 62161
MAX_PAYLOAD = 64 * 1024 * 1024


@dataclass(frozen=True)
class XYZ:
    raw: bytes
    payload: bytes
    compression: str

    @classmethod
    def read(cls, data):
        if len(data) < 30 or data[:8] != b"XYZ0\x0a\x0d\xf2\xb3":
            raise ValueError("Unsupported XYZ signature/version")
        compression = "zstd" if data[28:32] == b"\x28\xb5\x2f\xfd" else "zlib"
        size = struct.unpack_from("<I", data, 24)[0] if compression == "zstd" else struct.unpack_from(">I", data, 8)[0]
        if size > MAX_PAYLOAD:
            raise ValueError("XYZ payload exceeds supported limit")
        if compression == "zstd":
            if zstandard.frame_content_size(data[28:]) != size:
                raise ValueError("XYZ/zstd advertised size mismatch")
            payload = zstandard.ZstdDecompressor(max_window_size=MAX_PAYLOAD // 1024).decompress(data[28:], max_output_size=size, allow_extra_data=False)
        else:
            decoder = zlib.decompressobj()
            payload = decoder.decompress(data[28:], size + 1)
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError("XYZ stream boundary mismatch")
        if len(payload) != size:
            raise ValueError("XYZ payload size mismatch")
        return cls(bytes(data), payload, compression)

    @property
    def opaque_header(self):
        return self.raw[8:24] if self.compression == "zstd" else self.raw[12:28]

    def code(self):
        stream = io.BytesIO(self.payload)
        code = load_code(stream, MAGIC_26, bytes_for_s=True, code_objects={})
        if stream.tell() != len(self.payload):
            raise ValueError("Trailing marshal data")
        return code

    def unchanged(self):
        return self.raw

    def research_envelope(self, payload):
        """Never install this without resolving the opaque header contract."""
        if payload == self.payload:
            return self.raw
        if len(payload) > MAX_PAYLOAD:
            raise ValueError("XYZ payload too large")
        if self.compression == "zstd":
            return self.raw[:24] + struct.pack("<I", len(payload)) + zstandard.ZstdCompressor().compress(payload)
        return self.raw[:8] + struct.pack(">I", len(payload)) + self.raw[12:28] + zlib.compress(payload)
