"""Authoring geometry for regular grids, not an engine navigation algorithm."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any


@dataclass(frozen=True)
class GridCell:
    row: int
    column: int
    terrain: str
    road: bool = False

    @property
    def id(self) -> str:
        return f'r{self.row}c{self.column}'


@dataclass(frozen=True)
class StrategicGrid:
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    default_terrain: str
    cells: tuple[GridCell, ...]

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> StrategicGrid:
        required = {'dimensions', 'bounds', 'default_terrain'}
        if not isinstance(config, dict) or not required <= config.keys():
            raise ValueError('strategic grid requires dimensions, bounds and default_terrain')
        if set(config) - required - {'cells'}:
            raise ValueError('unknown strategic grid fields')
        dimensions = config['dimensions']
        if not isinstance(dimensions, dict) or set(dimensions) != {'width', 'height'}:
            raise ValueError('strategic grid dimensions require width and height')
        width, height = dimensions['width'], dimensions['height']
        if type(width) is not int or type(height) is not int:
            raise ValueError('strategic grid dimensions must be integers')
        if width <= 0 or height <= 0:
            raise ValueError('strategic grid dimensions must be positive')
        bounds = config['bounds']
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in bounds)):
            raise ValueError('strategic grid bounds must contain four finite numbers')
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError('strategic grid bounds must have positive area')
        terrain = config['default_terrain']
        if not isinstance(terrain, str) or not terrain.strip():
            raise ValueError('strategic grid requires a default terrain')
        raw_cells = config.get('cells')
        if 'cells' not in config:
            raw_cells = [{'row': row, 'column': column, 'terrain': terrain}
                         for row in range(height) for column in range(width)]
        if not isinstance(raw_cells, list):
            raise ValueError('strategic grid cells must be a list')
        cells = []
        for item in raw_cells:
            if (not isinstance(item, dict) or not {'row', 'column'} <= item.keys()
                    or set(item) - {'row', 'column', 'terrain', 'road', 'id'}):
                raise ValueError('invalid strategic grid cell fields')
            if type(item['row']) is not int or type(item['column']) is not int:
                raise ValueError('strategic grid cell coordinates must be integers')
            if type(item.get('road', False)) is not bool:
                raise ValueError('strategic grid road must be boolean')
            cell = GridCell(item['row'], item['column'], item.get('terrain', terrain),
                            item.get('road', False))
            if 'id' in item and item['id'] != cell.id:
                raise ValueError('strategic grid cell id does not match its coordinates')
            cells.append(cell)
        grid = cls(width, height, tuple(float(value) for value in bounds), terrain,
                   tuple(sorted(cells, key=lambda cell: (cell.row, cell.column))))
        grid.validate()
        return grid

    def validate(self) -> None:
        expected = {(row, column) for row in range(self.height) for column in range(self.width)}
        actual = {(cell.row, cell.column) for cell in self.cells}
        if actual != expected or len(self.cells) != len(expected):
            raise ValueError('strategic grid must contain each cell exactly once')
        supported = {self.default_terrain, 'StrategicPlain', 'StrategicForest', 'StrategicSemiUrban', 'StrategicUrban', 'StrategicWater'}
        if any(not isinstance(cell.terrain, str) or cell.terrain not in supported for cell in self.cells):
            raise ValueError('strategic grid contains an unknown terrain')
        if any(cell.road and cell.terrain == 'StrategicWater' for cell in self.cells):
            raise ValueError('strategic road cannot cross blocking water')

    def as_dict(self) -> dict[str, Any]:
        return {
            'dimensions': {'width': self.width, 'height': self.height},
            'bounds': list(self.bounds),
            'default_terrain': self.default_terrain,
            'cells': [{'id': cell.id, 'row': cell.row, 'column': cell.column,
                       'terrain': cell.terrain, **({'road': True} if cell.road else {})}
                      for cell in self.cells],
        }

    def _check_cell(self, row: int, column: int) -> None:
        if (type(row) is not int or type(column) is not int
                or not 0 <= row < self.height or not 0 <= column < self.width):
            raise ValueError('cell coordinates outside strategic grid')

    def cell_bounds(self, row: int, column: int) -> tuple[float, float, float, float]:
        self._check_cell(row, column)
        left, bottom, right, top = self.bounds
        cell_width, cell_height = (right - left) / self.width, (top - bottom) / self.height
        return (left + column * cell_width, bottom + row * cell_height,
                left + (column + 1) * cell_width, bottom + (row + 1) * cell_height)

    def cell_center(self, row: int, column: int) -> tuple[float, float]:
        left, bottom, right, top = self.cell_bounds(row, column)
        return ((left + right) / 2, (bottom + top) / 2)

    def neighbours(self, row: int, column: int) -> tuple[str, ...]:
        self._check_cell(row, column)
        result = []
        for row_delta, column_delta in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            adjacent_row, adjacent_column = row + row_delta, column + column_delta
            if 0 <= adjacent_row < self.height and 0 <= adjacent_column < self.width:
                result.append(f'r{adjacent_row}c{adjacent_column}')
        return tuple(result)
