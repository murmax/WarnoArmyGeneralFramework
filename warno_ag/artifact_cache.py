"""Content-addressed lifecycle for generated research artifacts."""
import json
import os
import tempfile
from pathlib import Path

from .storage import sha256


def input_manifest(paths):
    resolved = sorted(Path(path).resolve() for path in paths)
    return {path.as_posix(): sha256(path.read_bytes()) for path in resolved}


def publish_with_manifest(output, content, inputs):
    output = Path(output).resolve()
    manifest = output.with_name(output.name + '.manifest.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, output)
        payload = {'schema': 1, 'output_sha256': sha256(output.read_bytes()),
                   'inputs': input_manifest(inputs)}
        temporary_manifest = manifest.with_name(manifest.name + '.partial')
        temporary_manifest.write_text(json.dumps(payload, sort_keys=True) + '\n', encoding='utf-8')
        os.replace(temporary_manifest, manifest)
    finally:
        if temporary.exists():
            temporary.unlink()
        partial = manifest.with_name(manifest.name + '.partial')
        if partial.exists():
            partial.unlink()
    return payload


def verify_manifest(output, inputs):
    output = Path(output).resolve()
    manifest = output.with_name(output.name + '.manifest.json')
    if not output.is_file() or not manifest.is_file():
        return False
    try:
        payload = json.loads(manifest.read_text(encoding='utf-8'))
        return (payload.get('schema') == 1
                and payload.get('output_sha256') == sha256(output.read_bytes())
                and payload.get('inputs') == input_manifest(inputs))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
