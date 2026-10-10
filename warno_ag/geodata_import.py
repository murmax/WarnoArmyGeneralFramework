"""One bounded, on-demand geographic import for a user-picked campaign map.

Raw public sources stay in a checked cache. The project receives only locally
rendered assets and a provenance report; OSMF tile servers are never scraped.
"""
import json
from pathlib import Path
import sys
import tempfile

from .geodata_download import _bounds, download_copernicus_dem, download_osm_geopackage
from .geotiff import crop_geotiff, inspect_geotiff
from .osm_tiles import render_osm_tiles


def import_geographic_map(bounds_wgs84, destination, cache, *, resolution=2048,
                          surface_size=4096, elevation_ceiling_m=1600, zoom=12,
                          progress=None):
    bounds = _bounds(bounds_wgs84)
    destination = Path(destination).resolve()
    cache = Path(cache).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_progress = None

    def update(percent, stage):
        nonlocal last_progress
        if progress:
            current = (max(0, min(100, round(percent))), stage)
            if current != last_progress:
                progress(*current)
                last_progress = current

    def rewrite_report(path, source_fields):
        report = json.loads(path.read_text(encoding='utf-8'))
        report.update(source_fields)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report

    with tempfile.TemporaryDirectory(prefix='.geodata-import-', dir=destination.parent) as temp:
        stage = Path(temp) / 'result'
        stage.mkdir()
        dem_dir = stage / 'dem'
        osm_dir = stage / 'osm'
        update(1, 'Locating Copernicus elevation sources')
        dem = download_copernicus_dem(bounds, dem_dir, cache,
                                      progress=lambda p, s: update(2 + p * 0.35, s))
        update(40, 'Locating OpenStreetMap extract')
        osm = download_osm_geopackage(bounds, osm_dir, cache,
                                      progress=lambda p, s: update(40 + p * 0.30, s))
        update(72, 'Cropping and orienting heightmap')
        cropped = crop_geotiff(dem_dir / 'dem-source.tif', bounds, resolution,
                               stage / 'heightmap', elevation_ceiling_m=elevation_ceiling_m)
        inspect_geotiff(dem_dir / 'dem-source.tif', stage / 'dem-preview')
        cropped = rewrite_report(stage / 'heightmap' / 'crop.json',
                                 {'source': '../dem/dem-source.tif'})
        rewrite_report(stage / 'dem-preview' / 'geotiff.json',
                       {'source': '../dem/dem-source.tif'})
        update(78, 'Rendering OpenStreetMap tiles, map surface and cells')
        rendered = render_osm_tiles(osm_dir / 'source.gpkg', dem_dir / 'dem-source.tif',
                                    bounds, stage / 'surface', zoom=zoom,
                                    surface_size=surface_size, render_labels=False)
        rendered = rewrite_report(stage / 'surface' / 'osm-tiles.json',
                                  {'source': '../osm/source.gpkg',
                                   'dem': '../dem/dem-source.tif'})
        if cropped.get('raster_origin') != 'northwest' or rendered.get('raster_origin') != 'northwest':
            raise ValueError('Geographic import requires aligned north-up height and surface rasters')
        report = {
            'format': 'agf-geographic-map-import/v1',
            'raster_origin': 'northwest',
            'bounds_wgs84': list(bounds), 'heightmap': 'heightmap/heightmap.png',
            'preview': 'dem-preview/preview.png',
            'surface': 'surface/surface.png',
            'strategic_grid_cells': 'surface/strategic-grid-cells.json',
            'dem_source_sha256': cropped['source_sha256'],
            'dem': dem, 'osm': osm, 'render': rendered,
            'attribution': ['Contains modified Copernicus DEM data (2021)',
                            'Map data © OpenStreetMap contributors (ODbL)'],
            'tile_server_bulk_downloaded': False, 'runtime_verified': False,
        }
        (stage / 'geodata.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
        stage.rename(destination)
    update(100, 'Geographic map ready')
    return report


def cli_progress(percent, stage):
    print(f'AGF_EDITOR_PROGRESS\t{percent}\t{stage}', file=sys.stderr, flush=True)
