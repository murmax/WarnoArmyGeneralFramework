"""Read inspected LBH v10 point layouts; reject unsupported geometry encodings."""
import math
import struct

import zstandard


MAX_BODY_SIZE = 256 * 1024 * 1024


def read_point_lbh(raw):
    if len(raw) < 73 or raw[:4] != b'LBH0' or struct.unpack_from('<I', raw, 4)[0] != 10:
        raise ValueError('Unsupported point-scene LBH header')
    body_size = struct.unpack_from('<I', raw, 60)[0]
    if not 112 <= body_size <= MAX_BODY_SIZE:
        raise ValueError('Invalid point-scene LBH body size')
    try:
        if zstandard.frame_content_size(raw[64:]) != body_size:
            raise ValueError('Point-scene LBH frame size mismatch')
        body = zstandard.ZstdDecompressor(max_window_size=256 * 1024).decompress(
            raw[64:], max_output_size=body_size, allow_extra_data=False)
    except zstandard.ZstdError as error:
        raise ValueError('Invalid point-scene LBH compression') from error
    if len(body) != body_size:
        raise ValueError('Point-scene LBH decoded size mismatch')

    def bounded(offset, size, label):
        if offset < 0 or size < 0 or offset + size > body_size:
            raise ValueError('Point-scene LBH ' + label + ' outside body')

    symbol_offset, symbol_bytes, text_offset, text_bytes = struct.unpack_from('<4I', body, 16)
    bounded(symbol_offset, symbol_bytes, 'symbol table')
    bounded(text_offset, text_bytes, 'symbol text')
    if symbol_bytes % 8:
        raise ValueError('Invalid point-scene LBH symbol table')
    names = []
    for offset in range(symbol_offset, symbol_offset + symbol_bytes, 8):
        relative, length = struct.unpack_from('<IH', body, offset)
        if not length or relative + length > text_bytes:
            raise ValueError('Invalid point-scene LBH symbol name')
        try:
            name = body[text_offset + relative:text_offset + relative + length].decode('ascii')
        except UnicodeDecodeError as error:
            raise ValueError('Invalid point-scene LBH symbol encoding') from error
        names.append(name)
    if len(set(names)) != len(names):
        raise ValueError('Duplicate point-scene LBH symbols')
    cell_offset, cell_bytes = struct.unpack_from('<II', raw, 36)
    bounded(cell_offset, cell_bytes, 'cell table')
    if not cell_bytes or cell_bytes % 52:
        raise ValueError('Unsupported point-scene LBH cell layout')
    point_ranges = []
    points = []
    point_cells = []
    for offset in range(cell_offset, cell_offset + cell_bytes, 52):
        origin_x, origin_y = struct.unpack_from('<2f', body, offset)
        start, size = struct.unpack_from('<II', body, offset + 36)
        bounded(start, size, 'point records')
        if size and (start < 112 or start + size > cell_offset):
            raise ValueError('Point-scene LBH records overlap metadata')
        if size:
            if any(start < previous_end and previous_start < start + size
                   for previous_start, previous_end in point_ranges):
                raise ValueError('Overlapping point-scene LBH records')
            point_ranges.append((start, start + size))
        cursor = start
        while cursor < start + size:
            if cursor + 4 > start + size:
                raise ValueError('Truncated point-scene LBH record')
            flags = struct.unpack_from('<I', body, cursor)[0]
            symbol = flags >> 12
            layout = flags & 0xfff
            if symbol >= len(names) or layout not in (0x40, 0x80, 0x50, 0x90):
                raise ValueError('Unsupported point-scene LBH transform flags')
            transformed = bool(layout & 0x10)
            stride = 28 if transformed else 16
            if cursor + stride > start + size:
                raise ValueError('Truncated point-scene LBH transform')
            if transformed:
                cosine, negative_sine, horizontal, vertical, scale, height = struct.unpack_from(
                    '<6f', body, cursor + 4)
                if scale <= 0 or not math.isclose(math.hypot(cosine, negative_sine), scale,
                                                   rel_tol=1e-5, abs_tol=1e-6):
                    raise ValueError('Unsupported nonuniform point-scene transform')
                rotation = math.degrees(math.atan2(-negative_sine, cosine)) % 360
            else:
                horizontal, vertical, height = struct.unpack_from('<3f', body, cursor + 4)
                scale, rotation = 1.0, 0.0
            position = [origin_x + horizontal, origin_y + vertical, height]
            if not all(math.isfinite(value) for value in position + [scale, rotation]):
                raise ValueError('Nonfinite point-scene LBH transform')
            points.append({'asset': names[symbol], 'native_position': position,
                           'rotation_degrees': rotation, 'scale': scale})
            point_cells.append([origin_x, origin_y])
            cursor += stride
    return {'format': 'agf-point-lbh-readback-v1', 'symbols': names, 'points': points,
            'point_cells': point_cells,
            'ground_adaptation_verified': False}


def verify_point_lbh(raw, placements):
    """Match every instance; accept only engine copies beside spatial-cell borders."""
    result = read_point_lbh(raw)
    if len(result['points']) < len(placements):
        raise ValueError('Baked point scene has fewer instances than declared')

    def same(actual, expected):
        angle_difference = (actual['rotation_degrees'] - expected['rotation_degrees'] + 180) % 360 - 180
        return (actual['asset'] == expected['asset']
                and len(expected['native_position']) == 3
                and all(math.isclose(value, target, rel_tol=2**-23, abs_tol=1e-5)
                        for value, target in zip(actual['native_position'], expected['native_position']))
                and math.isclose(actual['scale'], expected['scale'], rel_tol=1e-5, abs_tol=1e-6)
                and abs(angle_difference) < 1e-4)

    unmatched = list(range(len(result['points'])))
    matched = []
    for expected in placements:
        match = next((index for index in unmatched if same(result['points'][index], expected)), None)
        if match is None:
            raise ValueError('Baked point scene transform or asset differs from declaration')
        unmatched.remove(match)
        matched.append(match)
    if unmatched:
        origins = result['point_cells']
        dimensions = []
        for axis in (0, 1):
            unique = sorted({row[axis] for row in origins})
            dimensions.extend(unique[index + 1] - unique[index]
                              for index in range(len(unique) - 1)
                              if unique[index + 1] > unique[index])
        if not dimensions:
            raise ValueError('Baked point scene contains undeclared duplicate instances')
        cell_step = min(dimensions)
        duplicate_cells = set()
        for extra in unmatched:
            point = result['points'][extra]
            origin = origins[extra]
            previous = next((index for index in matched
                             if same(point, result['points'][index])
                             and sum(not math.isclose(origin[axis], origins[index][axis],
                                     rel_tol=0, abs_tol=1e-4) for axis in (0, 1)) == 1
                             and any(math.isclose(abs(origin[axis] - origins[index][axis]),
                                     cell_step, rel_tol=0, abs_tol=1e-3) for axis in (0, 1))), None)
            if previous is None:
                raise ValueError('Baked point scene contains an undeclared extra instance')
            axis = 0 if origin[0] != origins[previous][0] else 1
            boundary = (origin[axis] + origins[previous][axis]) / 2
            if abs(point['native_position'][axis] - boundary) > cell_step / 80:
                raise ValueError('Baked point scene duplicate is away from a cell boundary')
            key = (previous, tuple(origin))
            if key in duplicate_cells:
                raise ValueError('Baked point scene repeats one cell instance')
            duplicate_cells.add(key)
    return {'format': 'agf-point-lbh-verification-v1', 'instances_verified': len(placements),
            'spatial_cell_duplicates': len(unmatched),
            'stored_transforms_verified': True, 'ground_adaptation_verified': False,
            'runtime_verified': False}
