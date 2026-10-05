"""Public campaign menu metadata, independent of the adapter's stock artwork."""
import copy
from pathlib import Path
import shutil
from PIL import Image
import yaml
from .storage import sha256, safe_child
from .cndf import decode, rebuild_sections, encode_objects, encode_strings

RESOURCE = Path('GameData/Generated/UserInterface/Textures/DivisionTextures.ndf')


def compile_menu(source, campaign):
    menu = campaign.get('menu')
    if menu is None:
        return None
    if not isinstance(menu,dict) or not {'header','subtitle','description','side_forces','image','attacker'} <= set(menu) or set(menu)-{'header','subtitle','description','side_forces','image','attacker','side_titles'}:
        raise ValueError('campaign.menu needs header, subtitle, description, side_forces, image and attacker')
    for key in ('header','subtitle','description'):
        value=menu[key]
        if not isinstance(value,dict) or set(value)!={'ru','en'} or any(not isinstance(x,str) or not x.strip() for x in value.values()):
            raise ValueError('campaign.menu.'+key+' needs RU/EN text')
    if menu['attacker'] not in ('nato','pact') or not isinstance(menu['side_forces'],dict) or set(menu['side_forces'])!={'nato','pact'}:
        raise ValueError('campaign.menu side configuration is invalid')
    for side,value in menu['side_forces'].items():
        if not isinstance(value,dict) or set(value)!={'ru','en'} or any(not isinstance(x,str) or not x.strip() for x in value.values()):
            raise ValueError('campaign.menu.side_forces.'+side+' needs RU/EN text')
    if 'side_titles' in menu:
        titles = menu['side_titles']
        if (not isinstance(titles, dict) or set(titles) != {'nato', 'pact'}
                or any(not isinstance(value, dict) or set(value) != {'ru', 'en'}
                       or any(not isinstance(text, str) or not text.strip() for text in value.values())
                       for value in titles.values())):
            raise ValueError('campaign.menu.side_titles needs NATO and PACT RU/EN text')
    path=safe_child(Path(source).resolve(), menu['image'])
    with Image.open(path) as im:
        if im.format!='PNG' or not 400<=im.width<=4096 or not 1.5<=im.width/im.height<=2.5:
            raise ValueError('Campaign menu map must be a landscape PNG at least 400 pixels wide')
        render_size=[400,round(400*im.height/im.width)]
    asset='GameData/Assets/2D/Interface/UseOutGame/AGFCampaigns/'+campaign['id']+'/MapTexture_AG.png'
    return {**copy.deepcopy(menu),'asset':asset,'image_sha256':sha256(path.read_bytes()),'render_size':render_size}


def stage_menu(source,workspace):
    if source is None:
        return None
    source,workspace=Path(source).resolve(),Path(workspace).resolve()
    campaign=yaml.safe_load((source/'campaign.yaml').read_text(encoding='utf-8'))
    menu=compile_menu(source,campaign)
    if menu is None:return None
    destination=safe_child(workspace,menu['asset'])
    if destination.exists():raise ValueError('Campaign menu artwork already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with Image.open(safe_child(source,menu['image'])) as image:
        image.convert('RGBA').resize(tuple(menu['render_size']),Image.Resampling.LANCZOS).save(destination)
    token='AGF_MenuMap_'+campaign['id']
    bank=workspace/RESOURCE
    text=bank.read_text(encoding='utf-8')
    if token in text:raise ValueError('Campaign menu texture token collision')
    text+='\n'+token+' is TUIResourceTexture_Common\n( FileName = "'+menu['asset'].replace('GameData/','GameData:/',1)+'" )\n'
    text+='unnamed TBUCKToolAdditionalTextureBank\n( Textures = MAP [("'+token+'", MAP [(~/ComponentState/Normal, ~/'+token+')])] )\n'
    bank.write_text(text,encoding='utf-8')
    return {'image':menu['image'],'asset':menu['asset']}


def menu_text(compiled,language):
    from .bruderkrieg import authored_text_key
    menu=compiled.get('menu')
    if not menu:return {}
    values={}
    def put(field,text):values[authored_text_key(compiled['campaign']['id'],'menu',field)]=text
    put('MissionName',menu['header'][language]);put('MissionSubtitle',menu['subtitle'][language])
    put('short_title',compiled['campaign']['title'][language])
    put('TitreObjectifs',compiled['campaign']['title'][language]);put('TexteObjectifs',menu['description'][language])
    put('MissionBrief',menu['description'][language]);put('TexteCentre',menu['subtitle'][language]);put('TextePrincipal','')
    # Preserve the native lobby convention: left = NATO (alliance 1).
    for prefix,side in [('Left','nato'),('Right','pact')]:
        attack=side==menu['attacker']
        title=(menu['side_titles'][side][language] if 'side_titles' in menu else
               ('США' if side=='nato' else 'СССР') if language=='ru' else ('UNITED STATES' if side=='nato' else 'SOVIET UNION'))
        role=('Атака' if attack else 'Защита') if language=='ru' else ('Attack' if attack else 'Defense')
        put(prefix+'BriefTitle',title+' — '+role)
        put(prefix+'BriefSubtitle',menu['side_forces'][side][language]);put(prefix+'Division','')
    return values


def patch_map_configuration(raw,compiled):
    menu=compiled.get('menu')
    if not menu:return raw
    from .bruderkrieg import authored_text_key
    doc,g=decode(raw)
    info,=[o for o in g['objects'] if o['class']=='TStrategicMapInfo']
    fields={p['property_name']:p['value'] for p in info['properties']}
    fields['Name']['value_hex']=authored_text_key(compiled['campaign']['id'],'menu','MissionName').hex()
    fields['ShortName']['value_hex']=authored_text_key(compiled['campaign']['id'],'menu','short_title').hex()
    for pair in fields['DescriptionTextElements']['items']:
        pair['value']['value_hex']=authored_text_key(compiled['campaign']['id'],'menu',pair['key']['value']).hex()
    fields['Duration']['value']=3  # 20 four-hour turns: four calendar days, native long-duration category.
    for prop in ('LobbyLeftSideAlliance','DefaultPlayerAlliance'):
        if prop in fields:fields[prop]['value']=1
    ref=next(pair['value'] for pair in fields['DescriptionTextureElements']['items'] if pair['key']['value']=='MapTexture_AG')
    filename=next(p['value'] for p in g['objects'][ref['object_id']]['properties'] if p['property_name']=='FileName')
    value=menu['asset'].replace('GameData/','GameData:/',1)
    if value not in g['strings']:g['strings'].append(value)
    filename.update(index=g['strings'].index(value),value=value)
    return rebuild_sections(doc,{'STRG':encode_strings(g['strings']),'OBJE':encode_objects(g['objects'])})


def verify_menu(root,compiled,source=None):
    menu=compiled.get('menu')
    if not menu:return None
    from .campaign_identity import campaign_identity
    from .bruderkrieg import _payloads
    from .tgv import read_texture
    from .event_images import compare_event_pixels
    root=Path(root)
    relative=str(Path(menu['asset']).relative_to('GameData').with_suffix('.tgv')).replace('\\','/')
    asset=root/'Gen/PC/Texture'/relative
    pixels,header=read_texture(asset.read_bytes())
    if list(pixels.size)!=menu['render_size'] or header['format']!='A8B8G8R8_LIN':raise ValueError('Campaign menu map texture differs')
    declared=(root/'Gen/DeclaredFiles.txt').read_text(encoding='utf-8').splitlines()
    if declared.count('ZZ:/PC/Texture/'+relative)!=1:raise ValueError('Campaign menu map is not declared exactly once')
    if source:
        with Image.open(safe_child(Path(source),menu['image'])) as original:
            compare_event_pixels(original.convert('RGBA').resize(tuple(menu['render_size']),Image.Resampling.LANCZOS),pixels)
    scenario=campaign_identity(compiled)['scenario']
    definition=root/'Scenarios'/f'{scenario}_Definition.dat'
    if definition.is_file():
        payload=next(v for k,v in _payloads(definition.read_bytes()).items() if '/MapConfiguration/' in k and k.endswith('ndfbin'))
        _,g=decode(payload)
        info,=[o for o in g['objects'] if o['class']=='TStrategicMapInfo']
        fields={p['property_name']:p['value'] for p in info['properties']}
        reference=next(p['value'] for p in fields['DescriptionTextureElements']['items'] if p['key']['value']=='MapTexture_AG')
        filename=next(p['value']['value'] for p in g['objects'][reference['object_id']]['properties'] if p['property_name']=='FileName')
        if filename!=menu['asset'].replace('GameData/','GameData:/',1):raise ValueError('Campaign menu still uses the template map')
        from .bruderkrieg import authored_text_key
        for p in fields['DescriptionTextElements']['items']:
            if p['value']['value_hex']!=authored_text_key(compiled['campaign']['id'],'menu',p['key']['value']).hex():
                raise ValueError('Campaign menu text still uses the template metadata')
        if fields['LobbyLeftSideAlliance']['value']!=1:raise ValueError('Campaign lobby coalition ordering changed')
        if (fields['Name']['value_hex']!=authored_text_key(compiled['campaign']['id'],'menu','MissionName').hex()
                or fields['ShortName']['value_hex']!=authored_text_key(compiled['campaign']['id'],'menu','short_title').hex()):
            raise ValueError('Campaign menu title formatting or short title was lost')
    return {'custom_map':True,'size':menu['render_size'],'attacker':menu['attacker'],'native_lobby_left':'nato','briefing_fields_isolated':True}
