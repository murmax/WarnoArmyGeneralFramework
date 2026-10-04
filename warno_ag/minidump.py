"""Read captured AMD64 exception state without loading or executing the game."""
from bisect import bisect_right
import struct


class MiniDump:
    def __init__(self, raw):
        self.raw = bytes(raw)
        signature, version, count, directory = self.unpack('<4sIII', 0)
        if signature != b'MDMP' or version & 0xffff != 0xa793:
            raise ValueError('Unsupported minidump header')
        self.slice(directory, count * 12)
        self.streams = {}
        for index in range(count):
            kind, size, offset = self.unpack('<III', directory + index * 12)
            if kind == 0:
                continue
            if kind in self.streams:
                raise ValueError('Duplicate minidump stream')
            self.slice(offset, size)
            self.streams[kind] = (offset, size)
        architecture, = self.stream_unpack(7, '<H')
        if architecture != 9:
            raise ValueError('Only AMD64 minidumps are supported')
        memory_count, = self.stream_unpack(5, '<I')
        memory_offset, memory_size = self.streams[5]
        if 4 + memory_count * 16 > memory_size:
            raise ValueError('Truncated minidump memory descriptors')
        self.memory = []
        for index in range(memory_count):
            address, size, offset = self.unpack('<QII', memory_offset + 4 + index * 16)
            self.slice(offset, size)
            if address + size > 1 << 64:
                raise ValueError('Invalid virtual memory range')
            if size:
                self.memory.append((address, size, offset))
        self.memory.sort()
        for previous, current in zip(self.memory, self.memory[1:]):
            if previous[0] + previous[1] > current[0]:
                raise ValueError('Overlapping captured memory ranges')
        self.addresses = [entry[0] for entry in self.memory]
        thread_id, = self.stream_unpack(6, '<I')
        code, = self.stream_unpack(6, '<I', 8)
        address, = self.stream_unpack(6, '<Q', 24)
        parameter_count, = self.stream_unpack(6, '<I', 32)
        if parameter_count > 15:
            raise ValueError('Invalid exception parameter count')
        parameters = self.stream_unpack(6, '<' + 'Q' * parameter_count, 40)
        context_size, context_offset = self.stream_unpack(6, '<II', 160)
        self.slice(context_offset, context_size)
        if context_size < 256:
            raise ValueError('Truncated AMD64 exception context')
        flags, = self.unpack('<I', context_offset + 48)
        if flags & 0x100003 != 0x100003:
            raise ValueError('AMD64 control/integer registers not captured')
        names = ('rax', 'rcx', 'rdx', 'rbx', 'rsp', 'rbp', 'rsi', 'rdi',
                 'r8', 'r9', 'r10', 'r11', 'r12', 'r13', 'r14', 'r15', 'rip')
        values = self.unpack('<17Q', context_offset + 120)
        self.exception = {'thread_id': thread_id, 'code': code, 'address': address,
                          'parameters': list(parameters), 'registers': dict(zip(names, values))}

    def slice(self, offset, size):
        if offset < 0 or size < 0 or offset + size > len(self.raw):
            raise ValueError('Truncated or invalid minidump file range')
        return self.raw[offset:offset + size]

    def unpack(self, format_string, offset):
        return struct.unpack(format_string, self.slice(offset, struct.calcsize(format_string)))

    def stream_unpack(self, kind, format_string, relative=0):
        if kind not in self.streams:
            raise ValueError(f'Required minidump stream {kind} not captured')
        offset, size = self.streams[kind]
        if relative < 0 or relative + struct.calcsize(format_string) > size:
            raise ValueError('Truncated minidump stream')
        return self.unpack(format_string, offset + relative)

    def read_memory(self, address, size):
        if address < 0 or size < 0 or address + size > 1 << 64:
            raise ValueError('Invalid virtual memory request')
        result = bytearray()
        while size:
            index = bisect_right(self.addresses, address) - 1
            if index < 0:
                raise ValueError(f'Memory at {address:#x} not captured')
            lower, length, offset = self.memory[index]
            available = lower + length - address
            if available <= 0:
                raise ValueError(f'Memory at {address:#x} not captured')
            copied = min(size, available)
            result.extend(self.raw[offset + address - lower:offset + address - lower + copied])
            address += copied
            size -= copied
        return bytes(result)
