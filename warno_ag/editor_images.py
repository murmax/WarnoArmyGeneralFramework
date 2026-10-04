"""Normalize user artwork to PNG without changing decoded colors or losing alpha."""
from pathlib import Path

from PIL import Image

from .storage import sha256


def normalize_editor_image(source, destination, role='surface'):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if role not in {'surface', 'event'} or destination.exists():
        raise ValueError('Expected a supported image role and a new destination')
    with Image.open(source) as image:
        if image.format not in {'PNG', 'WEBP', 'JPEG'} or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Import a static PNG, WebP or JPEG image')
        if any(not 2 <= value <= 8192 for value in image.size):
            raise ValueError('Image dimensions must be 2..8192 pixels')
        rgba = image.convert('RGBA')
        if role == 'surface' and rgba.getchannel('A').getextrema() != (255, 255):
            raise ValueError('Map surface artwork must be opaque')
        normalized = rgba.convert('RGB') if role == 'surface' else rgba
        destination.parent.mkdir(parents=True, exist_ok=True)
        normalized.save(destination, format='PNG')
    return {'format': 'agf-editor-image/v1', 'source_sha256': sha256(source.read_bytes()),
            'path': str(destination), 'sha256': sha256(destination.read_bytes()), 'role': role,
            'size': list(normalized.size), 'mode': normalized.mode}
