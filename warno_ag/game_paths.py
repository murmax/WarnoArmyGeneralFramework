"""Resolve local authoring inputs without requiring the default Steam library."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def game_root():
    explicit = os.environ.get('WARNO_GAME_ROOT')
    if explicit:
        return Path(explicit).expanduser().resolve()
    receipt = ROOT / 'artifacts/modgen-201602-template/agf-template-receipt.json'
    if receipt.is_file():
        data = json.loads(receipt.read_text(encoding='utf-8'))
        archive = Path(data['source'])
        if archive.name == 'base.zip' and archive.parent.name == 'ModData' and archive.parent.parent.name == 'Mods':
            return archive.parent.parent.parent.resolve()
        raise ValueError('Prepared game-template receipt has an unexpected source path')
    return Path('C:/Program Files (x86)/Steam/steamapps/common/WARNO')


def compatibility_root():
    current = ROOT / 'artifacts/compatibility'
    historical = ROOT / 'artifacts/full-campaign-work/RedLine1989-v12'
    return current if current.exists() or not historical.exists() else historical
