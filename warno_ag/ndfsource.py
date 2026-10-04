"""Read-only evidence from generated NDF source; this is not an NDF compiler."""
from pathlib import Path
import re
from .storage import safe_child,sha256


def export_block(text,name,kind):
    if not all(isinstance(v,str) and v for v in (name,kind)):
        raise ValueError('NDF export name/type must be non-empty text')
    matches=list(re.finditer(r'(?m)^export\s+'+re.escape(name)+r'\s+is\s+([^\s]+)\s*$',text))
    if not matches: raise ValueError(f'NDF export not found with expected type: {name}')
    if len(matches)!=1: raise ValueError(f'Ambiguous NDF export: {name}')
    match=matches[0]
    if match.group(1)!=kind: raise ValueError(f'NDF export not found with expected type: {name}')
    next_export=re.search(r'(?m)^export\s+',text[match.end():])
    end=match.end()+(next_export.start() if next_export else len(text)-match.end())
    return text[match.start():end]


def verify_ndf_profile(profile):
    if (not isinstance(profile,dict) or set(profile)!={'schema','root','files'} or
            type(profile['schema']) is not int or profile['schema']!=1 or
            not isinstance(profile['root'],str) or not profile['root'].strip()):
        raise ValueError('Unknown, missing or unsupported NDF evidence profile fields')
    root=Path(profile['root']).resolve()
    if not isinstance(profile['files'],list) or not profile['files']:
        raise ValueError('NDF evidence profile requires files')
    result=[]; paths=set()
    for file in profile['files']:
        if not isinstance(file,dict) or set(file)!={'path','sha256','exports'}:
            raise ValueError('Unknown or missing NDF evidence file fields')
        if (not isinstance(file['path'],str) or file['path'] in paths or
                not isinstance(file['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',file['sha256'])):
            raise ValueError('Invalid or duplicate NDF evidence file')
        paths.add(file['path'])
        path=safe_child(root,file['path'])
        raw=path.read_bytes()
        if sha256(raw)!=file['sha256']: raise ValueError(f'NDF evidence source fingerprint mismatch: {file["path"]}')
        text=raw.decode('utf-8')
        exports=[]; names=set()
        if not isinstance(file['exports'],list) or not file['exports']:
            raise ValueError('NDF evidence file requires exports')
        for expected in file['exports']:
            if not isinstance(expected,dict) or set(expected)!={'name','type','checks'}:
                raise ValueError('Unknown or missing NDF export evidence fields')
            if (not isinstance(expected['name'],str) or not isinstance(expected['type'],str) or
                    not expected['name'] or not expected['type'] or expected['name'] in names):
                raise ValueError('Invalid or duplicate NDF export evidence')
            names.add(expected['name'])
            block=export_block(text,expected['name'],expected['type'])
            checks=[]; checked_text=set()
            if not isinstance(expected['checks'],list) or not expected['checks']:
                raise ValueError('NDF export requires checks')
            for check in expected['checks']:
                if not isinstance(check,dict) or set(check) not in ({'text','minimum'},{'text','minimum','maximum'}):
                    raise ValueError('Unknown or missing NDF text-check fields')
                value,minimum=check['text'],check['minimum']
                maximum=check.get('maximum')
                if (not isinstance(value,str) or not value or type(minimum) is not int or minimum<1 or
                        value in checked_text or
                        (maximum is not None and (type(maximum) is not int or maximum<minimum))):
                    raise ValueError('Invalid NDF text-check bounds')
                checked_text.add(value)
                count=block.count(value)
                if count<minimum or maximum is not None and count>maximum:
                    raise ValueError(f'NDF export evidence mismatch: {expected["name"]}')
                checks.append({'text':value,'count':count,'verified':True})
            exports.append({'name':expected['name'],'type':expected['type'],'checks':checks})
        result.append({'path':str(path),'sha256':file['sha256'],'exports':exports})
    return {'schema':1,'root':str(root),'files':result,'verified':True,
            'limitations':['Generated NDF text was inspected; compilation and runtime resolution were not verified']}
