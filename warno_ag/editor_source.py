"""Read public source documents for the editor without compiling or modifying them.

JSON is only a transport between the existing strict YAML reader and the .NET
editor. No inferred defaults, adapter resolution or language reduction belongs
at this boundary: the editor must receive every source value.
"""
import math
from pathlib import Path, PurePosixPath

from .authoring import _read_yaml
from .storage import sha256


def _json_value(value, where, active=None, depth=0):
    active = set() if active is None else active
    if depth > 100:
        raise ValueError('Source document nesting limit exceeded: ' + where)
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) not in (list, dict):
        raise ValueError('Unsupported source scalar type or nonfinite number: ' + where)
    if id(value) in active:
        raise ValueError('Recursive YAML aliases are unsupported: ' + where)
    active.add(id(value))
    try:
        if isinstance(value, list):
            return [_json_value(item, f'{where}[{i}]', active, depth + 1)
                    for i, item in enumerate(value)]
        if any(type(key) is not str for key in value):
            raise ValueError('Source mapping keys must be strings: ' + where)
        return {key: _json_value(item, where + '.' + key, active, depth + 1)
                for key, item in value.items()}
    finally:
        active.remove(id(value))


def _confined(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or ':' in relative or PurePosixPath(relative).is_absolute()
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('Asset must use a confined relative path')
    result = (root / relative).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Source asset escapes its source directory')
    return result


def read_editor_source(source, profile=None):
    root = Path(source).resolve()
    if not (root / 'campaign.yaml').is_file():
        raise ValueError('Select a campaign source directory containing campaign.yaml')
    if profile is None:
        local = root / 'profile.yaml'
        if local.is_file():
            profile = local
        else:
            template_id = _read_yaml(root / 'campaign.yaml').get('template')
            candidates = [path for path in (Path(__file__).resolve().parents[1] / 'profiles').glob('*.yaml')
                          if _read_yaml(path).get('id') == template_id]
            if len(candidates) != 1:
                raise ValueError('Select the map profile for this campaign; no unique matching profile was found')
            profile = candidates[0]
    profile_path = Path(profile).resolve()
    documents, hashes = {}, {}
    for path in sorted(root.rglob('*.yaml')):
        if not path.resolve().is_relative_to(root):
            raise ValueError('Source document escapes its source directory')
        if path.resolve() == profile_path:
            continue
        relative = path.relative_to(root).as_posix()
        documents[relative] = _json_value(_read_yaml(path), relative)
        hashes[relative] = sha256(path.read_bytes())
    profile_document = _json_value(_read_yaml(profile_path), 'profile')
    assets = {}

    def asset(relative, role):
        path = _confined(root, relative)
        if not path.is_file():
            raise ValueError('Missing imported source asset: ' + relative)
        assets[relative] = {'path': relative, 'sourcePath': str(path),
                            'sha256': sha256(path.read_bytes()), 'role': role}

    world = documents.get('world.yaml')
    if world:
        for section in ('heightmap', 'surface'):
            specification = world.get(section)
            if isinstance(specification, dict) and 'file' in specification:
                asset(specification['file'], section)
    event_images = documents.get('event-images.yaml')
    if event_images:
        images = event_images.get('images')
        if not isinstance(images, dict):
            raise ValueError('Event images must be a mapping')
        for relative in images.values():
            asset(relative, 'event-image')
    emblems = documents.get('emblems.yaml')
    menu = documents.get('campaign.yaml',{}).get('menu')
    if menu:
        asset(menu['image'], 'campaign-menu')
    if emblems:
        for item in emblems.get('emblems', []):
            if not isinstance(item, dict) or not isinstance(item.get('image'), str):
                raise ValueError('Emblem asset declaration is invalid')
            asset(item['image'], 'division-emblem')
    if (root / 'ASSET_CREDITS.md').is_file():
        asset('ASSET_CREDITS.md', 'artwork-credits')
    if (root / 'artwork/emblems/SOURCES.json').is_file():
        asset('artwork/emblems/SOURCES.json', 'artwork-provenance')
    if documents.get('campaign.yaml', {}).get('schema') == 'agf-native-campaign/v1':
        from .native_campaign_source import verify_native_snapshot
        if profile_document.get('schema') != 'agf-native-profile/v1':
            raise ValueError('Native campaign requires its native source profile')
        native = profile_document.get('nativeSource')
        if not isinstance(native, dict):
            raise ValueError('Native source adapter is missing')
        manifest_path = _confined(root, native['manifestPath'])
        verify_native_snapshot(manifest_path.parent)
        for entry in native['assets']:
            relative = entry['sourcePath']
            asset(relative, entry['role'])
            if assets[relative]['sha256'] != entry['sha256']:
                raise ValueError('Native editor source asset hash changed: ' + relative)
        terrain = documents['world.yaml']['world']['terrain']
        for field, role in (('heightmapPath', 'heightmap'), ('surfacePath', 'surface')):
            if terrain.get(field):
                asset(terrain[field], role)
    preview = None
    reference = root / 'editor-preview/reference.json'
    if reference.is_file():
        import json
        preview = _json_value(json.loads(reference.read_text(encoding='utf-8')), 'editor-preview/reference.json')
        if (not isinstance(preview, dict) or preview.get('format') != 'agf-editor-game-reference/v1'
                or preview.get('preview_only') is not True or not isinstance(preview.get('files'), list)):
            raise ValueError('Unsupported editor map reference')
        seen = set()
        for item in preview['files']:
            if (not isinstance(item, dict) or set(item) != {'path', 'sha256', 'role'}
                    or not isinstance(item['sha256'], str) or len(item['sha256']) != 64
                    or item['path'] in seen):
                raise ValueError('Invalid editor map reference asset')
            seen.add(item['path'])
            asset(item['path'], item['role'])
            if assets[item['path']]['sha256'] != item['sha256']:
                raise ValueError('Editor map reference asset hash changed: ' + item['path'])
        asset('editor-preview/reference.json', 'editor-preview')
    return {'format': 'agf-editor-source/v1', 'sourceRoot': str(root),
            'documents': documents, 'profile': profile_document,
            'profilePath': str(profile_path), 'profileSha256': sha256(profile_path.read_bytes()),
            'documentHashes': hashes, 'assets': list(assets.values()),
            **({'previewReference': preview} if preview is not None else {})}
