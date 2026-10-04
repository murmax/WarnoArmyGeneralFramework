"""Typed CNDF identity edits for a cloned campaign Definition resource."""
import copy
import re
from .cndf import decode,encode_objects,encode_strings,rebuild_sections
from .storage import sha256
from .transforms import report


def _property(obj,name):
    found=[p['value'] for p in obj['properties'] if p['property_name']==name]
    if len(found)!=1: raise ValueError(f'Identity property {name} is missing or ambiguous')
    return found[0]


def _scalar(value):
    return value.get('value_hex') if 'value_hex' in value else value.get('value')


def patch_identity(raw,spec):
    if (not isinstance(spec,dict) or set(spec)!={'source_sha256','strings','properties'} or
            not isinstance(spec['source_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',spec['source_sha256'])):
        raise ValueError('Unknown, missing or invalid identity spec fields')
    if sha256(raw)!=spec['source_sha256']: raise ValueError('Identity source fingerprint mismatch')
    if not isinstance(spec['strings'],list) or not isinstance(spec['properties'],list):
        raise ValueError('Identity operations must be lists')
    doc,graph=decode(raw);expected=copy.deepcopy(graph);changed_sections=set();targets=set()
    for op in spec['strings']:
        if not isinstance(op,dict) or set(op)!={'table','expected','value'} or op['table'] not in ('strings','translations'):
            raise ValueError('Invalid identity string operation')
        old,new=op['expected'],op['value']
        if not isinstance(old,str) or not isinstance(new,str) or not old or not new or old==new:
            raise ValueError('Identity string values must be distinct non-empty text')
        table=expected[op['table']];matches=[i for i,value in enumerate(table) if value==old]
        target=(op['table'],old)
        if len(matches)!=1 or target in targets: raise ValueError('Identity string target is missing, ambiguous or duplicate')
        targets.add(target);table[matches[0]]=new
        changed_sections.add('STRG' if op['table']=='strings' else 'TRAN')
    for op in spec['properties']:
        if not isinstance(op,dict) or set(op)!={'class','property','expected','value'}:
            raise ValueError('Invalid identity property operation')
        if not isinstance(op['class'],str) or not isinstance(op['property'],str) or not op['class'] or not op['property']:
            raise ValueError('Identity class/property must be non-empty text')
        matches=[]
        for obj in expected['objects']:
            if obj['class']==op['class']:
                value=_property(obj,op['property'])
                if _scalar(value)==op['expected']: matches.append(value)
        target=(op['class'],op['property'],repr(op['expected']))
        if len(matches)!=1 or target in targets: raise ValueError('Identity property target is missing, ambiguous or duplicate')
        value=matches[0]
        if type(op['expected']) is not type(op['value']) or op['expected']==op['value']:
            raise ValueError('Identity property values must be type-stable and distinct')
        if 'value_hex' in value:
            if not isinstance(op['value'],str) or len(op['value'])!=len(value['value_hex']) or not re.fullmatch('[0-9a-f]+',op['value']):
                raise ValueError('Identity hexadecimal property is invalid')
            value['value_hex']=op['value']
        elif type(value.get('value')) is not type(op['expected']):
            raise ValueError('Identity property type changed')
        else: value['value']=op['value']
        targets.add(target);changed_sections.add('OBJE')
    if not targets: raise ValueError('Identity spec is a no-op')
    replacements={}
    if 'STRG' in changed_sections: replacements['STRG']=encode_strings(expected['strings'])
    if 'TRAN' in changed_sections: replacements['TRAN']=encode_strings(expected['translations'])
    if 'OBJE' in changed_sections: replacements['OBJE']=encode_objects(expected['objects'])
    changed=rebuild_sections(doc,replacements);_,after=decode(changed)
    def replace_paths(value):
        for op in spec['strings']:
            if op['table']=='translations': value=value.replace(op['expected'],op['value'])
        return value
    expected['imports']={index:replace_paths(path) for index,path in expected['imports'].items()}
    expected['exports']={index:replace_paths(path) for index,path in expected['exports'].items()}
    def refresh(value):
        if isinstance(value,dict):
            if value.get('type_id') in (7,0x1c): value['value']=expected['strings'][value['index']]
            elif value.get('type_id')==0xaaaaaaaa: value['value']=expected['imports'][value['index']]
            for nested in value.values(): refresh(nested)
        elif isinstance(value,list):
            for nested in value: refresh(nested)
    refresh(expected['objects'])
    for key in ('objects','classes','properties','strings','translations','imports','exports'):
        if after[key]!=expected[key]: raise ValueError(f'Unexpected campaign identity changes in {key}')
    return changed,report(raw,changed,spec['strings']+spec['properties'],'campaign-identity')
