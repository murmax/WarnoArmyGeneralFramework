"""Static objdump cross-references; indirect calls are explicitly not resolved."""
import os
from contextlib import closing
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from .native import PEImage
from .storage import sha256

LINE = re.compile(r'^\s*([0-9a-f]+):\s+(.*?)\s*$')
DIRECT = re.compile(r'^(callq?|jmpq?)\s+(?:0x)?([0-9a-f]+)(?:\s|$)')
RIP = re.compile(r'#\s*(?:0x)?([0-9a-f]+)(?:\s|$)')


def parse_reference(line, image_base):
    match = LINE.match(line)
    if not match: return None
    address, instruction = int(match[1],16), match[2]
    direct = DIRECT.match(instruction)
    if direct:
        kind, target = direct[1].removesuffix('q'), int(direct[2],16)
    else:
        comment = RIP.search(instruction) if '(%rip)' in instruction else None
        if not comment: return None
        kind, target = 'rip', int(comment[1],16)
    if not (0<=address-image_base<2**32 and 0<=target-image_base<2**32):
        return None
    return address-image_base, kind, target-image_base, instruction


def build_xrefs(exe):
    raw = Path(exe).read_bytes()
    digest = sha256(raw)
    pe = PEImage(raw)
    root = Path(__file__).resolve().parents[1]/'artifacts'/'native-code'/digest
    root.mkdir(parents=True,exist_ok=True)
    target = root/'xrefs-v1.sqlite'
    if target.exists():
        with closing(sqlite3.connect(f'{target.as_uri()}?mode=ro',uri=True)) as db:
            metadata = dict(db.execute('select key,value from metadata'))
            if metadata.get('source_sha256') != digest or metadata.get('complete') != 'true':
                raise ValueError('Invalid existing cross-reference cache')
        return target
    objdump = shutil.which('objdump')
    if not objdump: raise ValueError('GNU objdump required')
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    version = subprocess.run([objdump,'--version'],check=True,capture_output=True,text=True,
                             creationflags=flags,timeout=15).stdout.splitlines()[0]
    with tempfile.NamedTemporaryFile(prefix='xref-',suffix='.partial',dir=root,delete=False) as f:
        temporary = Path(f.name)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);'
                             'CREATE TABLE refs(rva INTEGER,kind TEXT,target INTEGER,function INTEGER,instruction TEXT);')
            command = [objdump,'-d','-w','--no-show-raw-insn',str(Path(exe).resolve())]
            with subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                  text=True,encoding='ascii',errors='replace',creationflags=flags) as proc:
                batch, count = [], 0
                try:
                    for line in proc.stdout:
                        value = parse_reference(line,pe.image_base)
                        if value:
                            rva,kind,destination,instruction = value
                            function = pe.function_containing(rva)
                            batch.append((rva,kind,destination,function['begin_rva'] if function else None,instruction))
                            if len(batch)>=10000:
                                db.executemany('INSERT INTO refs VALUES(?,?,?,?,?)',batch)
                                count+=len(batch);batch.clear()
                                if count%200000==0: print(f'Indexed {count} static references',flush=True)
                except BaseException:
                    # Popen.__exit__ waits: kill first so a full stdout pipe cannot deadlock it.
                    proc.kill()
                    proc.wait()
                    raise
                if proc.wait()!=0: raise ValueError('objdump failed; cross-reference index not published')
                db.executemany('INSERT INTO refs VALUES(?,?,?,?,?)',batch)
                count+=len(batch)
            db.execute('CREATE INDEX refs_target ON refs(target)')
            db.execute('CREATE INDEX refs_function ON refs(function)')
            db.executemany('INSERT INTO metadata VALUES(?,?)',[
                ('source_sha256',digest),('objdump',version),('schema','1'),('complete','true'),
                ('reference_count',str(count)),('scope','objdump -d executable-section linear disassembly: direct call/jmp and RIP-relative operands; not indirect targets')])
        # Publish only a complete index; old evidence is never overwritten.
        temporary.rename(target)
    except BaseException:
        if temporary.exists() and temporary.resolve().parent==root.resolve(): temporary.unlink()
        raise
    print(f'Cross-reference index: {count} references',flush=True)
    return target


def references_to(database, rva):
    path=Path(database).resolve()
    with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        return [dict(row) for row in db.execute('SELECT * FROM refs WHERE target=? ORDER BY rva',(rva,))]
