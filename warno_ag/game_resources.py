"""Read-only access to installed game archives, with explicit layering policies.

Definition packages are complete at a revision. Details/assets and the baked
Maps/PC packages have per-resource overlays. Preserving this distinction avoids
reviving old native schemas when importing current source scenarios.
"""
from dataclasses import dataclass
import mmap
from pathlib import Path
import re

from .archives import read_directory, read_entry, revision_key


def resource_path(value):
    if not isinstance(value, str):
        raise ValueError('Resource path must be text')
    value = value.replace('\\', '/')
    if (not value or ':' in value or value.startswith('/')
            or any(part in ('', '.', '..') for part in value.split('/'))
            or any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid archive resource path: ' + value)
    return value


@dataclass(frozen=True)
class GameResource:
    archive: Path
    path: str
    stored_path: str
    offset: int
    size: int
    edat_version: int
    checksum: str

    def read(self):
        return read_entry({'pack': str(self.archive), 'offset': self.offset,
                           'size': self.size, 'edat_version': self.edat_version,
                           'checksum': self.checksum})

    def origin(self):
        return {'archive': str(self.archive), 'path': self.path, 'stored_path': self.stored_path,
                'offset': self.offset, 'size': self.size, 'edat_version': self.edat_version,
                'checksum': self.checksum}


def _revision(path, data_root):
    numbers = revision_key(path, data_root)
    return (numbers[-1] if numbers else 0, numbers, str(path))


class ResourceSet:
    def __init__(self, entries=()):
        self._entries = {}
        for entry in entries:
            key = entry.path.casefold()
            if key in self._entries:
                raise ValueError('Ambiguous archive resource name: ' + entry.path)
            self._entries[key] = entry

    @classmethod
    def archive(cls, path):
        path = Path(path).resolve()
        entries = []
        with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            header, records, _ = read_directory(data)
            if header.version not in (2, 3):
                raise ValueError('Only checksummed EDAT v2/v3 source resources are supported')
            for record in records:
                entries.append(GameResource(path, resource_path(record.path), record.path,
                    header.file_offset + record.offset, record.size, header.version,
                    data[record.checksum_offset:record.checksum_offset + (4 if header.version == 3 else 16)].hex()))
        return cls(entries)

    @classmethod
    def latest(cls, paths, data_root):
        paths = list(paths)
        if not paths:
            raise FileNotFoundError('No complete definition archive was found')
        return cls.archive(max(paths, key=lambda path: _revision(path, data_root)))

    @classmethod
    def layers(cls, paths, data_root, *, base=None):
        entries = {} if base is None else dict(base._entries)
        for path in sorted(paths, key=lambda path: _revision(path, data_root)):
            entries.update(cls.archive(path)._entries)
        return cls(entries.values())

    @property
    def paths(self):
        return tuple(entry.path for entry in self._entries.values())

    @property
    def entries(self):
        return tuple(self._entries.values())

    def require(self, path):
        key = resource_path(path).casefold()
        if key not in self._entries:
            raise KeyError('Missing game resource: ' + path)
        return self._entries[key]

    def read(self, path):
        return self.require(path).read()

    def __len__(self):
        return len(self._entries)


class GameResources:
    def __init__(self, game_root):
        self.root = Path(game_root).resolve()
        self.data_root = self.root / 'Data/PC'
        self.maps_root = self.root / 'Maps/PC'
        if not self.data_root.is_dir() or not self.maps_root.is_dir():
            raise ValueError('Select the installed WARNO directory containing Data/PC and Maps/PC')
        self._files = {}
        for path in self.data_root.rglob('*.dat'):
            if not path.resolve().is_relative_to(self.data_root):
                raise ValueError('Game archive escapes Data/PC: ' + str(path))
            self._files.setdefault(path.name.casefold(), []).append(path)
        self._sets = {}

    def campaigns(self):
        return tuple(sorted({path.name.removesuffix('_Definition.dat')
                             for paths in self._files.values() for path in paths
                             if path.name.startswith('CampagneStrat_') and path.name.endswith('_Definition.dat')
                             and path.parent.name == 'Scenarios'}))

    def scenario(self, identifier, kind):
        if identifier not in self.campaigns() or kind not in {'Definition', 'Details', 'Assets', 'GameData'}:
            raise ValueError('Unknown installed source scenario or resource kind')
        key = ('scenario', identifier, kind)
        if key not in self._sets:
            paths = [path for path in self._files.get((identifier + '_' + kind + '.dat').casefold(), [])
                     if path.parent.name == 'Scenarios']
            self._sets[key] = (ResourceSet.latest(paths, self.data_root) if kind == 'Definition'
                               else ResourceSet.layers(paths, self.data_root))
        return self._sets[key]

    def map(self, identifier, kind):
        if (not isinstance(identifier, str) or re.fullmatch(r'[A-Za-z0-9_]+', identifier) is None
                or kind not in {'Definition', 'Details', 'Assets', 'baked', 'Shooting', 'Stickers'}):
            raise ValueError('Invalid source map identifier or resource kind')
        key = ('map', identifier, kind)
        if key not in self._sets:
            if kind in {'baked', 'Shooting', 'Stickers'}:
                name = identifier + ('' if kind == 'baked' else '_' + kind) + '.dat'
                base_path = self.maps_root / name
                base = ResourceSet.archive(base_path) if base_path.is_file() else None
                paths = [path for path in self._files.get(name.casefold(), []) if path.parent.name != 'Maps']
                if base is None and not paths:
                    raise FileNotFoundError('Missing installed base map: ' + name)
                self._sets[key] = ResourceSet.layers(paths, self.data_root, base=base)
            else:
                paths = [path for path in self._files.get((identifier + '_' + kind + '.dat').casefold(), [])
                         if path.parent.name == 'Maps']
                self._sets[key] = (ResourceSet.latest(paths, self.data_root) if kind == 'Definition'
                                   else ResourceSet.layers(paths, self.data_root))
        return self._sets[key]

    def shared(self):
        key = ('shared',)
        if key not in self._sets:
            paths = [path for group in self._files.values() for path in group
                     if re.fullmatch(r'ZZ(?:_\d+)?\.dat', path.name, re.IGNORECASE)]
            self._sets[key] = ResourceSet.layers(paths, self.data_root)
        return self._sets[key]

    def definitions(self):
        key = ('definitions',)
        if key not in self._sets:
            self._sets[key] = ResourceSet.latest(self._files.get('glad.dat', []), self.data_root)
        return self._sets[key]

    def decor_sets(self):
        return tuple(sorted({path.name.removesuffix('_Definition.dat')
                             for paths in self._files.values() for path in paths
                             if path.name.endswith('_Definition.dat') and path.parent.name == 'DecorsSets'}))

    def decor(self, identifier, kind):
        if identifier not in self.decor_sets() or kind not in {'Definition', 'Assets', 'Editor'}:
            raise ValueError('Unknown installed decor set or resource kind')
        key = ('decor', identifier, kind)
        if key not in self._sets:
            paths = [path for path in self._files.get((identifier + '_' + kind + '.dat').casefold(), [])
                     if path.parent.name == 'DecorsSets']
            self._sets[key] = (ResourceSet.latest(paths, self.data_root) if kind == 'Definition'
                               else ResourceSet.layers(paths, self.data_root))
        return self._sets[key]
