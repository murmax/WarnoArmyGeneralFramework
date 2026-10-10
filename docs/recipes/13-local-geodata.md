# Geographic inputs: local files and renderer details

[Basic geography workflow](13-geography.md) · [Русская версия](13-local-geodata.ru.md) · [Recipe index](../RECIPES.md)

## Use your own elevation GeoTIFF

The file must contain elevation in meters in its first raster band, a valid CRS and geographic transform. An unreferenced TIFF or an RGB satellite photograph is not an elevation source. Different horizontal CRS can be reprojected; vertical unit conversion is not inferred.

Preview and inspect:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geotiff-inspect data/my-dem.tif artifacts/dem-inspect-01
```

Open its `preview.png` and `geotiff.json`. The preview is north-up. Choose an entirely covered rectangle, then crop:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geotiff-crop data/my-dem.tif 32.45 44.28 34.15 45.55 2048 artifacts/dem-crop-01 --elevation-ceiling-m 1200
```

Replace source/coordinates. Crop output `heightmap.png` is northwest-origin and north-up, ready for the world's row convention; use `crop.json` for bounds and hash. Destination must be new.

| Argument | Limits / effect |
| --- | --- |
| Source | Existing GeoTIFF with CRS, dimensions at least 2×2 and at least one raster band |
| west/south/east/north | Finite ordered WGS84; longitude −180…180, latitude −90…90, each span ≥0.001° |
| Crop rectangle | Completely inside the reprojected source's available bounds |
| Resolution | Square integer 128–8192 |
| Elevation ceiling | Finite 1–10000 m, default 1600 |
| Destination | New directory |

Crop uses bilinear resampling, clamps negative/nonfinite elevation to zero and normalizes by the requested ceiling into 16-bit values. A selection without land elevation above 0.75 m is rejected. Elevation above the ceiling is clipped. Connect the resulting heightmap as shown in [world settings](13-geography.md#world-geometry-and-height-controls).

## Render from your own OSM GeoPackage and DEM

There is no `--osm-file` or `--dem-file` switch on `geodata-import`. That command downloads its own selected sources. For existing compatible files, the published renderer exposes a callable function. This copyable command uses that existing function; it does not require editing framework code:

```powershell
./.venv/Scripts/python.exe -B -c "from warno_ag.osm_tiles import render_osm_tiles; render_osm_tiles('data/source.gpkg', 'data/my-dem.tif', [32.45, 44.28, 34.15, 45.55], 'artifacts/local-surface-01', zoom=12, surface_size=4096, render_labels=False)"
```

Replace the paths and rectangle. Create the heightmap separately with `geotiff-crop`. The renderer creates its own `surface.png`, `tile-mosaic.png`, PNG tiles, preliminary `strategic-grid-cells.json` and `osm-tiles.json`.

GeoPackage compatibility requirements:

- Features are in EPSG:4326 longitude/latitude. The renderer interprets coordinates as degrees rather than transforming arbitrary vector CRS.
- GeoPackage geometry uses a supported little-endian header and WKB geometry.
- Each required table has `geom`, `fclass`, `name` columns. Tables may be empty but cannot be missing.
- Polygon/line/point and multipart geometries are supported in the relevant layers.

| Required table | Rendered content |
| --- | --- |
| `gis_osm_landuse_a_free` | Styled land-use polygons |
| `gis_osm_natural_a_free` | Styled natural polygons |
| `gis_osm_water_a_free` | Water polygons |
| `gis_osm_buildings_a_free` | Building footprints |
| `gis_osm_waterways_free` | Watercourse lines |
| `gis_osm_railways_free` | Railway lines |
| `gis_osm_roads_free` | Road/track/path lines |

Optional `gis_osm_places_free` is queried only with `render_labels=True`, which draws named `city` and `town` points. The standard import keeps labels off because native campaign labels can be localized and remain separate from the raster.

Arbitrary `.pbf`, Shapefile or a differently structured `.gpkg` is not accepted directly. Prepare a compatible GeoPackage externally before this call. The current interface does not provide arbitrary layer-name/column/CRS switches or a universal vector-file converter.

## What the renderer draws

Rendering starts with DEM-colored land/sea and light gradient shading, then draws the selected OSM layers in order. Styled polygon classes:

- Forest/wood; scrub/heath; grass/meadow/park/recreation_ground.
- Farmland/farm/orchard/vineyard.
- Residential/commercial; industrial/military/railway land use.
- Beach/sand; cemetery/allotments.

Other land-use/natural classes are skipped. Water/building polygons are filled. Rivers and railways are 2-pixel lines. Roads receive a border and interior, with interior widths 7 px for motorway/trunk, 6 for primary/primary_link, 5 secondary/secondary_link, 4 tertiary/tertiary_link, 3 residential/unclassified/living_street, 2 service/track, 1 for other classes. These are pixels of the intermediate render, not game cell widths.

Colors/line widths and polygon filters are fixed by the current renderer; they are not public YAML or CLI style settings. Users can supply another finished RGB surface image when another visual style is needed. That does not change movement cells.

Administrative boundaries, address labels, POI symbols, transit routes and contour lines are not drawn. This is a deliberately limited renderer, not the complete OpenStreetMap Carto style. Polygon drawing uses exterior rings; interior-hole fidelity is limited. Bridges/tunnels do not have a full cartographic stacking model.

Contrast is multiplied by 1.12 and brightness by 0.84 for strategic lighting. The image is first rendered in EPSG:3857, then cropped/reprojected to the chosen EPSG:4326 rectangle and retains its north-up, northwest-origin orientation. Zoom 8–13, surface size 512–8192 and the 48-million intermediate pixel bound apply to this local-file call too.

## Preliminary terrain classification

The renderer produces a **101×101** whole-rectangle classification from averaged masks:

| Priority | Test | Terrain |
| --- | --- | --- |
| 1 | Water mask ≥0.60 | StrategicWater |
| 2 | Urban mask ≥0.36 | StrategicUrban |
| 3 | Urban mask ≥0.11 | StrategicSemiUrban |
| 4 | Forest mask ≥0.42 | StrategicForest |
| 5 | Otherwise | StrategicPlain |

Urban land-use masks use weight 220/255, building footprints 1, forest polygons 1. Water mask is derived from DEM elevation ≤0.7 m, **not** all drawn OSM water polygons. Thus a high-elevation lake may be blue on the picture without becoming a water cell, while very low land may be classified as water. Inspect and correct the result; automatic thresholds do not establish fully accurate strategic terrain.

Road movement flags are not created by this renderer. Its road layer is visible art only. Set `road: true` in the appropriate logical cells separately. There is no automatic modern-to-historical geography conversion or universal 3D building/forest placement.

## Use the generated whole-map cells

For a first whole-map prototype retaining a 2×2 world, you can deliberately use the full native bounds as playable/logical bounds. This example rewrites `map.yaml` and `profile.yaml`; keep a source copy first. It preserves other YAML data, but comments/formatting can change.

```powershell
@'
import json
from pathlib import Path
import yaml

source = Path('campaigns/my-campaign')
cells_file = Path('artifacts/my-geodata-01/surface/strategic-grid-cells.json')
bounds = [0, 0, 1310720, 1310720]
cells = json.loads(cells_file.read_text(encoding='utf-8'))

map_file = source / 'map.yaml'
map_data = yaml.safe_load(map_file.read_text(encoding='utf-8'))
map_data['strategic_grid'] = {
    'dimensions': {'width': 101, 'height': 101},
    'bounds': bounds, 'default_terrain': 'StrategicPlain', 'cells': cells,
}
profile_file = source / 'profile.yaml'
profile = yaml.safe_load(profile_file.read_text(encoding='utf-8'))
profile['bounds'] = bounds
profile['strategic_map'].update(
    bounds=bounds, playable_bounds=bounds,
    dimensions={'width': 101, 'height': 101},
)
for path, data in [(map_file, map_data), (profile_file, profile)]:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
'@ | ./.venv/Scripts/python.exe -B -
```

This applies only when `world.bounds` is the same 2×2 extent, render_cases is 2×2, and you intend the full region to be playable. It does not move old entities or scene objects and does not add roads. Change matching map names before rebuilding a modified world.

For a smaller playable region or another world size, do not reuse these constants blindly. Derive cell bounds/dimensions for that region and select/resample the original classification accordingly. The native movement step stays 13000; image resolution stays independent. The public interface has no general command for every possible crop/resample of this cells JSON.

## Download coverage and cache

`geodata-import` uses the [Geofabrik regional index](https://download.geofabrik.de/index-v1.json) and [Copernicus GLO-30](https://registry.opendata.aws/copernicus-dem/). Raw sources have per-file receipts with URLs, sizes and SHA256. Reusing a matching cache preserves those bytes; “latest” in a URL does not automatically refresh a cached extract.

Only one compact overlapping OSM region is selected. That is not a guarantee of complete coverage of a cross-border rectangle; inspect `geodata.json` and `osm-source.json`. For such areas, use a prepared compatible merged extract or choose a rectangle within one available region. An OSM region too large for the byte limit or missing public DEM coverage is a real input limitation.

For newer data use a new cache directory and new import output. A changed/missing receipt or partial download is rejected rather than silently replaced. Retain OpenStreetMap contributor attribution/ODbL and the Copernicus source license alongside distributed derived assets. Sources are geographic data snapshots; their provenance is separate from the gameplay YAML.
