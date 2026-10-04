"""On-demand, attributed sources for a user-selected geographic rectangle.

Copernicus DEM comes from its public COG bucket. OSM features come from a
Geofabrik regional extract; raster game tiles are rendered locally from that
extract, never bulk-fetched from OSMF's community tile servers.
"""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import zipfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
import requests
from shapely.geometry import box, shape


EARTH_SEARCH = 'https://earth-search.aws.element84.com/v1/search'
GEOFABRIK_INDEX = 'https://download.geofabrik.de/index-v1.json'
USER_AGENT = 'WARNO-Army-General-Editor/0.1 (desktop geodata import)'


def _bounds(values):
    if (not isinstance(values, (tuple, list)) or len(values) != 4
            or any(type(value) not in (int, float) or not math.isfinite(value)
                   for value in values)):
        raise ValueError('Geodata requires four finite WGS84 coordinates')
    west, south, east, north = map(float, values)
    if (not -180 <= west < east <= 180 or not -85 < south < north < 85
            or east - west > 3 or north - south > 3):
        raise ValueError('Choose a rectangle no wider than three degrees in either direction')
    return west, south, east, north


def _digest(path):
    checksum = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            checksum.update(block)
    return checksum.hexdigest()


def _session():
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT})
    return session


def _download(session, url, target, max_bytes, *, progress=None):
    """Keep a source in a checked cache without replacing conflicting bytes."""
    target = Path(target)
    receipt = target.with_name(target.name + '.source.json')
    if target.is_file() and receipt.is_file():
        record = json.loads(receipt.read_text(encoding='utf-8'))
        if record.get('url') != url or record.get('sha256') != _digest(target):
            raise ValueError('Cached geodata changed; inspect its receipt: ' + str(target))
        if progress: progress(1.0)
        return record
    if target.exists() or receipt.exists():
        raise ValueError('Incomplete geodata cache; inspect before retrying: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.geodata-', dir=target.parent) as temporary:
        pending = Path(temporary) / 'download'
        size = 0
        with session.get(url, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            announced = int(response.headers.get('Content-Length', '0'))
            if announced > max_bytes:
                raise ValueError('Geodata download exceeds the bounded import size')
            checksum = hashlib.sha256()
            with pending.open('wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk: continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Geodata download exceeds the bounded import size')
                    output.write(chunk); checksum.update(chunk)
                    if progress and announced:
                        progress(min(0.99, size / announced))
            record = {'url': url, 'resolved_url': response.url, 'bytes': size,
                      'sha256': checksum.hexdigest()}
        pending.rename(target)
        receipt.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        if progress: progress(1.0)
        return record


def _dem_url(s3):
    prefix = 's3://copernicus-dem-30m/'
    if not isinstance(s3, str) or not s3.startswith(prefix) or not s3.endswith('.tif'):
        raise ValueError('Unexpected Copernicus DEM STAC asset')
    return 'https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/' + s3[len(prefix):]


def download_copernicus_dem(bounds_wgs84, destination, cache, *, progress=None):
    """Fetch public COG tiles intersecting the rectangle and emit one GeoTIFF."""
    bounds = _bounds(bounds_wgs84)
    destination = Path(destination).resolve()
    cache = Path(cache).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    with _session() as session:
        response = session.post(EARTH_SEARCH,
                                json={'collections': ['cop-dem-glo-30'],
                                      'bbox': list(bounds), 'limit': 40}, timeout=40)
        response.raise_for_status()
        features = response.json().get('features', [])
        if not 1 <= len(features) <= 16:
            raise ValueError('Copernicus DEM selection requires 1..16 public tiles')
        rows = []
        for index, feature in enumerate(sorted(features, key=lambda item: item['id'])):
            url = _dem_url(feature['assets']['data']['href'])
            path = cache / 'copernicus-glo30' / (feature['id'] + '.tif')
            record = _download(session, url, path, 300_000_000,
                               progress=(lambda fraction, i=index: progress(
                                   round((i + fraction) / len(features) * 65),
                                   'Downloading Copernicus DEM tiles') if progress else None))
            rows.append({'id': feature['id'], 'path': str(path), **record})
            if progress: progress(round((index + 1) / len(features) * 65), 'Downloading Copernicus DEM tiles')
    with rasterio.Env(GDAL_NUM_THREADS='ALL_CPUS'):
        sources = [rasterio.open(row['path']) for row in rows]
        try:
            if any(src.crs != rasterio.crs.CRS.from_epsg(4326) for src in sources):
                raise ValueError('Copernicus DEM tile CRS changed unexpectedly')
            source_bounds = [min(src.bounds.left for src in sources),
                             min(src.bounds.bottom for src in sources),
                             max(src.bounds.right for src in sources),
                             max(src.bounds.top for src in sources)]
            west, south, east, north = bounds
            padding_x = (east - west) * 0.11
            padding_y = (north - south) * 0.11
            padded = [max(source_bounds[0], west - padding_x),
                      max(source_bounds[1], south - padding_y),
                      min(source_bounds[2], east + padding_x),
                      min(source_bounds[3], north + padding_y)]
            width = min(8192, max(512, math.ceil((padded[2] - padded[0]) * 3600)))
            height = min(8192, max(512, math.ceil((padded[3] - padded[1]) * 3600)))
            raster, transform = merge(sources, bounds=padded,
                                      res=((padded[2] - padded[0]) / width,
                                           (padded[3] - padded[1]) / height),
                                      nodata=0, resampling=Resampling.bilinear)
        finally:
            for src in sources: src.close()
    elevation = np.nan_to_num(raster[0], nan=0, posinf=0, neginf=0).astype('float32')
    np.maximum(elevation, 0, out=elevation)
    if not np.any(elevation > 0.75):
        raise ValueError('Copernicus DEM contains no land in the selected area')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.copdem-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result'
        staged.mkdir()
        mosaic = staged / 'dem-source.tif'
        with rasterio.open(mosaic, 'w', driver='GTiff', width=elevation.shape[1],
                           height=elevation.shape[0], count=1, dtype='float32', crs='EPSG:4326',
                           transform=transform, nodata=0, compress='deflate', tiled=True,
                           blockxsize=256, blockysize=256) as output:
            output.write(elevation, 1)
        report = {'format': 'agf-copernicus-dem-download/v1',
                  'requested_bounds_wgs84': list(bounds), 'mosaic_bounds_wgs84': padded,
                  'mosaic_size': [elevation.shape[1], elevation.shape[0]],
                  'mosaic_sha256': _digest(mosaic), 'source_tiles': rows,
                  'attribution': 'Contains modified Copernicus DEM data (2021)',
                  'license_url': 'https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM',
                  'runtime_verified': False}
        (staged / 'dem-source.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
        staged.rename(destination)
    if progress: progress(100, 'Copernicus DEM mosaic ready')
    return report


def _geofabrik_region(index, bounds):
    selection = box(*bounds)
    choices = []
    for item in index.get('features', []):
        properties = item.get('properties', {})
        shp = properties.get('urls', {}).get('shp')
        if not isinstance(shp, str) or not shp.endswith('-latest-free.shp.zip'):
            continue
        geometry = shape(item['geometry'])
        overlap = geometry.intersection(selection).area / selection.area
        if overlap >= 0.05:
            choices.append((overlap, geometry.area, properties['id'], shp))
    if not choices:
        raise ValueError('No bounded Geofabrik OSM extract covers the selected land')
    # Index polygons often overlap: Crimea is present in both the Ukraine and
    # Crimean district polygons. Prefer a compact region when it covers nearly
    # as much of the selected rectangle as the broad country polygon.
    maximum = max(choice[0] for choice in choices)
    candidates = [choice for choice in choices if choice[0] >= max(0.20, maximum * 0.75)]
    _, _, identifier, shapefile_url = min(candidates, key=lambda choice: (choice[1], -choice[0]))
    return identifier, shapefile_url.replace('-latest-free.shp.zip', '-latest-free.gpkg.zip')


def download_osm_geopackage(bounds_wgs84, destination, cache, *, progress=None):
    """Fetch a licensed regional OSM extract for locally rendered raster tiles."""
    bounds = _bounds(bounds_wgs84)
    destination = Path(destination).resolve()
    cache = Path(cache).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    with _session() as session:
        index_response = session.get(GEOFABRIK_INDEX, timeout=40)
        index_response.raise_for_status()
        identifier, url = _geofabrik_region(index_response.json(), bounds)
        if progress: progress(10, 'Choosing regional OpenStreetMap extract')
        zip_path = cache / 'geofabrik' / (identifier.replace('/', '_') + '-latest-free.gpkg.zip')
        archive = _download(session, url, zip_path, 500_000_000,
                            progress=(lambda fraction: progress(round(10 + fraction * 65),
                                'Downloading OpenStreetMap regional extract') if progress else None))
    if progress: progress(75, 'Extracting OpenStreetMap geometry')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.osm-extract-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'result'
        staged.mkdir()
        with zipfile.ZipFile(zip_path) as zipped:
            contents = [item for item in zipped.infolist() if item.filename.endswith('.gpkg')]
            if len(contents) != 1 or contents[0].file_size > 700_000_000:
                raise ValueError('Regional OSM GeoPackage archive inventory changed')
            with zipped.open(contents[0]) as source, (staged / 'source.gpkg').open('wb') as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
        report = {'format': 'agf-osm-extract-download/v1', 'requested_bounds_wgs84': list(bounds),
                  'region_id': identifier, 'archive': archive,
                  'geopackage_sha256': _digest(staged / 'source.gpkg'),
                  'source_url': url,
                  'attribution': 'Map data © OpenStreetMap contributors (ODbL)',
                  'tile_server_bulk_downloaded': False, 'runtime_verified': False}
        (staged / 'osm-source.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
        staged.rename(destination)
    if progress: progress(100, 'OpenStreetMap source extract ready')
    return report
