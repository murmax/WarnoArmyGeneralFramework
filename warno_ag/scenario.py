"""Typed legacy ScenarioDB layout edits, keyed by stable game-design names."""
import copy
import math
import struct
from .cndf import decode, encode_objects, encode_strings, rebuild_sections
from .transforms import check_spec, report


FIELDS={'spawn','expected_class','class','expected_position','position'}


def one_property(obj,name):
    found=[p['value'] for p in obj['properties'] if p['property_name']==name]
    if len(found)!=1: raise ValueError(f'ScenarioDB property {name} is missing or ambiguous')
    return found[0]


def position(value,label):
    if (not isinstance(value,list) or len(value)!=2 or any(type(v) not in (int,float) for v in value)
            or any(not math.isfinite(v) for v in value)):
        raise ValueError(f'{label} must be two finite coordinates')
    try: return [struct.unpack('<f',struct.pack('<f',float(v)))[0] for v in value]
    except (OverflowError,struct.error) as exc: raise ValueError(f'{label} does not fit float32') from exc


def scenario_spawn(graph,name):
    found=[]
    for obj in graph['objects']:
        if obj['class']=='TGameDesignAddOn_Spawn':
            value=one_property(obj,'Name')
            if value.get('type_id') not in (7,0x1c): raise ValueError('ScenarioDB spawn Name is not a string reference')
            if value.get('value')==name: found.append(obj)
    if len(found)!=1: raise ValueError('ScenarioDB spawn selector is missing or ambiguous')
    addon=found[0]
    items=[]
    for obj in graph['objects']:
        if obj['class']=='TGameDesignItem':
            value=one_property(obj,'AddOn')
            if value.get('type_id')==0xbbbbbbbb and value.get('object_id')==addon['id']:
                items.append(obj)
    if len(items)!=1: raise ValueError('ScenarioDB spawn item relation is missing or ambiguous')
    return addon,items[0]


def patch_scenario(raw,spec):
    check_spec(raw,spec,FIELDS)
    doc,graph=decode(raw)
    if doc.header.compression_mode != 1:
        raise ValueError('ScenarioDB backend is pinned to explicit CNDF/LZ4 mode 1')
    expected=copy.deepcopy(graph)
    targets=set()
    for op in spec['operations']:
        name=op['spawn']
        if not isinstance(name,str) or not name or name in targets: raise ValueError('Invalid or duplicate ScenarioDB spawn')
        targets.add(name)
        addon,item=scenario_spawn(expected,name)
        class_value=one_property(addon,'ClassName')
        position_value=one_property(item,'Position')
        if class_value.get('type_id') not in (7,0x1c) or position_value.get('type_id')!=0x21:
            raise ValueError('ScenarioDB ClassName/Position types changed')
        if not all(isinstance(op[k],str) and op[k] for k in ('expected_class','class')):
            raise ValueError('ScenarioDB classes must be non-empty text')
        if class_value.get('value')!=op['expected_class']:
            raise ValueError('ScenarioDB class precondition failed')
        old_position=position(op['expected_position'],'expected_position')
        new_position=position(op['position'],'position')
        if position_value.get('value')!=old_position:
            raise ValueError('ScenarioDB position precondition failed')
        if op['class'] not in expected['strings']:
            expected['strings'].append(op['class'])
        class_value['index']=expected['strings'].index(op['class'])
        class_value['value']=op['class']
        position_value['value']=new_position
    if all(op['expected_class']==op['class'] and position(op['expected_position'],'expected_position')==position(op['position'],'position')
           for op in spec['operations']):
        raise ValueError('ScenarioDB operation set is a no-op')
    changed=rebuild_sections(doc,{'OBJE':encode_objects(expected['objects']),
                                  'STRG':encode_strings(expected['strings'])})
    _,after=decode(changed)
    for key in ('objects','classes','properties','strings','translations','imports','exports'):
        if after[key]!=expected[key]: raise ValueError(f'Unexpected ScenarioDB semantic changes in {key}')
    result=report(raw,changed,spec['operations'],'legacy-scenariodb-layout')
    result['limitations'].extend([
        'Legacy ScenarioDB path: runtime precedence against current GDScript/Details is unresolved',
        'Class reassignment assumes referenced strategic descriptors/decks are provided by the complete mod'])
    return changed,result
