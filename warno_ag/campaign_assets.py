"""Attach explicit world/event recipes to immutable authored campaign builds."""
import json
from pathlib import Path

from .event_images import verify_cooked_event_images
from .storage import safe_child, sha256
from .world_assets import load_world_asset_recipe, validate_world_recipe


def validate_asset_bindings(compiled):
    assets = compiled.get('assets', {})
    if not isinstance(assets, dict) or set(assets) - {'world', 'event_images'}:
        raise ValueError('Unsupported campaign asset recipe')
    if 'world' in assets:
        contract = compiled['adapter'].get('strategic_map')
        if contract is None:
            raise ValueError('World assets require an independent strategic map contract')
        validate_world_recipe(assets['world'], contract)
    private_tokens = {event['adapter_image'] for event in compiled['events']
                      if isinstance(event.get('adapter_image'), str)
                      and event['adapter_image'].startswith('AGF_EVT_')}
    manifest = assets.get('event_images')
    if manifest is None:
        if private_tokens:
            raise ValueError('Private event-image tokens require a declared asset recipe')
        return assets
    if manifest.get('format') != 'agf-event-images-compiled-v1':
        raise ValueError('Unsupported campaign event-image manifest')
    tokens = [record['token'] for record in manifest['images']]
    if len(set(tokens)) != len(tokens) or not private_tokens <= set(tokens):
        raise ValueError('Campaign private event-image token bindings mismatch')
    return assets


def attach_campaign_assets(compiled, *, world_source=None, event_images=None):
    assets = {}
    if world_source is not None:
        contract = compiled['adapter'].get('strategic_map')
        if contract is None:
            raise ValueError('World assets require an independent strategic map contract')
        assets['world'] = load_world_asset_recipe(world_source, contract)
    if event_images is not None:
        assets['event_images'] = json.loads((Path(event_images) / 'event-images.compiled.json').read_text(
            encoding='utf-8'))
    if assets:
        compiled['assets'] = assets
    validate_asset_bindings(compiled)
    return assets


def write_candidate_asset_metadata(root, compiled):
    assets = validate_asset_bindings(compiled)
    if 'event_images' in assets:
        target = Path(root) / 'event-images.compiled.json'
        if target.exists():
            raise ValueError('Candidate already contains event-image metadata')
        target.write_text(json.dumps(assets['event_images'], ensure_ascii=False, indent=2) + '\n',
                          encoding='utf-8')


def stage_candidate_event_images(root, compiled, staged):
    """Carry private source art into the candidate checked against cooked pixels."""
    assets = validate_asset_bindings(compiled)
    if 'event_images' not in assets:
        if staged is not None:
            raise ValueError('Staged event artwork has no compiled campaign recipe')
        return []
    if staged is None:
        raise ValueError('Compiled campaign event artwork requires staged source images')
    root, staged = Path(root).resolve(), Path(staged).resolve()
    records = assets['event_images']['images']
    prepared = []
    for record in records:
        relative = record['asset']
        if not relative.startswith('GameData/Assets/2D/Interface/UseStrategic/AGFEvents/'):
            raise ValueError('Event artwork target is outside the private image directory')
        source, target = safe_child(staged, relative), safe_child(root, relative)
        if not source.is_file() or target.exists():
            raise ValueError('Private event artwork missing or colliding: ' + relative)
        raw = source.read_bytes()
        if sha256(raw) != record['asset_sha256']:
            raise ValueError('Private event artwork changed after compilation: ' + relative)
        prepared.append((target, raw))
    for target, raw in prepared:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return [str(target.relative_to(root)).replace('\\', '/') for target, _ in prepared]


def validate_candidate_assets(root, compiled):
    root = Path(root)
    assets = validate_asset_bindings(compiled)
    metadata = root / 'event-images.compiled.json'
    if 'event_images' not in assets:
        if metadata.exists():
            raise ValueError('Candidate contains undeclared event-image metadata')
        return {}
    if not metadata.is_file() or json.loads(metadata.read_text(encoding='utf-8')) != assets['event_images']:
        raise ValueError('Candidate event-image metadata differs from compiled recipe')
    return {'event_images': verify_cooked_event_images(root, root / 'Gen')}
