"""Render reproducible OSM-derived raster tiles for authored offline maps.

Input is an OSM GeoPackage extract licensed under ODbL. This module renders
its own web-map-style PNG tiles and a south-up game surface. It never scrapes
OpenStreetMap Foundation's public tile servers for offline use.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import struct
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject
from shapely import wkb


EARTH_RADIUS = 6378137.0
WEB_EDGE = math.pi * EARTH_RADIUS
TILE_SIZE = 256


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _web_pixel(lon, lat, zoom):
    side = TILE_SIZE * (1 << zoom)
    latitude = math.radians(max(-85.05112878, min(85.05112878, lat)))
    return ((lon + 180) / 360 * side,
            (1 - math.asinh(math.tan(latitude)) / math.pi) / 2 * side)


def _gpkg_geometry(blob, bounds):
    if not blob or blob[:2] != b'GP':
        return None
    flags = blob[3]
    if flags & 1 != 1:
        raise ValueError('OSM GeoPackage requires little-endian geometry')
    envelope = (flags >> 1) & 7
    envelope_size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope)
    if envelope_size is None:
        raise ValueError('Unknown GeoPackage geometry envelope')
    if envelope_size:
        min_x, max_x, min_y, max_y = struct.unpack_from('<4d', blob, 8)
        if max_x < bounds[0] or min_x > bounds[2] or max_y < bounds[1] or min_y > bounds[3]:
            return None
    return wkb.loads(blob[8 + envelope_size:])


def _rows(database, table, bounds):
    for blob, kind, name in database.execute(
            'SELECT geom, fclass, name FROM "' + table + '"'):
        geometry = _gpkg_geometry(blob, bounds)
        if geometry is not None and not geometry.is_empty:
            yield geometry, kind, name


def _parts(geometry):
    if geometry.geom_type in ('Polygon', 'LineString', 'Point'):
        yield geometry
    elif hasattr(geometry, 'geoms'):
        for child in geometry.geoms:
            yield from _parts(child)


def _draw_polygon(draw, geometry, project, color):
    for part in _parts(geometry):
        if part.geom_type == 'Polygon':
            points = [project(x, y) for x, y in part.exterior.coords]
            if len(points) >= 3:
                draw.polygon(points, fill=color)


def _draw_line(draw, geometry, project, color, width):
    for part in _parts(geometry):
        if part.geom_type == 'LineString':
            points = [project(x, y) for x, y in part.coords]
            if len(points) >= 2:
                draw.line(points, fill=color, width=width, joint='curve')


def _web_dem(source, transform, shape):
    data = np.zeros(shape, dtype='float32')
    with rasterio.open(source) as dem:
        reproject(rasterio.band(dem, 1), data, src_transform=dem.transform,
                  src_crs=dem.crs, src_nodata=dem.nodata,
                  dst_transform=transform, dst_crs='EPSG:3857', dst_nodata=0,
                  resampling=Resampling.bilinear)
    np.nan_to_num(data, copy=False, nan=0, posinf=0, neginf=0)
    np.maximum(data, 0, out=data)
    return data


def _render_base(dem):
    land = dem > 0.7
    normalized = np.clip(dem / 1450, 0, 1)
    gy, gx = np.gradient(dem)
    shade = np.clip(0.96 - gx * 0.016 - gy * 0.012, 0.72, 1.12)
    pixels = np.empty((*dem.shape, 3), dtype='float32')
    pixels[:] = (127, 177, 195)
    colors = np.stack((213 - normalized * 66, 215 - normalized * 69,
                       186 - normalized * 77), axis=-1)
    pixels[land] = colors[land]
    pixels[land] *= shade[land, None]
    return Image.fromarray(np.clip(pixels, 0, 255).astype('uint8'))


def _tile_transform(left_tile, top_tile, width, height, zoom):
    metres_per_pixel = 2 * WEB_EDGE / (TILE_SIZE * (1 << zoom))
    west = -WEB_EDGE + left_tile * TILE_SIZE * metres_per_pixel
    north = WEB_EDGE - top_tile * TILE_SIZE * metres_per_pixel
    return from_bounds(west, north - height * metres_per_pixel,
                       west + width * metres_per_pixel, north, width, height)


def _style_polygon(kind):
    if kind in {'forest', 'wood'}: return (102, 145, 100)
    if kind in {'scrub', 'heath'}: return (160, 175, 119)
    if kind in {'grass', 'meadow', 'park', 'recreation_ground'}: return (153, 184, 126)
    if kind in {'farmland', 'farm', 'orchard', 'vineyard'}: return (205, 202, 154)
    if kind in {'residential', 'commercial'}: return (195, 187, 177)
    if kind in {'industrial', 'military', 'railway'}: return (175, 174, 171)
    if kind in {'beach', 'sand'}: return (231, 216, 169)
    if kind in {'cemetery', 'allotments'}: return (156, 181, 143)
    return None


def _road_style(kind):
    if kind in {'motorway', 'trunk'}: return 7, (227, 143, 71), (124, 94, 69)
    if kind in {'primary', 'primary_link'}: return 6, (235, 177, 91), (139, 113, 82)
    if kind in {'secondary', 'secondary_link'}: return 5, (240, 203, 125), (147, 128, 95)
    if kind in {'tertiary', 'tertiary_link'}: return 4, (248, 229, 170), (152, 144, 116)
    if kind in {'residential', 'unclassified', 'living_street'}: return 3, (242, 238, 216), (158, 157, 144)
    if kind in {'service', 'track'}: return 2, (215, 205, 174), (164, 158, 143)
    return 1, (194, 186, 164), (194, 186, 164)


def _world_copy(source, src_transform, src_shape, bounds, destination_size):
    target = np.zeros((3, destination_size, destination_size), dtype='uint8')
    target_transform = from_bounds(*bounds, destination_size, destination_size)
    values = np.asarray(source)
    for index in range(3):
        reproject(values[:, :, index], target[index], src_transform=src_transform,
                  src_crs='EPSG:3857', dst_transform=target_transform,
                  dst_crs='EPSG:4326', dst_nodata=0, resampling=Resampling.bilinear)
    return np.flipud(np.moveaxis(target, 0, 2)).copy()


def render_osm_tiles(geopackage, geotiff, bounds_wgs84, destination, *, zoom=12,
                     surface_size=4096, render_labels=False):
    """Render an OSM web-tile mosaic and an aligned authored map surface."""
    geopackage, geotiff, destination = map(lambda value: Path(value).resolve(),
                                           (geopackage, geotiff, destination))
    if destination.exists():
        raise FileExistsError(destination)
    if (not geopackage.is_file() or not geotiff.is_file()
            or type(zoom) is not int or not 8 <= zoom <= 13
            or type(surface_size) is not int or not 512 <= surface_size <= 8192):
        raise ValueError('OSM tile rendering requires source files, zoom 8..13 and surface size 512..8192')
    if (not isinstance(bounds_wgs84, (tuple, list)) or len(bounds_wgs84) != 4
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds_wgs84)):
        raise ValueError('OSM rendering requires four finite WGS84 bounds')
    west, south, east, north = map(float, bounds_wgs84)
    if not -180 <= west < east <= 180 or not -85 < south < north < 85:
        raise ValueError('Invalid OSM tile rendering rectangle')
    x0, y1 = _web_pixel(west, south, zoom)
    x1, y0 = _web_pixel(east, north, zoom)
    left_tile, top_tile = math.floor(x0 / TILE_SIZE), math.floor(y0 / TILE_SIZE)
    right_tile, bottom_tile = math.ceil(x1 / TILE_SIZE), math.ceil(y1 / TILE_SIZE)
    width = (right_tile - left_tile) * TILE_SIZE
    height = (bottom_tile - top_tile) * TILE_SIZE
    if width * height > 48_000_000:
        raise ValueError('Selected OSM zoom/area would create too many raster pixels')
    transform = _tile_transform(left_tile, top_tile, width, height, zoom)
    dem = _web_dem(geotiff, transform, (height, width))
    canvas = _render_base(dem)
    forest = Image.new('L', (width, height), 0)
    urban = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    forest_draw = ImageDraw.Draw(forest)
    urban_draw = ImageDraw.Draw(urban)
    total = TILE_SIZE * (1 << zoom)

    def project(lon, lat):
        lon_px, lat_px = _web_pixel(lon, lat, zoom)
        return (round(lon_px - left_tile * TILE_SIZE),
                round(lat_px - top_tile * TILE_SIZE))

    database = sqlite3.connect(geopackage)
    counts = {}
    try:
        for table in ('gis_osm_landuse_a_free', 'gis_osm_natural_a_free'):
            number = 0
            for geometry, kind, _ in _rows(database, table, bounds_wgs84):
                color = _style_polygon(kind)
                if color is None: continue
                _draw_polygon(draw, geometry, project, color)
                if kind in {'forest', 'wood'}:
                    _draw_polygon(forest_draw, geometry, project, 255)
                if kind in {'residential', 'commercial', 'industrial'}:
                    _draw_polygon(urban_draw, geometry, project, 220)
                number += 1
            counts[table] = number
        for table in ('gis_osm_water_a_free',):
            counts[table] = 0
            for geometry, _, _ in _rows(database, table, bounds_wgs84):
                _draw_polygon(draw, geometry, project, (108, 162, 190))
                counts[table] += 1
        for geometry, _, _ in _rows(database, 'gis_osm_buildings_a_free', bounds_wgs84):
            _draw_polygon(draw, geometry, project, (166, 155, 138))
            _draw_polygon(urban_draw, geometry, project, 255)
            counts['buildings'] = counts.get('buildings', 0) + 1
        for geometry, _, _ in _rows(database, 'gis_osm_waterways_free', bounds_wgs84):
            _draw_line(draw, geometry, project, (105, 159, 188), 2)
            counts['waterways'] = counts.get('waterways', 0) + 1
        for geometry, _, _ in _rows(database, 'gis_osm_railways_free', bounds_wgs84):
            _draw_line(draw, geometry, project, (100, 102, 101), 2)
            counts['railways'] = counts.get('railways', 0) + 1
        roads = [(geometry, *_road_style(kind)) for geometry, kind, _
                 in _rows(database, 'gis_osm_roads_free', bounds_wgs84)]
        for geometry, width_px, _, border in roads:
            _draw_line(draw, geometry, project, border, width_px + 2)
        for geometry, width_px, inside, _ in roads:
            _draw_line(draw, geometry, project, inside, width_px)
        counts['roads'] = len(roads)
        counts['city_labels'] = 0
        if render_labels:
            font_path = Path('C:/Windows/Fonts/arial.ttf')
            font = ImageFont.truetype(str(font_path), 16) if font_path.is_file() else ImageFont.load_default()
            for geometry, kind, name in _rows(database, 'gis_osm_places_free', bounds_wgs84):
                if kind not in {'city', 'town'} or not name: continue
                for point in _parts(geometry):
                    if point.geom_type == 'Point':
                        x, y = project(point.x, point.y)
                        draw.text((x + 4, y - 7), name, font=font, fill=(42, 50, 47),
                                  stroke_width=2, stroke_fill=(244, 239, 218))
                        counts['city_labels'] += 1
    finally:
        database.close()

    # The in-game strategic light rig lifts map colors. Keep enough contrast
    # and darker midtones so roads, fields and forests remain legible there.
    canvas = ImageEnhance.Contrast(canvas).enhance(1.12)
    canvas = ImageEnhance.Brightness(canvas).enhance(0.84)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.osm-tiles-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result'
        staged.mkdir()
        tile_root = staged / 'tiles' / str(zoom)
        for column in range(left_tile, right_tile):
            path = tile_root / str(column)
            path.mkdir(parents=True, exist_ok=True)
            for row in range(top_tile, bottom_tile):
                tile = canvas.crop(((column - left_tile) * TILE_SIZE,
                                    (row - top_tile) * TILE_SIZE,
                                    (column - left_tile + 1) * TILE_SIZE,
                                    (row - top_tile + 1) * TILE_SIZE))
                tile.save(path / f'{row}.png')
        canvas.save(staged / 'tile-mosaic.png')
        image = Image.fromarray(_world_copy(canvas, transform, (height, width),
                                           (west, south, east, north), surface_size))
        image.save(staged / 'surface.png')
        # Semantic masks use the same geo transform, so map cells and art agree.
        target_transform = from_bounds(west, south, east, north, 101, 101)
        masks = {}
        for key, pixels in [('water', (dem <= 0.7).astype('float32')),
                            ('forest', np.asarray(forest).astype('float32') / 255),
                            ('urban', np.asarray(urban).astype('float32') / 255)]:
            cells = np.zeros((101, 101), dtype='float32')
            reproject(pixels, cells, src_transform=transform, src_crs='EPSG:3857',
                      dst_transform=target_transform, dst_crs='EPSG:4326',
                      resampling=Resampling.average)
            masks[key] = np.flipud(cells).copy()
        terrain = []
        counts_by_terrain = {}
        for row in range(101):
            for column in range(101):
                kind = ('StrategicWater' if masks['water'][row, column] >= 0.60
                        else 'StrategicUrban' if masks['urban'][row, column] >= 0.36
                        else 'StrategicSemiUrban' if masks['urban'][row, column] >= 0.11
                        else 'StrategicForest' if masks['forest'][row, column] >= 0.42
                        else 'StrategicPlain')
                terrain.append({'row': row, 'column': column, 'terrain': kind})
                counts_by_terrain[kind] = counts_by_terrain.get(kind, 0) + 1
        (staged / 'strategic-grid-cells.json').write_text(json.dumps(terrain) + '\n', encoding='utf-8')
        report = {'format': 'agf-osm-raster-tiles/v1',
                  'source': str(geopackage), 'source_sha256': _sha256(geopackage),
                  'dem': str(geotiff), 'dem_sha256': _sha256(geotiff),
                  'bounds_wgs84': [west, south, east, north], 'zoom': zoom,
                  'tile_range': [left_tile, top_tile, right_tile, bottom_tile],
                  'tile_count': (right_tile - left_tile) * (bottom_tile - top_tile),
                  'surface_size': [surface_size, surface_size],
                  'raster_origin': 'southwest',
                  'labels_rendered': render_labels,
                  'source_attribution': 'Map data © OpenStreetMap contributors (ODbL)',
                  'feature_counts': counts, 'terrain_cells': counts_by_terrain,
                  'runtime_verified': False}
        (staged / 'osm-tiles.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                              encoding='utf-8')
        staged.rename(destination)
    return report
