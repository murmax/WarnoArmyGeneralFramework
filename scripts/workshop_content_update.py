"""Update an existing owner's WARNO item through the running Steam client.

Only content and preview setters are exposed. Title, description, visibility,
tags and other author-managed metadata are never submitted. No credentials
are accepted; Steam must already be logged in. Game executables are not run.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import time

APP = 1611600
U64, U32, I32, PTR, BOOL = C.c_uint64, C.c_uint32, C.c_int32, C.c_void_p, C.c_bool


class Callback(C.Structure):
    _fields_ = [('user', I32), ('callback', I32), ('data', PTR), ('size', I32)]


class Completed(C.Structure):
    _fields_ = [('call', U64), ('callback', I32), ('size', U32)]


class Details(C.Structure):
    _fields_ = [('id', U64), ('result', I32), ('type', I32), ('creator', U32),
        ('consumer', U32), ('title', C.c_char * 129), ('description', C.c_char * 8000),
        ('owner', U64), ('created', U32), ('updated', U32), ('listed', U32),
        ('visibility', I32), ('banned', BOOL), ('accepted', BOOL), ('truncated', BOOL),
        ('tags', C.c_char * 1025), ('file', U64), ('preview', U64),
        ('filename', C.c_char * 260), ('filesize', I32), ('previewsize', I32),
        ('url', C.c_char * 256), ('up', U32), ('down', U32), ('score', C.c_float),
        ('children', U32)]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unchanged(before, after):
    for key in ('id', 'owner', 'creator', 'consumer', 'title', 'description', 'visibility', 'tags'):
        if before[key] != after[key]:
            raise RuntimeError('Workshop author metadata changed: ' + key)


class Steam:
    def __init__(self, dll):
        os.environ['SteamAppId'] = str(APP)
        os.environ['SteamGameId'] = str(APP)
        self.dll = C.CDLL(str(Path(dll).resolve()))
        self.bind('SteamAPI_InitFlat', I32, [PTR])
        self.bind('SteamAPI_Shutdown', None, [])
        self.bind('SteamAPI_GetHSteamPipe', I32, [])
        self.bind('SteamAPI_ManualDispatch_Init', None, [])
        self.bind('SteamAPI_ManualDispatch_RunFrame', None, [I32])
        self.bind('SteamAPI_ManualDispatch_GetNextCallback', BOOL, [I32, C.POINTER(Callback)])
        self.bind('SteamAPI_ManualDispatch_FreeLastCallback', None, [I32])
        self.bind('SteamAPI_ManualDispatch_GetAPICallResult', BOOL,
                  [I32, U64, PTR, I32, I32, C.POINTER(BOOL)])
        self.bind('SteamAPI_SteamUGC_v020', PTR, [])
        self.bind('SteamAPI_SteamUser_v023', PTR, [])
        self.bind('SteamAPI_ISteamUser_GetSteamID', U64, [PTR])
        for name, result, args in (
            ('CreateQueryUGCDetailsRequest', U64, [C.POINTER(U64), U32]),
            ('SetReturnLongDescription', BOOL, [U64, BOOL]),
            ('SetAllowCachedResponse', BOOL, [U64, U32]),
            ('SendQueryUGCRequest', U64, [U64]),
            ('GetQueryUGCResult', BOOL, [U64, U32, PTR]),
            ('ReleaseQueryUGCRequest', BOOL, [U64]),
            ('StartItemUpdate', U64, [U32, U64]),
            ('SetItemContent', BOOL, [U64, C.c_char_p]),
            ('SetItemPreview', BOOL, [U64, C.c_char_p]),
            ('SubmitItemUpdate', U64, [U64, C.c_char_p]),
            ('GetItemUpdateProgress', I32, [U64, C.POINTER(U64), C.POINTER(U64)]),
        ):
            self.bind('SteamAPI_ISteamUGC_' + name, result, [PTR, *args])
        error = C.create_string_buffer(1024)
        if self.dll.SteamAPI_InitFlat(error) != 0:
            raise RuntimeError('Steam API initialization failed: ' + error.value.decode('utf-8'))
        self.dll.SteamAPI_ManualDispatch_Init()
        self.pipe = self.dll.SteamAPI_GetHSteamPipe()
        self.ugc = self.dll.SteamAPI_SteamUGC_v020()
        self.user = self.dll.SteamAPI_SteamUser_v023()
        if not self.pipe or not self.ugc or not self.user:
            self.close()
            raise RuntimeError('Steam client interfaces unavailable')

    def bind(self, name, result, args):
        fn = getattr(self.dll, name)
        fn.restype, fn.argtypes = result, args

    def ugc_call(self, name, *args):
        return getattr(self.dll, 'SteamAPI_ISteamUGC_' + name)(self.ugc, *args)

    def wait(self, call, callback, timeout=120, progress=None):
        if not call:
            raise RuntimeError('Steam returned an invalid asynchronous call')
        deadline, next_progress = time.monotonic() + timeout, 0
        while time.monotonic() < deadline:
            self.dll.SteamAPI_ManualDispatch_RunFrame(self.pipe)
            message = Callback()
            while self.dll.SteamAPI_ManualDispatch_GetNextCallback(self.pipe, C.byref(message)):
                completed = None
                if message.callback == 703 and message.size >= C.sizeof(Completed):
                    completed = Completed.from_buffer_copy(C.string_at(message.data, C.sizeof(Completed)))
                self.dll.SteamAPI_ManualDispatch_FreeLastCallback(self.pipe)
                if completed and completed.call == call:
                    if completed.callback != callback or not 4 <= completed.size <= 32768:
                        raise RuntimeError('Unexpected Steam callback schema')
                    data = C.create_string_buffer(completed.size)
                    failed = BOOL()
                    ok = self.dll.SteamAPI_ManualDispatch_GetAPICallResult(self.pipe, call, data,
                             completed.size, callback, C.byref(failed))
                    if not ok or failed.value:
                        raise RuntimeError('Steam asynchronous request failed')
                    return data.raw
            if progress and time.monotonic() >= next_progress:
                progress()
                next_progress = time.monotonic() + 15
            time.sleep(0.1)
        raise TimeoutError('Steam callback timed out')

    def query(self, item):
        ids = (U64 * 1)(item)
        query = self.ugc_call('CreateQueryUGCDetailsRequest', ids, 1)
        if not query or query == (1 << 64) - 1:
            raise RuntimeError('Steam details query rejected')
        try:
            if not self.ugc_call('SetReturnLongDescription', query, True):
                raise RuntimeError('Steam long description query rejected')
            self.ugc_call('SetAllowCachedResponse', query, 0)
            response = self.wait(self.ugc_call('SendQueryUGCRequest', query), 3401)
            if len(response) < 20 or I32.from_buffer_copy(response, 8).value != 1:
                raise RuntimeError('Steam details query did not succeed')
            # Larger backing buffer protects against SDK additions to the documented structure.
            buffer = C.create_string_buffer(32768)
            if not self.ugc_call('GetQueryUGCResult', query, 0, buffer):
                raise RuntimeError('Steam item details missing')
            d = Details.from_buffer_copy(buffer)
            if d.result != 1 or d.id != item or d.consumer != APP:
                raise RuntimeError('Unexpected Steam item identity or detail error')
            result = {name: getattr(d, name) for name in ('id', 'owner', 'creator', 'consumer', 'visibility', 'updated', 'file', 'preview', 'filesize', 'previewsize')}
            for name in ('title', 'description', 'tags'):
                result[name] = getattr(d, name).decode('utf-8', errors='strict')
            result['description_sha256'] = digest(result['description'].encode('utf-8'))
            result['authenticated_owner'] = d.owner == self.dll.SteamAPI_ISteamUser_GetSteamID(self.user)
            return result
        finally:
            self.ugc_call('ReleaseQueryUGCRequest', query)

    def update(self, item, content, preview, note):
        content, preview = Path(content).resolve(), Path(preview).resolve()
        if not content.is_dir() or not preview.is_file() or not 0 < preview.stat().st_size < 1_000_000:
            raise ValueError('Content directory and preview smaller than 1MB are required')
        size = sum(p.stat().st_size for p in content.rglob('*') if p.is_file())
        if not 0 < size <= 512 * 1024 * 1024:
            raise ValueError('Workshop update exceeds its 512MiB ceiling')
        before = self.query(item)
        if not before['authenticated_owner']:
            raise RuntimeError('Running Steam user does not own this Workshop item')
        handle = self.ugc_call('StartItemUpdate', APP, item)
        if not handle or handle == (1 << 64) - 1:
            raise RuntimeError('Steam update handle rejected')
        if not self.ugc_call('SetItemContent', handle, str(content).encode('utf-8')):
            raise RuntimeError('Steam content setter rejected')
        if not self.ugc_call('SetItemPreview', handle, str(preview).encode('utf-8')):
            raise RuntimeError('Steam preview setter rejected')
        def progress():
            processed, total = U64(), U64()
            state = self.ugc_call('GetItemUpdateProgress', handle, C.byref(processed), C.byref(total))
            print(json.dumps({'upload_state': state, 'processed': processed.value, 'total': total.value}), flush=True)
        result = self.wait(self.ugc_call('SubmitItemUpdate', handle, note.encode('utf-8')),
                           3404, timeout=1800, progress=progress)
        if I32.from_buffer_copy(result).value != 1:
            raise RuntimeError('Steam rejected update: EResult=' + str(I32.from_buffer_copy(result).value))
        if result[4]:
            raise RuntimeError('Steam requires owner acceptance of the Workshop legal agreement')
        after = self.query(item)
        unchanged(before, after)
        return {'before': before, 'after': after, 'metadata_preserved': True,
                'content_bytes': size, 'preview_sha256': digest(preview.read_bytes()),
                'steam_upload_performed': True}

    def close(self):
        self.dll.SteamAPI_Shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dll', required=True)
    parser.add_argument('--item', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--content', type=Path)
    parser.add_argument('--preview', type=Path)
    parser.add_argument('--note', default='Campaign V11: action point recovery and complete localization')
    args = parser.parse_args()
    if bool(args.content) != bool(args.preview) or args.output.exists():
        parser.error('Use a new receipt path and supply both content and preview for an update')
    steam = Steam(args.dll)
    try:
        report = steam.update(args.item, args.content, args.preview, args.note) if args.content else steam.query(args.item)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({key: value for key, value in report.items() if key not in ('description', 'before', 'after', 'tags')}, ensure_ascii=True))
    finally:
        steam.close()


if __name__ == '__main__':
    main()
