"""Declarative offline research packages. No deployment or game execution."""
import json
from pathlib import Path
import re
from .archives import read_directory, repack, clone_v3
from .storage import sha256, safe_child
from .transforms import patch_native, patch_script
from .scenario import patch_scenario
from .identity import patch_identity


def assemble_module(spec):
    base={'schema','id','source_pack','source_sha256','resources'}
    extended=base|{'output_name','entry_renames'}
    if not isinstance(spec, dict) or set(spec) not in (base,extended):
        raise ValueError('Unknown or missing package manifest fields')
    if type(spec['schema']) is not int or spec['schema'] != 1:
        raise ValueError('Unsupported package manifest schema')
    if not isinstance(spec['id'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,63}',spec['id']):
        raise ValueError('Invalid module id')
    if not isinstance(spec['resources'],list) or not spec['resources']:
        raise ValueError('A module must specify resources')
    raw = Path(spec['source_pack']).read_bytes()
    if sha256(raw) != spec['source_sha256']:
        raise ValueError('Module source pack fingerprint mismatch')
    # Verify EVERY payload before transformations, including untouched entries.
    repack(raw,{})
    header, entries, _ = read_directory(raw)
    entries = {e.path:e for e in entries}
    replacements, reports = {}, []
    for resource in spec['resources']:
        if not isinstance(resource,dict) or set(resource) != {'path','backend','spec'}:
            raise ValueError('Unknown or missing resource manifest fields')
        name = resource['path']
        if name not in entries or name in replacements:
            raise ValueError('Missing or duplicate module resource')
        backend = {'native':patch_native,'script':patch_script,'scenario-layout':patch_scenario,
                   'campaign-identity':patch_identity}.get(resource['backend'])
        if backend is None:
            raise ValueError('Unknown module backend')
        entry = entries[name]
        start = header.file_offset+entry.offset
        changed, report = backend(raw[start:start+entry.size],resource['spec'])
        replacements[name] = changed
        reports.append({'path':name, **report})
    if set(spec)==extended:
        if (not isinstance(spec['output_name'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.dat',spec['output_name']) or
                not isinstance(spec['entry_renames'],dict) or not spec['entry_renames']):
            raise ValueError('Invalid cloned archive output metadata')
        output=clone_v3(raw,replacements,spec['entry_renames'])
    else: output = repack(raw,replacements)
    # Exercise all rebuilt payload CRCs independently of the repacker diff check.
    repack(output,{})
    return output, {'schema':1,'id':spec['id'],'source_pack':str(Path(spec['source_pack']).resolve()),
                    'source_sha256':sha256(raw),'output_sha256':sha256(output),
                    'output_name':spec.get('output_name','package.edat'),
                    'resources':reports,'runtime_verified':False,'installable':False,
                    'status':'offline-research-only',
                    'limitations':['Not a deployed mod; runtime resource precedence and load path unverified',
                                   'Selected resources only; other native/Python variants are not synchronized']}


def write_build(spec):
    output, report = assemble_module(spec)
    # CLI deliberately has no arbitrary output-path or deployment option.
    root = Path(__file__).resolve().parents[1] / 'artifacts' / 'builds'
    if root.is_symlink() or root.resolve() != root.absolute():
        raise ValueError('Research output root must not be redirected')
    target = safe_child(root, spec['id']+'-'+report['output_sha256'][:16])
    if Path(spec['source_pack']).resolve().is_relative_to(target):
        raise ValueError('Source pack overlaps build output')
    target.mkdir(parents=True,exist_ok=False)
    with (target/'package.edat-research').open('xb') as stream:
        stream.write(output)
    for name, data in [('module.json',spec),('report.json',report)]:
        with (target/name).open('x',encoding='utf-8',newline='\n') as stream:
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.write('\n')
    # report.json is the completion marker; pre-existing outputs never overwritten.
    return target
