"""Output operations confined to an explicit research directory."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_child(root, virtual):
    name = virtual.replace("\\", "/")
    parts = PurePosixPath(name).parts
    if not parts or any(p in ("..", ".", "/") or ":" in p for p in parts):
        raise ValueError(f"Unsafe resource path: {virtual!r}")
    root = Path(root).resolve()
    target = root.joinpath(*parts).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Resource escaped output root")
    return target


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
