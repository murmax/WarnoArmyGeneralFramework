"""Windows process identities for launch observation without external dependencies."""
import ctypes
from ctypes import wintypes


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                ('pid', wintypes.DWORD), ('heap', ctypes.c_size_t),
                ('module', wintypes.DWORD), ('threads', wintypes.DWORD),
                ('parent', wintypes.DWORD), ('priority', wintypes.LONG),
                ('flags', wintypes.DWORD), ('exe', wintypes.WCHAR * 260)]


def snapshot():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    signatures = {
        'CreateToolhelp32Snapshot': ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
        'Process32FirstW': ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        'Process32NextW': ([wintypes.HANDLE, ctypes.POINTER(ProcessEntry)], wintypes.BOOL),
        'OpenProcess': ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
        'GetProcessTimes': ([wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
        'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        getattr(api, name).argtypes = arguments
        getattr(api, name).restype = result
    handle = api.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    records = {}
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        available = api.Process32FirstW(handle, ctypes.byref(entry))
        while available:
            process = api.OpenProcess(0x1000, False, entry.pid)
            if process:
                try:
                    times = [wintypes.FILETIME() for unused in range(4)]
                    if api.GetProcessTimes(process, *(ctypes.byref(value) for value in times)):
                        created = times[0].dwHighDateTime << 32 | times[0].dwLowDateTime
                        records[entry.pid] = {'created': created, 'parent': entry.parent,
                                              'exe': entry.exe}
                finally:
                    api.CloseHandle(process)
            available = api.Process32NextW(handle, ctypes.byref(entry))
    finally:
        api.CloseHandle(handle)
    return records


def descendants(records, owned):
    """Extend known identities, refusing a parent PID reused by another process."""
    result = dict(owned)
    changed = True
    while changed:
        changed = False
        for pid, record in records.items():
            parent = record['parent']
            if pid in result or parent not in result:
                continue
            if parent in records and records[parent]['created'] != result[parent]:
                continue
            if record['created'] >= result[parent]:
                result[pid] = record['created']
                changed = True
    return result
