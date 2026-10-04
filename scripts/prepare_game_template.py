"""Extract the installed WARNO ModGen source archive for local authoring.

The extracted game sources stay under ignored ``artifacts/``. This command
never launches WARNO, installs a mod, or copies game resources into Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import uuid
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DESTINATION = ARTIFACTS / "modgen-201602-template"
REQUIRED = (
    "GameData/Generated/Gameplay/Decks/StrategicPacks.ndf",
    "GameData/Generated/Gameplay/Gfx/UniteDescriptor.ndf",
    "GameData/Generated/Gameplay/Decks/DivisionRules.ndf",
)
MAX_ENTRIES = 10_000
MAX_UNCOMPRESSED = 512 * 1024 * 1024


def prepare(game_root: Path) -> dict:
    game = game_root.resolve()
    archive_path = game / "Mods/ModData/base.zip"
    if not archive_path.is_file() or not (game / "WARNO.exe").is_file():
        raise FileNotFoundError("Select a WARNO installation containing WARNO.exe and Mods/ModData/base.zip")
    ARTIFACTS.mkdir(exist_ok=True)
    if DESTINATION.exists():
        raise FileExistsError(f"Local ModGen template already exists: {DESTINATION}")
    temporary = ARTIFACTS / (".modgen-template-" + uuid.uuid4().hex)
    if not temporary.resolve().is_relative_to(ARTIFACTS.resolve()):
        raise ValueError("Temporary template escaped artifacts")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ENTRIES or sum(item.file_size for item in members) > MAX_UNCOMPRESSED:
                raise ValueError("Official source archive exceeds the bounded extraction limit")
            names = {item.filename.replace("\\", "/") for item in members}
            if not set(REQUIRED) <= names:
                raise ValueError("WARNO source archive lacks required ModGen catalogs")
            temporary.mkdir()
            count = 0
            total = 0
            for item in members:
                name = item.filename.replace("\\", "/")
                parts = Path(name).parts
                if (not name or name.startswith("/") or ":" in name or
                        any(part in ("", ".", "..") for part in parts) or
                        stat.S_IFMT(item.external_attr >> 16) == stat.S_IFLNK):
                    raise ValueError("Unsafe entry in WARNO source archive")
                target = (temporary / name).resolve()
                if not target.is_relative_to(temporary.resolve()):
                    raise ValueError("WARNO source archive entry escaped destination")
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                count += 1
                total += item.file_size
        receipt = {"format": "agf-installed-game-template/v1",
                   "source": str(archive_path),
                   "source_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                   "files": count, "uncompressed_bytes": total,
                   "game_launched": False, "git_tracked": False}
        (temporary / "agf-template-receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        temporary.rename(DESTINATION)
        return receipt
    finally:
        if temporary.exists():
            if temporary.is_symlink() or not temporary.resolve().is_relative_to(ARTIFACTS.resolve()):
                raise ValueError("Unsafe temporary template cleanup target")
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.game_root), indent=2))


if __name__ == "__main__":
    main()
