"""Strict optional campaign translations, separate from RU/EN authoring fields."""
import copy
import re

NATIVE_LOCALES = {'DEV':'en','US':'en','RU':'ru','FR':'fr','GER':'de',
                  'SPA':'es','POL':'pl','SC':'zh'}
SUPPORTED_LOCALES = set(NATIVE_LOCALES.values())


def locale(value):
    result=NATIVE_LOCALES.get(value,value)
    if result not in SUPPORTED_LOCALES:
        raise ValueError('Unknown campaign locale: '+str(value))
    return result


def translate(compiled, text, language):
    language=locale(language)
    if not text or language=='ru':
        return text
    catalog=compiled.get('localisation',{}).get('translations',{})
    if language=='en':
        return catalog.get('en',{}).get(text,text)
    if language not in catalog:
        return text  # Legacy campaigns explicitly retain their EN fallback.
    values=catalog[language]
    if text in values:
        return values[text]
    # Native event presentations concatenate separately authored paragraphs.
    if '\n' in text:
        return '\n'.join(translate(compiled,part,language) for part in text.split('\n'))
    raise ValueError('Missing '+language+' campaign translation: '+repr(text))


def field(compiled, value, language):
    language=locale(language)
    return value['ru'] if language=='ru' else translate(compiled,value['en'],language)


def bilingual_strings(value):
    if isinstance(value,dict):
        if set(value)=={'ru','en'} and all(isinstance(v,str) for v in value.values()):
            yield value['en']
        else:
            for key,child in value.items():
                if key!='voice_script':yield from bilingual_strings(child)
    elif isinstance(value,list):
        for child in value:yield from bilingual_strings(child)


def ui_name_fields(compiled):
    """Names displayed by WARNO's 30 UTF-16-unit editable OOB widgets."""
    for battalion in compiled.get('battalions', []):
        oob = battalion.get('oob', {})
        prefix = 'battalion ' + battalion['id']
        for kind, item in (('name', oob),
                           ('organization', oob.get('organization', {})),
                           ('division', oob.get('division_definition', {})),
                           ('command', oob.get('command', {}))):
            if 'localized_name' in item:
                yield prefix + '.' + kind, item['localized_name']
        for index, company in enumerate(oob.get('companies', [])):
            path = f'{prefix}.company[{index}]'
            if 'localized_name' in company:
                yield path, company['localized_name']
            for number, platoon in enumerate(company.get('platoons', [])):
                if 'localized_name' in platoon:
                    yield f'{path}.platoon[{number}]', platoon['localized_name']


def validate_ui_names(compiled):
    """Validate resolved names, including translations and legacy EN fallbacks.

    Narrative/event/map text uses different UI controls and is not truncated.
    Report the exact field and locale so authors can supply a real abbreviation.
    """
    from .modgen import MAX_UI_TEXT_UNITS, _ui_text
    for path, value in ui_name_fields(compiled):
        for language in sorted(SUPPORTED_LOCALES):
            text = field(compiled, value, language)
            if not _ui_text(text):
                units = len(text.encode('utf-16-le')) // 2
                raise ValueError(
                    f'{path} [{language}] UI name requires 1..{MAX_UI_TEXT_UNITS} '
                    f'UTF-16 units; got {units}: {text!r}')


def compile_localisation(document, compiled):
    if (not isinstance(document,dict) or set(document)!={'schema','source_language','translations'}
            or document['schema']!=1 or document['source_language']!='en'
            or not isinstance(document['translations'],dict)):
        raise ValueError('localization.yaml requires schema=1, source_language=en and translations')
    result=copy.deepcopy(document)
    for language,values in result['translations'].items():
        if language not in SUPPORTED_LOCALES-{'ru'} or not isinstance(values,dict):
            raise ValueError('Invalid campaign translation language/table')
        for source,target in values.items():
            if (not isinstance(source,str) or not source or not isinstance(target,str) or not target.strip()
                    or '\x00' in target or len(target)>20000):
                raise ValueError('Invalid campaign translation entry')
            if sorted(re.findall(r'%\d+',source))!=sorted(re.findall(r'%\d+',target)):
                raise ValueError('Campaign translation changes native placeholder: '+source)
            if re.findall(r'#(?:US|SOV)\b',source)!=re.findall(r'#(?:US|SOV)\b',target):
                raise ValueError('Campaign translation changes coalition markup')
    temporary={**compiled,'localisation':result}
    from .bruderkrieg import _authored_text_base
    required=set(bilingual_strings(compiled)) | set(_authored_text_base(compiled,'en').values())
    for language in result['translations']:
        if language=='en':continue
        for text in required:
            translate(temporary,text,language)
    validate_ui_names(temporary)
    return result
