"""Extract an original strategic event portrait into an ignored editor preview."""
import json
from pathlib import Path
import re

from .game_resources import GameResources
from .storage import sha256
from .tgv import read_texture


def capture_game_event_preview(game_root, token, destination):
    if not isinstance(token, str) or re.fullmatch(r'general_[A-Za-z0-9_]+', token) is None:
        raise ValueError('Only verified stock strategic event portrait tokens are previewable')
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    game = GameResources(game_root)
    resources = game.shared()
    suffix = '/ldhint/' + token.casefold() + '.tgv'
    matches = [path for path in resources.paths if path.casefold().endswith(suffix)
               and path.startswith('PC/Texture/Assets/2D/Interface/UseStrategic/LDHint/')]
    if len(matches) != 1:
        raise ValueError('Stock event portrait token has no unique game texture: ' + token)
    raw = resources.require(matches[0]).read()
    image, header = read_texture(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format='PNG')
    report = {'format': 'agf-editor-stock-event-preview/v1', 'token': token,
              'source': matches[0], 'source_sha256': sha256(raw),
              'image_sha256': sha256(destination.read_bytes()),
              'size': list(image.size), 'texture_format': header['format'],
              'runtime_verified': False}
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def capture_native_event_preview(game_root, scenario, token, destination):
    """Decode one scenario-owned cutscene texture, preserving its source path."""
    if (not isinstance(scenario, str) or not isinstance(token, str)
            or re.fullmatch(r'CampagneStrat_[A-Za-z0-9_]+', scenario) is None
            or re.fullmatch(r'[A-Za-z0-9_]{1,96}', token) is None):
        raise ValueError('Native event image requires a source scenario and safe texture token')
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    game = GameResources(game_root)
    if scenario not in game.campaigns():
        raise ValueError('Native event image scenario is not an installed source campaign')
    resources = game.scenario(scenario, 'Assets')
    expected = f'PC/Texture/{scenario}/Scripting/Textures/{token}.tgv'
    matches = [path for path in resources.paths if path.casefold() == expected.casefold()]
    if len(matches) != 1:
        raise ValueError('Native event image has no unique scenario asset: ' + token)
    raw = resources.require(matches[0]).read()
    image, header = read_texture(raw)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format='PNG')
    report = {'format': 'agf-editor-native-event-preview/v1', 'scenario': scenario,
              'token': token, 'source': matches[0], 'source_sha256': sha256(raw),
              'image_sha256': sha256(destination.read_bytes()), 'size': list(image.size),
              'texture_format': header['format'], 'runtime_verified': False}
    destination.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report
