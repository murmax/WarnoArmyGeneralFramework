"""Inspect and crop georeferenced elevation as a north-up world raster.

GeoTIFFs remain source inputs. The exported editor heightmap is a 16-bit PNG
whose first row corresponds to the map's northern edge. Columns map to native
x and rows to native y; the geographic y coordinate increases southward.
"""
import hashlib
import json
import math
from pathlib import Path
import tempfile

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject


def _digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            checksum.update(block)
    return checksum.hexdigest()


def _source(path):
    path = Path(path).resolve()
    if not path.is_file() or path.suffix.lower() not in ('.tif', '.tiff'):
        raise ValueError('Select a readable GeoTIFF (.tif or .tiff)')
    opened = rasterio.open(path)
    if opened.count < 1 or opened.crs is None or opened.width < 2 or opened.height < 2:
        opened.close()
        raise ValueError('GeoTIFF requires a CRS and at least one raster band')
    return path, opened


def _bounds(vrt):
    bounds = [float(vrt.bounds.left), float(vrt.bounds.bottom),
              float(vrt.bounds.right), float(vrt.bounds.top)]
    if (any(not math.isfinite(value) for value in bounds)
            or not -180 <= bounds[0] < bounds[2] <= 180
            or not -90 <= bounds[1] < bounds[3] <= 90):
        raise ValueError('GeoTIFF has invalid WGS84 bounds')
    return bounds


def _preview(data):
    heights = np.nan_to_num(data.astype('float32'), nan=0, posinf=0, neginf=0)
    heights = np.maximum(heights, 0)
    land = heights > 0.75
    ceiling = max(1.0, float(np.percentile(heights[land], 99.5))) if np.any(land) else 1.0
    normalized = np.clip(heights / ceiling, 0, 1)
    gy, gx = np.gradient(heights)
    shade = np.clip(0.82 - gx * 0.025 - gy * 0.018, 0.5, 1.15)
    pixels = np.empty((*heights.shape, 3), dtype='float32')
    pixels[:] = (57, 103, 129)
    colors = np.stack((149 - normalized * 45, 166 - normalized * 39,
                       120 - normalized * 51), axis=-1)
    pixels[land] = colors[land]
    pixels *= shade[:, :, None]
    return Image.fromarray(np.clip(pixels, 0, 255).astype('uint8'))


def inspect_geotiff(source, destination):
    """Create an ignored north-up preview and machine-readable source receipt."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    path, dataset = _source(source)
    try:
        with WarpedVRT(dataset, crs='EPSG:4326', resampling=Resampling.bilinear) as vrt:
            bounds = _bounds(vrt)
            scale = min(1100 / vrt.width, 800 / vrt.height, 1.0)
            size = [max(2, round(vrt.width * scale)), max(2, round(vrt.height * scale))]
            data = vrt.read(1, out_shape=(size[1], size[0]),
                            resampling=Resampling.bilinear, masked=True).filled(0)
        image = _preview(data)
        report = {'format': 'agf-geotiff-inspect/v1', 'source': str(path),
                  'source_sha256': _digest(path), 'source_crs': dataset.crs.to_string(),
                  'source_size': [dataset.width, dataset.height],
                  'bounds_wgs84': bounds, 'preview_size': size,
                  'preview_origin': 'northwest', 'runtime_verified': False}
    finally:
        dataset.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.geotiff-inspect-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result'
        staged.mkdir()
        image.save(staged / 'preview.png')
        (staged / 'geotiff.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        staged.rename(destination)
    return report


def crop_geotiff(source, bounds_wgs84, resolution, destination, *, elevation_ceiling_m=1600.0):
    """Reproject a user-picked rectangle and convert metres to editor height.

    Coordinates are west/south/east/north. The north-up GeoTIFF output is
    retained north-up: row zero is the northern edge of the authored world.
    """
    if (not isinstance(bounds_wgs84, (tuple, list)) or len(bounds_wgs84) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in bounds_wgs84)):
        raise ValueError('Crop requires four finite WGS84 coordinates')
    west, south, east, north = map(float, bounds_wgs84)
    if (not -180 <= west < east <= 180 or not -90 <= south < north <= 90
            or east - west < 0.001 or north - south < 0.001):
        raise ValueError('Select a nonempty west/south/east/north rectangle')
    if type(resolution) is not int or not 128 <= resolution <= 8192:
        raise ValueError('Heightmap resolution must be 128..8192 pixels per edge')
    if (type(elevation_ceiling_m) not in (int, float) or not math.isfinite(elevation_ceiling_m)
            or not 1 <= elevation_ceiling_m <= 10000):
        raise ValueError('Elevation ceiling must be 1..10000 metres')
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    path, dataset = _source(source)
    try:
        with WarpedVRT(dataset, crs='EPSG:4326') as vrt:
            available = _bounds(vrt)
        if (west < available[0] - 1e-7 or south < available[1] - 1e-7
                or east > available[2] + 1e-7 or north > available[3] + 1e-7):
            raise ValueError('Selected rectangle extends outside the GeoTIFF')
        heights = np.zeros((resolution, resolution), dtype='float32')
        reproject(source=rasterio.band(dataset, 1), destination=heights,
                  src_transform=dataset.transform, src_crs=dataset.crs,
                  src_nodata=dataset.nodata, dst_transform=from_bounds(
                      west, south, east, north, resolution, resolution),
                  dst_crs='EPSG:4326', dst_nodata=0,
                  resampling=Resampling.bilinear)
        heights = np.nan_to_num(heights, nan=0, posinf=0, neginf=0)
        np.maximum(heights, 0, out=heights)
        if not np.any(heights > 0.75):
            raise ValueError('Selected GeoTIFF rectangle contains no land elevation')
        maximum = float(heights.max())
        scaled = np.rint(np.clip(heights / elevation_ceiling_m, 0, 1) * 65535).astype('uint16')
        # Keep the GeoTIFF orientation. Flipping here mirrored every imported
        # map and forced authors to place geography in a reflected world.
        image = Image.fromarray(scaled)
        report = {'format': 'agf-geotiff-crop/v1', 'source': str(path),
                  'source_sha256': _digest(path), 'source_crs': dataset.crs.to_string(),
                  'bounds_wgs84': [west, south, east, north],
                  'resolution': [resolution, resolution],
                  'elevation_ceiling_m': float(elevation_ceiling_m),
                  'sample_max_m': maximum, 'sample_land_pixels': int(np.count_nonzero(heights > 0.75)),
                  'raster_origin': 'northwest', 'heightmap': 'heightmap.png',
                  'runtime_verified': False}
    finally:
        dataset.close()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.geotiff-crop-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result'
        staged.mkdir()
        image.save(staged / 'heightmap.png')
        (staged / 'crop.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        staged.rename(destination)
    return report
