"""A bounded strategic briefing panel with independent picture and text frames."""
from pathlib import Path
import re
import yaml
from .cndf import decode

TEMPLATES = 'GameData/UserInterface/Use/Strategic/UIStrategicLDHintTemplates.ndf'
RESOURCES = 'GameData/UserInterface/Use/Strategic/UIStrategicLDHint_ressources.ndf'

FLOW_LAYOUT = '''
template AGF_BriefingSlideV2 [] is BUCKContainerDescriptor
(
    ComponentFrame = TUIFramePropertyRTTI(RelativeWidthHeight = [1.0,1.0])
    PointerEventsToAllow = ~/EAllowablePointerEventType/Move | ~/EAllowablePointerEventType/Button3 | ~/EAllowablePointerEventType/Scroll
    Components = [ BUCKContainerDescriptor
    (
        ComponentFrame = TUIFramePropertyRTTI(RelativeWidthHeight=[1.0,0.0] AlignementToFather=[0.5,0.5] AlignementToAnchor=[0.5,0.5])
        Components = [ BUCKListDescriptor
        (
            Axis=~/ListAxis/Vertical
            ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[1348.0,0.0] AlignementToFather=[0.5,0.5] AlignementToAnchor=[0.5,0.5])
            BreadthComputationMode=~/BreadthComputationMode/ComputeBreadthFromFrameProperty
            Elements = [
                BUCKListElementDescriptor(ComponentDescriptor=BUCKTextDescriptor
                (
                    ElementName="Text2"
                    ComponentFrame=TUIFramePropertyRTTI(RelativeWidthHeight=[1.0,0.0] MagnifiableWidthHeight=[0.0,68.0])
                    ParagraphStyle=TParagraphStyle(Alignment=UIText_Center VerticalAlignment=UIText_VerticalCenter)
                    TextStyle="Default" HorizontalFitStyle=~/FitStyle/UserDefined VerticalFitStyle=~/FitStyle/UserDefined
                    TypefaceToken="Eurostyle" TextSize="26" TextColor="SM_LDhint_texte" BigLineAction=~/BigLineAction/BalancedMultiline
                    TextDico=~/LocalisationConstantes/dico_dialogues
                )),
                BUCKListElementDescriptor(ComponentDescriptor=BUCKContainerDescriptor
                (
                    ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[1348.0,500.0])
                    Components=[
                        BUCKTextureDescriptor
                        (
                            ElementName="Texture1" AdaptContainerToTextureSize=False ClipTextureToComponent=True
                            ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[700.0,394.0] MagnifiableOffset=[20.0,53.0])
                            TextureFrame=TUIFramePropertyRTTI(RelativeWidthHeight=[1.0,1.0])
                        ),
                        BUCKTextDescriptor
                        (
                            ElementName="Text1"
                            ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[588.0,464.0] MagnifiableOffset=[740.0,18.0])
                            ParagraphStyle=TParagraphStyle(Alignment=UIText_Left VerticalAlignment=UIText_VerticalCenter InterLine=0.1)
                            TextStyle="Default" HorizontalFitStyle=~/FitStyle/UserDefined VerticalFitStyle=~/FitStyle/UserDefined
                            TypefaceToken="Eurostyle" TextSize="20" TextColor="SM_LDhint_texte" BigLineAction=~/BigLineAction/BalancedMultiline
                            TextDico=~/LocalisationConstantes/dico_dialogues
                        )]
                )),
                BUCKListElementDescriptor(ComponentDescriptor=LDHintDefaultButtonList
                (InterItemMarginAsFloat=~/LDHintMagnifiableInterButtonMargin BladeDescriptor=LDHintGreenButton())),
                BUCKListElementSpacer(Magnifiable=16.0)
            ]
            BackgroundComponents=[PanelRoundedCorner(Radius=8 BackgroundBlockColorToken='SM_LDhint_fond' BorderLineColorToken='SM_LDhint_texte' BorderThicknessToken='2')]
        )]
    )]
)
'''

LAYOUT = '''
template AGF_BriefingSlide [] is BUCKContainerDescriptor
(
    ComponentFrame = TUIFramePropertyRTTI(RelativeWidthHeight = [1.0, 1.0])
    PointerEventsToAllow = ~/EAllowablePointerEventType/Move | ~/EAllowablePointerEventType/Button3 | ~/EAllowablePointerEventType/Scroll
    Components = [ BUCKContainerDescriptor
    (
        ComponentFrame = TUIFramePropertyRTTI
        (
            MagnifiableWidthHeight = [1400.0, 800.0]
            AlignementToFather = [0.5, 0.5]
            AlignementToAnchor = [0.5, 0.5]
        )
        Components = [
            PanelRoundedCorner(Radius = 8 BackgroundBlockColorToken = 'SM_LDhint_fond' BorderLineColorToken = 'SM_LDhint_texte' BorderThicknessToken = '2' RoundedVertexes = [true,true,true,true]),
            BUCKTextureDescriptor
            (
                ElementName = "Texture1"
                AdaptContainerToTextureSize = False
                ClipTextureToComponent = True
                ComponentFrame = TUIFramePropertyRTTI
                (
                    MagnifiableWidthHeight = [740.0, 416.0]
                    MagnifiableOffset = [28.0, 150.0]
                    AlignementToFather = [0.0, 0.0]
                    AlignementToAnchor = [0.0, 0.0]
                )
                TextureFrame = TUIFramePropertyRTTI(RelativeWidthHeight = [1.0, 1.0])
            ),
            BUCKTextDescriptor
            (
                ElementName = "Text2"
                ComponentFrame = TUIFramePropertyRTTI
                (
                    MagnifiableWidthHeight = [1344.0, 64.0]
                    MagnifiableOffset = [28.0, 24.0]
                    AlignementToFather = [0.0, 0.0]
                    AlignementToAnchor = [0.0, 0.0]
                )
                ParagraphStyle = TParagraphStyle(Alignment = UIText_Center VerticalAlignment = UIText_VerticalCenter BigWordAction = ~/BigWordAction/BigWordNewLine InterLine = 0.0)
                TextStyle = "Default"
                HorizontalFitStyle = ~/FitStyle/UserDefined
                VerticalFitStyle = ~/FitStyle/UserDefined
                TypefaceToken = "Eurostyle"
                BigLineAction = ~/BigLineAction/BalancedMultiline
                TextColor = "SM_LDhint_texte"
                TextSize = "26"
                TextDico = ~/LocalisationConstantes/dico_dialogues
            ),
            BUCKTextDescriptor
            (
                ElementName = "Text1"
                ComponentFrame = TUIFramePropertyRTTI
                (
                    MagnifiableWidthHeight = [584.0, 548.0]
                    MagnifiableOffset = [788.0, 112.0]
                    AlignementToFather = [0.0, 0.0]
                    AlignementToAnchor = [0.0, 0.0]
                )
                ParagraphStyle = TParagraphStyle(Alignment = UIText_Left VerticalAlignment = UIText_VerticalCenter BigWordAction = ~/BigWordAction/BigWordNewLine InterLine = 0.1)
                TextStyle = "Default"
                HorizontalFitStyle = ~/FitStyle/UserDefined
                VerticalFitStyle = ~/FitStyle/UserDefined
                TypefaceToken = "Eurostyle"
                BigLineAction = ~/BigLineAction/BalancedMultiline
                TextColor = "SM_LDhint_texte"
                TextSize = "20"
                TextDico = ~/LocalisationConstantes/dico_dialogues
            ),
            BUCKContainerDescriptor
            (
                ComponentFrame = TUIFramePropertyRTTI
                (
                    MagnifiableWidthHeight = [1344.0, 44.0]
                    MagnifiableOffset = [28.0, 722.0]
                    AlignementToFather = [0.0, 0.0]
                    AlignementToAnchor = [0.0, 0.0]
                )
                Components = [ LDHintDefaultButtonList
                (
                    InterItemMarginAsFloat = ~/LDHintMagnifiableInterButtonMargin
                    BladeDescriptor = LDHintGreenButton()
                ) ]
            )
        ]
    ) ]
)
'''


def stage_cinematic_layout(source, workspace):
    path = Path(source) / 'cinematics.yaml'
    if not path.is_file() or yaml.safe_load(path.read_text(encoding='utf-8')).get('layout') != 'briefing':
        return {'staged':False}
    workspace = Path(workspace)
    version=yaml.safe_load(path.read_text(encoding='utf-8')).get('layout_version',1)
    name='AGF_BriefingSlideV2' if version==2 else 'AGF_BriefingSlide'
    target = workspace / TEMPLATES
    body = target.read_text(encoding='utf-8')
    if version==2:
        start=body.index('template ST_Popup_1Texture_5Text')
        end=body.index('template Steelman_newLDHINT',start)
        choice=body[start:end].replace('ST_Popup_1Texture_5Text','AGF_GraphicCardsV2').replace('VertiscalListStrategicChoice_text()','AGF_ChoiceOverlay()')
        extras='''
template AGF_ChoiceButton [] is BUCKButtonDescriptor
(
    ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[633.0,471.0])
    Mapping=TEugBMutablePBaseClass(Value=TUserInputMapping(KeyboardEventID=UserInputKeyboard/KEY_ENTER))
    LeftClickSound=~/SoundEvent_SteelmanChoiceButton
    HasBorder=True BorderThicknessToken="5" BorderLineColorToken="bouton_strategic_choice" BordersToDraw=~/TBorderSide/All
    Components=[BUCKTextDescriptor
    (
        ElementName="LDHintDefaultButtonTextElement"
        ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[633.0,54.0] MagnifiableOffset=[0.0,282.0])
        ParagraphStyle=paragraphStyleTextCenter TextStyle="Default" HorizontalFitStyle=~/FitStyle/UserDefined VerticalFitStyle=~/FitStyle/UserDefined
        TypefaceToken="Eurostyle" TextSize="18" TextColor="SM_paleSilver" BigLineAction=~/BigLineAction/MultiLine
        TextDico=~/LocalisationConstantes/dico_interface_ingame
    )]
)
template AGF_ChoiceOverlay [] is BUCKContainerDescriptor
(
    ComponentFrame=TUIFramePropertyRTTI(RelativeWidthHeight=[1.0,1.0])
    Components=[BUCKContainerDescriptor
    (
        ComponentFrame=TUIFramePropertyRTTI(RelativeWidthHeight=[1.0,0.0] MagnifiableOffset=[0.0,91.0])
        Components=[LDHintDefaultButtonList(InterItemMarginAsFloat=20.0 BladeDescriptor=AGF_ChoiceButton())]
    )]
)
'''
        # Independent localized titles/descriptions sit above the transparent
        # native buttons, whose full 633px width matches the actual cards.
        overlay=extras.rfind('    )]\n)')
        texts=[]
        for element,offset,size in [('Text2',[56,111],24),('Text3',[56,467],16),('Text4',[709,111],24),('Text5',[709,467],16)]:
            texts.append('BUCKTextDescriptor(ElementName="'+element+'" TextStyle="Default" TypefaceToken="Eurostyle" TextSize="'+str(size)+'" TextColor="SM_paleSilver" TextDico=~/LocalisationConstantes/dico_dialogues '
                'HorizontalFitStyle=~/FitStyle/UserDefined VerticalFitStyle=~/FitStyle/UserDefined BigLineAction=~/BigLineAction/BalancedMultiline '
                'ParagraphStyle=paragraphStyleTextCenter ComponentFrame=TUIFramePropertyRTTI(MagnifiableWidthHeight=[583.0,70.0] MagnifiableOffset=['+str(offset[0])+','+str(offset[1])+']))')
        extras=extras[:overlay]+'    ),\n        '+',\n        '.join(texts)+'\n    ]\n)\n'
        body+='\n'+choice+'\n'+extras
    if 'template AGF_BriefingSlide' in body:
        raise ValueError('Briefing panel already exists in compiler workspace')
    target.write_text(body + '\n' + (FLOW_LAYOUT if version==2 else LAYOUT), encoding='utf-8')
    resource = workspace / RESOURCES
    body = resource.read_text(encoding='utf-8')
    pattern = r'(\(\s*"ST_Component_1Texture_1Text"\s*,[^\n]+)'
    body, count = re.subn(pattern, r'\1\n        ( "'+name+'", '+name+'() ),', body, count=1)
    if version==2:
        body=body.replace('( "'+name+'", '+name+'() ),','( "'+name+'", '+name+'() ),\n        ( "AGF_GraphicCardsV2", AGF_GraphicCardsV2() ),',1)
    if count != 1:
        raise ValueError('Strategic panel registration shell is absent')
    resource.write_text(body, encoding='utf-8')
    return {'staged':True, 'panel':[1400,800], 'image':[740,416], 'body':[584,548]}


def verify_cinematic_layout(gen, compiled, *, require_graphic_caption_bounds=False):
    if compiled.get('cinematics', {}).get('layout') != 'briefing':
        return None
    _, graph = decode((Path(gen) / 'NDF/UI/Components.ndfbin').read_bytes())
    name='AGF_BriefingSlideV2' if compiled['cinematics'].get('layout_version')==2 else 'AGF_BriefingSlide'
    matches = []
    for obj in graph['objects']:
        if obj['class'] != 'TUICommonLDHintResource':
            continue
        for prop in obj['properties']:
            if prop['property_name'] == 'ComponentByName':
                matches += [pair['value'] for pair in prop['value']['items'] if pair['key'].get('value') == name]
    if len(matches) != 1 or graph['objects'][matches[0]['object_id']]['class'] != 'TBUCKContainerDescriptor':
        raise ValueError('Bounded briefing panel registration is missing or ambiguous')
    objects = graph['objects']
    def field(obj, name):
        return next(p['value'] for p in obj['properties'] if p['property_name'] == name)
    root = objects[matches[0]['object_id']]
    if name=='AGF_BriefingSlideV2':
        wrapper=objects[field(root,'Components')['items'][0]['object_id']]
        frame=objects[field(wrapper,'ComponentFrame')['object_id']]
        if field(frame,'RelativeWidthHeight')['value']!=[1.0,0.0]:raise ValueError('Briefing flow lost native centering wrapper')
        panel=objects[field(wrapper,'Components')['items'][0]['object_id']]
        if panel['class']!='TBUCKListDescriptor':raise ValueError('Briefing flow lost its native list container')
        report = {'registered':True,'component':name,'native_flow_centering':True,
                  'picture_text_separated':True,'picture_resizing_disabled':True}
        if not require_graphic_caption_bounds:
            return report
        card_roots = [pair['value']['object_id'] for obj in objects
                      if obj['class'] == 'TUICommonLDHintResource'
                      for prop in obj['properties'] if prop['property_name'] == 'ComponentByName'
                      for pair in prop['value']['items']
                      if pair['key'].get('value') == 'AGF_GraphicCardsV2']
        if len(card_roots) != 1:
            raise ValueError('Graphic-card component registration differs')
        from .bruderkrieg import _reachable_objects
        named = {}
        for oid in _reachable_objects(graph, card_roots[0]):
            obj = objects[oid]
            element = next((p['value'].get('value') for p in obj['properties']
                            if p['property_name'] == 'ElementName'), None)
            if element in ('Text2', 'Text3', 'Text4', 'Text5'):
                if element in named:
                    raise ValueError('Graphic-card caption is duplicated')
                named[element] = obj
        # Fresh builds must use bounded frames; old bundles retain their
        # historical verification contract unless the caller opts in.
        for element, offset in {'Text2':[56,111], 'Text3':[56,467],
                                'Text4':[709,111], 'Text5':[709,467]}.items():
            if element not in named:
                raise ValueError('Graphic-card caption is missing: ' + element)
            frame = objects[field(named[element], 'ComponentFrame')['object_id']]
            if (named[element]['class'] != 'TBUCKTextDescriptor'
                    or field(frame, 'MagnifiableWidthHeight')['value'] != [583,70]
                    or field(frame, 'MagnifiableOffset')['value'] != offset):
                raise ValueError('Graphic-card caption exceeds its bounded card: ' + element)
        return {**report, 'graphic_caption_bounds_checked':True}
    panel = objects[field(root, 'Components')['items'][0]['object_id']]
    frame = objects[field(panel, 'ComponentFrame')['object_id']]
    if field(frame, 'MagnifiableWidthHeight')['value'] != [1400.0, 800.0]:
        raise ValueError('Briefing panel has an unbounded or changed frame')
    children = [objects[r['object_id']] for r in field(panel,'Components')['items']]
    named = {field(o,'ElementName')['value']:o for o in children
             if any(p['property_name']=='ElementName' for p in o['properties'])}
    expected = {'Texture1':([740,416],[28,150]),'Text1':([584,548],[788,112]),'Text2':([1344,64],[28,24])}
    for name,(size,offset) in expected.items():
        if name not in named:
            raise ValueError('Briefing panel lost its picture or text field')
        frame = objects[field(named[name],'ComponentFrame')['object_id']]
        if (field(frame,'MagnifiableWidthHeight')['value'] != size
                or field(frame,'MagnifiableOffset')['value'] != offset):
            raise ValueError('Briefing panel picture and text frames changed')
    # CNDF omits the native false default; the template's former true setting
    # produced an explicit property. Missing here is therefore false.
    resize = next((p['value']['value'] for p in named['Texture1']['properties']
                   if p['property_name']=='AdaptContainerToTextureSize'), False)
    if resize:
        raise ValueError('Briefing picture can resize the bounded panel')
    return {'registered':True, 'component':'AGF_BriefingSlide', 'panel':[1400,800],
            'picture_text_separated':True,'picture_resizing_disabled':True}
