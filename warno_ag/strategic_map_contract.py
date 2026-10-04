"""Configuration contract for an Army General strategic-map package."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]*\Z')


@dataclass(frozen=True)
class StrategicMapContract:
    id: str
    map_name: str
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    default_terrain: str
    render_cases: tuple[int, int]
    tactical_policy: str
    fixed_battleground: str | None = None
    playable_bounds: tuple[float, float, float, float] | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> 'StrategicMapContract':
        base = {'id', 'map_name', 'dimensions', 'render_cases', 'bounds', 'default_terrain'}
        if not isinstance(config, dict) or not base <= set(config):
            raise ValueError('strategic map contract fields mismatch')
        policy_fields = set(config) - base - {'playable_bounds'}
        if policy_fields == {'tactical_policy'}:
            tactical_policy = config['tactical_policy']
            fixed_battleground = None
        elif policy_fields == {'fixed_battleground'}:
            tactical_policy = 'specific'
            fixed_battleground = config['fixed_battleground']
        else:
            raise ValueError('strategic map contract fields mismatch')
        values = {key: config[key] for key in ('id', 'map_name', 'default_terrain')}
        for key, value in values.items():
            if not isinstance(value, str) or NAME.fullmatch(value) is None:
                raise ValueError(f'{key} must be an identifier')
        if tactical_policy not in ('terrain_pool', 'specific'):
            raise ValueError('unsupported tactical policy')
        if tactical_policy == 'specific' and (not isinstance(fixed_battleground, str)
                or NAME.fullmatch(fixed_battleground) is None):
            raise ValueError('fixed_battleground must be an identifier')
        sizes = {}
        for field in ('dimensions', 'render_cases'):
            dimensions = config[field]
            if (not isinstance(dimensions, dict) or set(dimensions) != {'width', 'height'}
                    or type(dimensions['width']) is not int or type(dimensions['height']) is not int
                    or dimensions['width'] <= 0 or dimensions['height'] <= 0):
                raise ValueError(f'strategic map {field} must be positive integers')
            sizes[field] = (dimensions['width'], dimensions['height'])
        bounds = config['bounds']
        if (not isinstance(bounds, list) or len(bounds) != 4
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in bounds)
                or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
            raise ValueError('strategic map bounds must be finite and ordered')
        playable = config.get('playable_bounds')
        if 'playable_bounds' in config:
            if (not isinstance(playable, list) or len(playable) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value)
                           for value in playable)
                    or not bounds[0] <= playable[0] < playable[2] <= bounds[2]
                    or not bounds[1] <= playable[1] < playable[3] <= bounds[3]):
                raise ValueError('playable bounds must be finite, ordered and inside map bounds')
        return cls(values['id'], values['map_name'], sizes['dimensions'][0], sizes['dimensions'][1],
                   tuple(float(value) for value in bounds), values['default_terrain'],
                   sizes['render_cases'], tactical_policy, fixed_battleground,
                   tuple(float(value) for value in playable) if playable is not None else None)

    def as_dict(self) -> dict[str, Any]:
        result = {'id': self.id, 'map_name': self.map_name,
                'dimensions': {'width': self.width, 'height': self.height},
                'render_cases': {'width': self.render_cases[0], 'height': self.render_cases[1]},
                'bounds': list(self.bounds), 'default_terrain': self.default_terrain,
                'tactical_policy': self.tactical_policy}
        if self.fixed_battleground is not None:
            result['fixed_battleground'] = self.fixed_battleground
        if self.playable_bounds is not None:
            result['playable_bounds'] = list(self.playable_bounds)
        return result
