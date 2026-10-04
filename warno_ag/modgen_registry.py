"""Locate the one official ModGen localisation registry in a candidate."""
from pathlib import Path
import re


def authored_build_name(root):
    root = Path(root).resolve()
    folder = root / 'Gen/NDF/Localisation'
    matches = [path for path in folder.glob('*.ndfbin')
               if re.fullmatch(r'WarnoAGF[A-Za-z0-9_]*Build[A-Za-z0-9_]*', path.stem)]
    if len(matches) != 1:
        raise ValueError('Expected exactly one official AGF ModGen localisation registry')
    name = matches[0].stem
    return name


def authored_registry_path(root):
    return Path(root).resolve() / 'Gen/NDF/Localisation' / (authored_build_name(root) + '.ndfbin')
