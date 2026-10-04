"""Generate regular Army General logical zones from a strategic-map contract."""
import copy
import struct

from .authoring import _guid
from .cndf import decode, encode_objects, encode_strings, rebuild_sections


def _value(type_id, type_name, value):
    return {'type_id': type_id, 'type': type_name, 'reference_prefix': False, 'value': value}


def _reference(object_id, class_id):
    return {'type_id': 3149642683, 'type': 'obj_ref', 'reference_prefix': True,
            'object_id': object_id, 'class_id': class_id}


def _list(items, type_name='list'):
    return {'type_id': 18 if type_name == 'map_list' else 17, 'type': type_name,
            'reference_prefix': False, 'length': len(items), 'items': items}


def _replace(document, graph, objects, strings, top=(0,)):
    for index, obj in enumerate(objects):
        obj['id'] = index
        obj['class_id'] = graph['classes'].index(obj['class'])
        obj['is_top_object'] = index in top
    chunk = next(section for section in document.sections if section.name == 'CHNK')
    raw_chunk = bytearray(document.full_data[chunk.offset:chunk.offset + chunk.size])
    struct.pack_into('<I', raw_chunk, 4, len(objects))
    result = rebuild_sections(document, {'OBJE': encode_objects(objects),
        'TOPO': b''.join(struct.pack('<I', index) for index in top),
        'CHNK': bytes(raw_chunk), 'STRG': encode_strings(strings)})
    _, check = decode(result)
    if check['object_count'] != len(objects) or [o['id'] for o in check['objects'] if o['is_top_object']] != list(top):
        raise ValueError('Strategic zone graph readback mismatch')
    return result


def _properties(graph, class_name):
    return {row['name']: row['id'] for row in graph['properties'] if row['class'] == class_name}


def _object(class_name, properties):
    return {'class': class_name, 'properties': properties}


def _property(ids, name, value):
    return {'property_id': ids[name], 'property_name': name, 'value': value}


def cell_names(contract):
    return [f'AGFW_Cell_r{row}c{column}' for row in range(contract['dimensions']['height'])
            for column in range(contract['dimensions']['width'])]


def build_regular_ia_zones(template, contract, campaign_id):
    document, graph = decode(template)
    required = {'TMapAreaSet', 'TMapArea', 'TGameDesignAddOn_StrategicIAStratZone'}
    if not required <= set(graph['classes']):
        raise ValueError('Unsupported strategic-zone template')
    names = cell_names(contract)
    strings = names + ['Tag_StrategicIAStratZone']
    string_index = {value: index for index, value in enumerate(strings)}
    width, height = contract['dimensions']['width'], contract['dimensions']['height']
    left, bottom, right, top = contract.get('playable_bounds', contract['bounds'])
    cell_width, cell_height = (right-left)/width, (top-bottom)/height
    set_ids = _properties(graph, 'TMapAreaSet')
    area_ids = _properties(graph, 'TMapArea')
    addon_ids = _properties(graph, 'TGameDesignAddOn_StrategicIAStratZone')
    areas, addons = [], []
    area_class = graph['classes'].index('TMapArea')
    addon_class = graph['classes'].index('TGameDesignAddOn_StrategicIAStratZone')
    for index, name in enumerate(names):
        row, column = divmod(index, width)
        x0, y0 = left + column*cell_width, bottom + row*cell_height
        x1, y1 = x0 + cell_width, y0 + cell_height
        addon_id = 1 + len(names) + index
        polygon = [[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]
        areas.append(_object('TMapArea', [
            _property(area_ids, 'BasePolygon2D', _list([_value(33,'float2',point) for point in polygon])),
            _property(area_ids, 'Center', _value(11,'vec3',[(x0+x1)/2,(y0+y1)/2,0.0])),
            _property(area_ids, 'AddOn', _reference(addon_id, addon_class))]))
        addons.append(_object('TGameDesignAddOn_StrategicIAStratZone', [
            _property(addon_ids, 'Name', dict(_value(7,'strg_ref',name), index=string_index[name])),
            _property(addon_ids, 'Ranking', dict(_value(7,'strg_ref','Tag_StrategicIAStratZone'), index=string_index['Tag_StrategicIAStratZone'])),
            _property(addon_ids, 'GUID', {'type_id':26,'type':'guid','reference_prefix':False,
                'value_hex':_guid('strategic-cell',campaign_id,f'r{row}c{column}')}),
            _property(addon_ids, 'Defense_ToCapture', _value(2,'int32',1))]))
    root = _object('TMapAreaSet', [_property(set_ids, 'Areas',
        _list([_reference(1+i, area_class) for i in range(len(areas))]))])
    return _replace(document, graph, [root] + areas + addons, strings)


def build_regular_playable_zone(template, contract):
    document, graph = decode(template)
    set_ids, area_ids = _properties(graph,'TMapAreaSet'), _properties(graph,'TMapArea')
    left,bottom,right,top = contract.get('playable_bounds', contract['bounds'])
    polygon=[[left,bottom],[right,bottom],[right,top],[left,top],[left,bottom]]
    area_class=graph['classes'].index('TMapArea')
    root=_object('TMapAreaSet',[_property(set_ids,'Areas',_list([_reference(1,area_class)]))])
    area=_object('TMapArea',[
        _property(area_ids,'BasePolygon2D',_list([_value(33,'float2',p) for p in polygon])),
        _property(area_ids,'Center',_value(11,'vec3',[(left+right)/2,(bottom+top)/2,0.0])),
        _property(area_ids,'Rotation',_value(5,'float32',0.0))])
    return _replace(document,graph,[root,area],[])


def build_regular_map_strategies(template, contract):
    document,graph=decode(template)
    names=cell_names(contract); width=contract['dimensions']['width']; height=contract['dimensions']['height']
    ids={name:_properties(graph,name) for name in graph['classes']}
    classes={name:graph['classes'].index(name) for name in graph['classes']}
    objects=[None,None,None]
    strategy_data=[]
    for side in range(2):
        info_ids=[]
        for name in names:
            info_ids.append(len(objects))
            objects.append(_object('TStrategicZoneBattleInfos',[
                _property(ids['TStrategicZoneBattleInfos'],'WeightPerValueType',
                          _list([_value(5,'float32',0.0) for unused in range(4)]))]))
        links=[]
        for row in range(height):
            for column in range(width):
                here=row*width+column
                for target in ((row,column+1),(row+1,column)):
                    if target[0] >= height or target[1] >= width: continue
                    there=target[0]*width+target[1]
                    link_id=len(objects); links.append(link_id)
                    objects.append(_object('TIAStratZoneLink',[
                        _property(ids['TIAStratZoneLink'],'FromZone',dict(_value(7,'strg_ref',names[here]),index=here)),
                        _property(ids['TIAStratZoneLink'],'ToZone',dict(_value(7,'strg_ref',names[there]),index=there))]))
        zone_items=[{'key':dict(_value(7,'strg_ref',name),index=index),
                     'value':_reference(info_ids[index],classes['TStrategicZoneBattleInfos'])}
                    for index,name in enumerate(names)]
        strategy_data.append([
            _property(ids['TStrategicMapStrategy'],'ZoneInfos',_list(zone_items,'map_list')),
            _property(ids['TStrategicMapStrategy'],'ZoneLinks',_list([
                _reference(index,classes['TIAStratZoneLink']) for index in links]))])
    objects[1]=_object('TStrategicMapStrategy',strategy_data[0])
    objects[2]=_object('TStrategicMapStrategy',strategy_data[1])
    objects[0]=_object('TStrategicMapStrategies',[
        _property(ids['TStrategicMapStrategies'],'AttackerStrategy',_reference(1,classes['TStrategicMapStrategy'])),
        _property(ids['TStrategicMapStrategies'],'DefenderStrategy',_reference(2,classes['TStrategicMapStrategy']))])
    return _replace(document,graph,objects,names)


def clear_item_database(template):
    document,graph=decode(template)
    roots=[copy.deepcopy(obj) for obj in graph['objects'] if obj['is_top_object']]
    databases=[obj for obj in roots if obj['class'] in ('TSaveDescriptorItemList','TGameDesignDatabase')]
    shells=[obj for obj in roots if obj['class']=='TSaveDescriptorPatternSet' and not obj['properties']]
    if len(databases)!=1 or len(roots)!=1+len(shells):
        raise ValueError('Unsupported map item database root')
    database=databases[0]
    field='Items' if database['class']=='TSaveDescriptorItemList' else 'GameDesignItemList'
    values=[prop['value'] for prop in database['properties'] if prop['property_name']==field]
    if len(values)!=1 or values[0].get('type')!='list':
        raise ValueError('Unsupported map item database list')
    values[0]['items']=[]; values[0]['length']=0
    objects=[database]+shells
    return _replace(document,graph,objects,graph['strings'],tuple(range(len(objects))))
