"""Read the checked TGV layouts used by native WARNO map and UI textures."""
import io
import struct
import zlib

from PIL import Image
import zstandard


def texture_header(raw):
    if len(raw) < 56:
        raise ValueError('Truncated TGV texture')
    version, flags, width, height, stored_width, stored_height, count, name_length = struct.unpack_from('<6IHH', raw)
    if version not in (2, 3) or flags not in (0, 2) or not 1 <= count <= 16 or not 1 <= name_length <= 32:
        raise ValueError('Unsupported TGV header')
    if any(not 1 <= value <= 16384 for value in (width, height, stored_width, stored_height)):
        raise ValueError('Invalid TGV dimensions')
    format_name = raw[28:28 + name_length].decode('ascii').rstrip('\0')
    table = ((28 + name_length + 3) // 4) * 4 + 16
    if table + count * 8 > len(raw):
        raise ValueError('Truncated TGV mip table')
    offsets = struct.unpack_from('<' + 'I' * count, raw, table)
    sizes = struct.unpack_from('<' + 'I' * count, raw, table + count * 4)
    ranges = []
    for offset, size in zip(offsets, sizes):
        if offset < table + count * 8 or size < 1 or offset + size > len(raw):
            raise ValueError('TGV mip is outside the texture')
        if any(offset < end and start < offset + size for start, end in ranges):
            raise ValueError('Overlapping TGV mip data')
        ranges.append((offset, offset + size))
    return {'version': version, 'flags': flags, 'width': width, 'height': height,
            'stored_width': stored_width, 'stored_height': stored_height,
            'format': format_name, 'mips': list(zip(offsets, sizes))}


def _decode_mip(raw, offset, size, flags):
    payload = raw[offset:offset + size]
    if flags == 0:
        return payload
    if len(payload) < 8:
        raise ValueError('Truncated compressed TGV mip')
    expected = struct.unpack_from('<I', payload, 4)[0]
    if not 1 <= expected <= 512 * 1024 * 1024:
        raise ValueError('TGV decoded size is out of range')
    if payload[:4] == b'ZSTD':
        result = zstandard.ZstdDecompressor().decompress(payload[8:], max_output_size=expected, allow_extra_data=False)
    elif payload[:4] == b'ZIPO':
        decoder = zlib.decompressobj()
        result = decoder.decompress(payload[8:], expected + 1)
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Invalid TGV zlib frame')
    else:
        raise ValueError('Unsupported TGV compression')
    if len(result) != expected:
        raise ValueError('TGV decoded mip size mismatch')
    return result


def read_texture(raw):
    header = texture_header(raw)
    width, height, name = header['width'], header['height'], header['format']
    if name.startswith('L16') or name == 'R16_LIN':
        expected = width * height * 2
        mode = 'I;16'
    elif name.startswith('A8B8G8R8'):
        expected = width * height * 4
        mode = 'RGBA'
    elif name.startswith(('BC1', 'DXT1')):
        expected = ((width + 3) // 4) * ((height + 3) // 4) * 8
        mode = 'DXT1'
    elif name.startswith(('BC3', 'DXT5')):
        expected = ((width + 3) // 4) * ((height + 3) // 4) * 16
        mode = 'DXT5'
    else:
        raise ValueError('Unsupported native texture format: ' + name)
    candidates = []
    for offset, size in header['mips']:
        decoded_size = size if header['flags'] == 0 else struct.unpack_from('<I', raw, offset + 4)[0]
        if decoded_size == expected:
            candidates.append((offset, size))
    if len(candidates) != 1:
        raise ValueError('TGV has no unique full-resolution mip')
    pixels = _decode_mip(raw, *candidates[0], header['flags'])
    if mode in ('I;16', 'RGBA'):
        return Image.frombytes(mode, (width, height), pixels), header
    dds = bytearray(128)
    dds[:4] = b'DDS '
    struct.pack_into('<7I', dds, 4, 124, 0x81007, height, width, len(pixels), 0, 1)
    struct.pack_into('<II4s5I', dds, 76, 32, 4, mode.encode('ascii'), 0, 0, 0, 0, 0)
    struct.pack_into('<I', dds, 108, 0x1000)
    with Image.open(io.BytesIO(bytes(dds) + pixels)) as image:
        image.load()
        return image.copy(), header
