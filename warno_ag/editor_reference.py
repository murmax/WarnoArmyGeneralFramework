"""Crop read-only game previews to a public YAML adapter's world coordinates."""
import json
import math
from pathlib import Path

from PIL import Image

from .native_campaign_source import verify_native_snapshot
from .editor_visuals import verify_editor_visuals
from .storage import safe_child, sha256


def crop_game_reference(source, visuals, bounds, destination):
    source, visuals, destination = Path(source).resolve(), Path(visuals).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    verify_native_snapshot(source)
    manifest = json.loads((source / 'native-source.json').read_text(encoding='utf-8'))
    visual = verify_editor_visuals(visuals, manifest['projection_sha256'])
    if not visual.get('ground') or not visual.get('scene', {}).get('path_geometry'):
        raise ValueError('The source needs converted ground and scene previews')
    projection = json.loads(safe_child(source, manifest['projection_file']).read_text(encoding='utf-8'))
    original = projection['map']['bounds']
    if (len(bounds) != 4 or any(not math.isfinite(x) for x in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise ValueError('Invalid YAML reference bounds')
    step = projection['map']['grid']['step_native']
    if any(a < b - step for a, b in zip(bounds[:2], original[:2])) or any(a > b + step for a, b in zip(bounds[2:], original[2:])):
        raise ValueError('YAML reference bounds exceed the source map')
    destination.mkdir(parents=True)
    outputs = {}
    for name, input_path in (('surface', source / 'preview/surface.png'),
                             ('ground', safe_child(visuals, visual['ground']['albedo']))):
        with Image.open(input_path) as image:
            rgb = image.convert('RGB')
            out_size = tuple(max(2, min(8192, round(a * (bounds[i + 2] - bounds[i]) / (original[i + 2] - original[i]))))
                             for i, a in enumerate(rgb.size))
            source_pixels = rgb.load()
            pixels = []
            for y in range(out_size[1]):
                world_y = bounds[1] + (y + .5) * (bounds[3] - bounds[1]) / out_size[1]
                sy = max(0, min(rgb.height - 1, round((world_y - original[1]) / (original[3] - original[1]) * (rgb.height - 1))))
                for x in range(out_size[0]):
                    world_x = bounds[0] + (x + .5) * (bounds[2] - bounds[0]) / out_size[0]
                    sx = max(0, min(rgb.width - 1, round((world_x - original[0]) / (original[2] - original[0]) * (rgb.width - 1))))
                    pixels.append(source_pixels[sx, sy])
            output = Image.new('RGB', out_size)
            output.putdata(pixels)
            path = destination / (name + '.png')
            output.save(path)
            outputs[name] = {'file': str(path), 'size': list(out_size), 'sha256': sha256(path.read_bytes())}
    report = {'format': 'agf-editor-game-reference/v1', 'scenario': manifest['scenario'], 'source_bounds': original,
              'target_bounds': list(bounds), 'images': outputs, 'preview_only': True, 'runtime_verified': False}
    (destination / 'reference-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report
