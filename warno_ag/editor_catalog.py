"""Read-only verified unit catalog adapter for the external editor."""
from __future__ import annotations

import json
from pathlib import Path

from .visual_catalog import build_visual_catalog
from .modgen import strategic_pack_signatures


def discover_editor_catalog(base_root, mod_roots=()):
    base_root = Path(base_root).resolve()
    base = _catalog(base_root, 'base_game', base_root.name)
    mods = [_catalog(Path(root).resolve(), 'local_mod', Path(root).name,
                     enabled_by_default=False) for root in mod_roots]
    return {
        'format': 'agf-editor-catalog-v1',
        'enabled_sources': ['base_game'],
        'base_game': base,
        'mods': mods,
        'scope': 'verified descriptors with resolved strategic visual mesh and icon registration',
        'runtime_verified': False,
    }


def _catalog(root, source, name, *, enabled_by_default=True):
    try:
        catalog = build_visual_catalog(root)
    except (OSError, ValueError) as error:
        return {'name': name, 'source': source, 'root': str(root),
                'enabled_by_default': enabled_by_default, 'status': 'unavailable',
                'entries': [], 'error': str(error)}
    entries = []
    signatures = strategic_pack_signatures() if source == 'base_game' else {}
    for identifier, visual in sorted(catalog.items()):
        strategic_pack_id = next((name.removeprefix('Descriptor_StrategicPack_')
                                  for name, value in signatures.items()
                                  if value.get('unit') in {'Descriptor_Unit_' + identifier,
                                                           '$/GFX/Unit/Descriptor_Unit_' + identifier}), None)
        entries.append({
            'id': identifier,
            'display_name': identifier,
            'source': source,
            'is_verified': True,
            'icon_path': visual['texture'],
            'mesh': visual['mesh'],
            'category': visual['category'],
            'tags': visual['tags'],
            'strategic_pack_id': strategic_pack_id,
        })
    return {'name': name, 'source': source, 'root': str(root),
            'enabled_by_default': enabled_by_default, 'status': 'verified',
            'entries': entries}


def write_editor_catalog(base_root, output, mod_roots=()):
    report = discover_editor_catalog(base_root, mod_roots)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report
