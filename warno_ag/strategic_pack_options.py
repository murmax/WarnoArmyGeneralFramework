"""Verified tactical transports for a public Army General unit pack."""
from pathlib import Path
import re

from .modgen import is_tactical_transport
from .visual_catalog import current_visual_catalog


RULES = (Path(__file__).resolve().parents[1] /
         'artifacts/modgen-201602-template/GameData/Generated/Gameplay/Decks/DivisionRules.ndf')


def strategic_pack_options(unit_id, transport=None):
    catalog = current_visual_catalog()
    if not isinstance(unit_id,str) or unit_id not in catalog:
        raise ValueError('Choose a verified tactical game unit')
    if transport is not None and (not isinstance(transport,str) or transport not in catalog
                                  or not is_tactical_transport(transport)):
        raise ValueError('Choose a verified game transport rather than a combat-only vehicle')
    source = RULES.read_text(encoding='utf-8')
    found = []
    for match in re.finditer(r'(?m)^Descriptor_Deck_Division_(\w+)_Rule is TDeckDivisionRule\s*$',source):
        end = source.find('\nDescriptor_Deck_Division_',match.end())
        region = source[match.end():end if end >= 0 else len(source)]
        for rule in re.findall(r'TDeckUniteRule\s*\((.*?)\n\s*\),',region,re.S):
            unit = re.search(r'UnitDescriptor\s*=\s*\$/GFX/Unit/Descriptor_Unit_(\w+)',rule)
            if unit is None or unit.group(1) != unit_id:
                continue
            raw = re.search(r'AvailableTransportList\s*=\s*\[(.*?)\]',rule,re.S)
            transports = re.findall(r'Descriptor_Unit_(\w+)',raw.group(1)) if raw else []
            found.append({'division':match.group(1),
                          'without_transport':bool(re.search(r'AvailableWithoutTransport\s*=\s*True',rule)),
                          'transports':transports})
    recommended = sorted({value for rule in found for value in rule['transports']
                          if value in catalog and is_tactical_transport(value)})
    return {'unit':unit_id,'category':catalog[unit_id]['category'],
            'verified_transport':transport,
            'recommended_transports':recommended,
            'stock_rules':found,
            'matches_stock_rule':(transport is None and any(rule['without_transport'] for rule in found)
                                  or transport is not None and transport in recommended),
            'runtime_verified':False}
