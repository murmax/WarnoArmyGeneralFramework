"""Read-only, build-pinned native analysis; never loads or executes the image."""
from bisect import bisect_right
from pathlib import Path
import os
import json
import shutil
import struct
import subprocess
from .storage import sha256, write_json, safe_child


class PEImage:
    def __init__(self, raw):
        self.raw = bytes(raw)
        if len(raw) < 64 or raw[:2] != b'MZ':
            raise ValueError('Not a PE image')
        pe = self.unpack('<I',0x3c)[0]
        if raw[pe:pe+4] != b'PE\0\0':
            raise ValueError('Invalid PE signature')
        machine, count = self.unpack('<HH',pe+4)
        optional_size = self.unpack('<H',pe+20)[0]
        opt = pe+24
        if machine != 0x8664 or not 0<count<=96 or optional_size < 144 or self.unpack('<H',opt)[0] != 0x20b:
            raise ValueError('Only x64 PE32+ with exception directory is supported')
        self.image_base = self.unpack('<Q',opt+24)[0]
        directories = self.unpack('<I',opt+108)[0]
        if directories < 4 or 112+directories*8 > optional_size:
            raise ValueError('Invalid PE optional header directories')
        table = opt+optional_size
        self.sections = []
        for i in range(count):
            pos = table+40*i
            size,rva,raw_size,offset = self.unpack('<IIII',pos+8)
            flags = self.unpack('<I',pos+36)[0]
            if offset+raw_size > len(raw) or (raw_size and offset < table+count*40):
                raise ValueError('Invalid PE section file range')
            self.sections.append({'name':raw[pos:pos+8].split(b'\0')[0].decode('ascii'),
                                  'rva':rva,'virtual_size':size,'file_offset':offset,
                                  'file_size':raw_size,'flags':flags})
        for key,size_key in [('rva','virtual_size'),('file_offset','file_size')]:
            ordered = sorted((s for s in self.sections if s[size_key]),key=lambda s:s[key])
            for a,b in zip(ordered,ordered[1:]):
                span = max(a['virtual_size'],a['file_size']) if key=='rva' else a[size_key]
                if a[key]+span > b[key]:
                    raise ValueError('Overlapping PE sections')
        exception_rva,exception_size = self.unpack('<II',opt+112+3*8)
        if not exception_size or exception_size % 12:
            raise ValueError('Invalid PE runtime function table size')
        offset = self.file_offset(exception_rva,exception_size)
        self.functions = []
        for pos in range(offset,offset+exception_size,12):
            begin,end,unwind = self.unpack('<III',pos)
            if begin >= end or (self.functions and begin < self.functions[-1]['end_rva']):
                raise ValueError('Invalid/overlapping PE runtime function range')
            self.file_offset(begin,end-begin)
            self.file_offset(unwind,4)
            self.functions.append({'begin_rva':begin,'end_rva':end,'unwind_rva':unwind})
        self.begins = [f['begin_rva'] for f in self.functions]

    def unpack(self, fmt, offset):
        if offset < 0 or offset+struct.calcsize(fmt) > len(self.raw):
            raise ValueError('Truncated PE structure')
        return struct.unpack_from(fmt,self.raw,offset)

    def file_offset(self, rva, size=1):
        if size < 1:
            raise ValueError('Invalid PE requested span')
        found = [s for s in self.sections if s['rva']<=rva and rva+size<=s['rva']+s['file_size']]
        if len(found)!=1:
            raise ValueError('PE RVA is unbacked or ambiguous')
        section = found[0]
        return section['file_offset']+rva-section['rva']

    def function_containing(self, rva):
        i=bisect_right(self.begins,rva)-1
        return self.functions[i] if i>=0 and rva<self.functions[i]['end_rva'] else None


def verify_native_profile(raw, profile):
    """Verify static observations, not reachability, ABI or runtime hook safety."""
    if sha256(raw) != profile['source_sha256']:
        raise ValueError('Executable does not match native research profile')
    pe = PEImage(raw)
    verified, identifiers = [], set()
    for check in profile.get('checks', []):
        identifier = check['id']
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError('Invalid/duplicate native check identifier')
        identifiers.add(identifier)
        rva = int(check['rva'], 16)
        kind = check['kind']
        if kind == 'bytes':
            expected = bytes.fromhex(check['expected'])
            if not 1 <= len(expected) <= 256:
                raise ValueError('Native byte check must contain 1..256 bytes')
        elif kind == 'ascii':
            expected = check['expected'].encode('ascii') + b'\0'
        elif kind == 'pointer64':
            target = int(check['target_rva'], 16)
            pe.file_offset(target)
            expected = struct.pack('<Q', pe.image_base + target)
        elif kind in ('call_rel32', 'jump_rel32'):
            target = int(check['target_rva'], 16)
            for address in (rva, target):
                if not any(s['rva'] <= address < s['rva'] + s['file_size']
                           and s['flags'] & 0x20000000 for s in pe.sections):
                    raise ValueError('Native direct edge must connect executable sections')
            expected = bytes([0xe8 if kind == 'call_rel32' else 0xe9]) + struct.pack('<i', target-rva-5)
        else:
            raise ValueError(f'Unsupported native check kind: {kind}')
        offset = pe.file_offset(rva, len(expected))
        if raw[offset:offset+len(expected)] != expected:
            raise ValueError(f'Native evidence mismatch: {identifier} at {rva:#x}')
        verified.append({**check, 'file_offset': offset, 'size': len(expected), 'verified': True})
    return pe, verified


def inspect_native(exe, profile):
    """Record actual function ranges and disassembly, not inferred hook contracts."""
    raw = Path(exe).read_bytes()
    pe, checks = verify_native_profile(raw, profile)
    objdump = shutil.which('objdump')
    if not objdump:
        raise ValueError('GNU objdump is required for native disassembly')
    output = Path(__file__).resolve().parents[1]/'artifacts'/'native-code'/sha256(raw)
    output.mkdir(parents=True,exist_ok=True)
    options = {'check':True,'capture_output':True,'text':True,'timeout':30}
    if os.name=='nt': options['creationflags']=subprocess.CREATE_NO_WINDOW
    version=subprocess.run([objdump,'--version'],**options).stdout.splitlines()[0]
    profile_digest = sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode('utf-8'))
    report={'source':str(Path(exe).resolve()),'sha256':sha256(raw),'image_base':pe.image_base,
            'profile_sha256':profile_digest,'checks':checks,
            'sections':pe.sections,'runtime_function_count':len(pe.functions),'objdump':version,
            'functions':[],'runtime_verified':False,'hook_ready':False}
    for target in profile['targets']:
        rva=int(target['rva'],16)
        function=pe.function_containing(rva)
        if function is None:
            raise ValueError('Profile target has no runtime function entry')
        for anchor in target.get('strings',[]):
            offset=pe.file_offset(int(anchor['rva'],16),len(anchor['value'])+1)
            if raw[offset:offset+len(anchor['value'])+1] != anchor['value'].encode('ascii')+b'\0':
                raise ValueError('Native profile string anchor changed')
        begin,end = function['begin_rva'],function['end_rva']
        offset=pe.file_offset(begin,end-begin)
        command=[objdump,'-d',f'--start-address={pe.image_base+begin:#x}',
                 f'--stop-address={pe.image_base+end:#x}',str(Path(exe).resolve())]
        result=subprocess.run(command,**options)
        path=safe_child(output,f'{begin:08x}.asm.txt')
        path.write_text(result.stdout,encoding='utf-8',newline='\n')
        report['functions'].append({**target,**function,'file_offset':offset,
                                    'code_sha256':sha256(raw[offset:offset+end-begin]),
                                    'disassembly':str(path),'command':command})
    # Keep independent profiles' evidence when the latest-report alias changes.
    write_json(output/f'report-{profile_digest}.json',report)
    write_json(output/'report.json',report)
    return report
