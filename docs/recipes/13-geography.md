# 13. Terrain, OSM, heightmaps and scenery

[Recipe index](../RECIPES.md) · [Русская версия](13-geography.ru.md) · [Local files and renderer details](13-local-geodata.md)

## Basic procedure: import another geographic rectangle

Run from the repository root in the prepared Python environment:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geodata-import 32.45 44.28 34.15 45.55 artifacts/my-geodata-01 --cache artifacts/geodata-cache --resolution 2048 --surface-size 4096 --elevation-ceiling-m 1200 --zoom 12
```

Replace the four coordinates with **west longitude, south latitude, east longitude, north latitude**. This example selects a rectangle only; it is not a campaign position. The output directory must be new. The cache can be reused for matching source downloads.

The command downloads selected Copernicus elevation tiles and a Geofabrik OSM extract, then renders source assets locally. It does not install or create a complete campaign. Geographic generation needs the framework environment and network access; baking the result into a campaign also needs WARNO's supplied tools.

Main outputs:

| Output | Use |
| --- | --- |
| `heightmap/heightmap.png` | 16-bit game-oriented height raster |
| `surface/surface.png` | RGB map texture |
| `surface/strategic-grid-cells.json` | Preliminary 101×101 whole-rectangle terrain classification |
| `osm/source.gpkg` | Downloaded vector features |
| `dem/dem-source.tif` | Joined elevation source |
| `surface/tile-mosaic.png` | Rendered map preview/mosaic |
| `geodata.json` and component reports | Actual paths, bounds, source hashes and attribution |

## Basic procedure: use the images in your campaign

1. Copy the generated heightmap and surface into `campaigns/my-campaign/artwork/`.
2. Update their relative file paths under `world.yaml.heightmap` and `surface`.
3. Retain consistent world/profile geometry and choose a **new matching map name** in `world.yaml.map_name` and `profile.yaml.strategic_map.map_name` when changing baked source.
4. Update georeference from the import report if present. Reposition flags, labels, units, airfields, reserve points and waypoints for the new geography.
5. Replace or clear old scenery objects; they do not move with the raster.
6. Rebuild terrain cells and roads as described below. Old movement rules do not follow the new image.
7. Check, build and inspect orientation, coast, movement and heights in a new campaign.

```yaml
# Inside world.yaml; retain the remaining required world fields
heightmap:
  file: artwork/heightmap.png
  max_altitude_lbu: 22
surface:
  file: artwork/surface.png
```

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/geography-check-01
```

New imported images are **north-up**, with a **northwest** origin: columns increase eastward along native x, and rows increase southward along native y. Use the generated surface, heightmap and cells together without flipping them. Releases through 1.1.0 incorrectly emitted south-up geography; old projects need an explicit coordinated migration, not another flip on new imports. Legacy `raster_origin: southwest` is still readable and is never silently migrated. Camera orientation does not transform source pixels.

## Three independent map products

| Product | Controlled by | Mechanical effect |
| --- | --- | --- |
| Visible colors/roads | `world.surface.file` | Map appearance |
| Height and buildings/trees | `world.heightmap`, `world.objects` | Rendered terrain and point scenery |
| Movement terrain/roads | `map.strategic_grid` | Native terrain/road classification |

A painted road does not speed units; a forest cell does not create trees. The importer renders/classifies data but does not provide a universal automatic building/tree-placement command. Source-derived point placement must be authored in `world.objects`; [local renderer details](13-local-geodata.md) explain what is and is not automatic.

## Import command settings

| Argument | Default / limits | Effect |
| --- | --- | --- |
| west/south/east/north | Required four finite degrees | Ordered WGS84 rectangle; longitude −180…180, latitude strictly within −85…85, ≤3° per axis |
| destination | Required new directory | Complete import output |
| `--cache` | Required directory | Reusable raw downloads and source receipts |
| `--resolution` | 2048; integer 128–8192 | Square heightmap resolution |
| `--surface-size` | 4096; integer 512–8192 | Square surface resolution |
| `--elevation-ceiling-m` | 1600; finite 1–10000 m | Elevation normalization/clipping ceiling |
| `--zoom` | 12; integer 8–13 | Local web-map-style rendering detail |

The intermediate tile mosaic cannot exceed 48,000,000 pixels. Elevation selection is limited to 1–16 public tiles, each download ≤300,000,000 bytes; the OSM archive limit is 500,000,000 bytes and its GeoPackage ≤700,000,000. The importer selects one regional OSM extract: [coverage and cache limitations](13-local-geodata.md#download-coverage-and-cache).

Resolution and zoom change image detail, not the number or size of movement cells. High zoom can hit the intermediate-pixel limit even if final surface resolution stays 4096.

## World geometry and height controls

World root requires schema `agf-world/v1`, `id`, `map_name`, `bounds`, `render_cases`, `raster_axes`, `heightmap`, `surface`, `objects`. The [file reference](../YAML_REFERENCE.md#16-worldyaml) gives a complete declaration.

| Field | Values / rule |
| --- | --- |
| `id` | Unique lowercase identifier |
| `map_name` | Latin letter first, then letters/digits/underscores; same in profile |
| `bounds` | `[0,0,max_x,max_y]`, positive extents |
| `render_cases` | Positive integer width/height; each spans 655360 native units |
| `raster_axes` | `columns_x_rows_y` |
| `heightmap.file` | Campaign-relative 16-bit grayscale PNG, each axis 2–8192 |
| `heightmap.max_altitude_lbu` | Finite >0 and strictly <5000/215 |
| Height alternative | `samples` rectangular normalized grid ≥2×2, values 0…1; `resolution: [width,height]` 2–8192; same maximum altitude |
| `surface.file` | Opaque RGB PNG/WebP, each axis 2–8192 |
| `objects` | Explicit list, `[]` allowed |

Do not mix file and inline height samples. Native extent must equal render-case count ×655360 on each axis. A 2×2 map is `[0,0,1310720,1310720]`; the playable region may be a smaller rectangle. This render-case count is unrelated to 101×101 AP cells or the image pixel size.

The maximum raster value reaches `max_altitude_lbu ×215` native units. Terrain must stay strictly below the 5000-unit strategic overlay. Increasing the DEM normalization ceiling reduces relative heights; lowering it raises contrast but clips peaks. Changing the world maximum changes absolute rendered altitude. Inspect both; do not raise the whole map to create mountain contrast.

Optional `georeference` requires `crs: EPSG:4326`, geographic bounds, `elevation_ceiling_m` 1–10000, 64-character lowercase source SHA256, and `raster_origin: northwest`. Use the DEM source hash from the report. This records provenance and mapping, not automatic unit relocation.

For an unrotated geographic/world rectangle, coordinate conversion is:

```text
x = min_x + (longitude - west) / (east - west) * (max_x - min_x)
y = min_y + (north - latitude) / (north - south) * (max_y - min_y)
```

Check recognizable corner landmarks before assigning many placements. Longitude/latitude widths do not represent equal physical distances; choose a sensible extent/aspect ratio for the selected area.

## Movement cells and roads

`map.yaml.strategic_grid` needs dimensions `{width,height}`, bounds and default_terrain. Optional `cells` must enumerate **every** row/column exactly once if present. Cell optional ID is `r<row>c<column>`; terrain defaults to default_terrain, road defaults false.

```yaml
strategic_grid:
  dimensions: {width: 4, height: 3}
  bounds: [100000, 100000, 152000, 139000]
  default_terrain: StrategicPlain
```

With cells omitted this creates a uniform logical grid. This is a structural example; for your map keep bounds inside playable_bounds and match profile dimensions. Its physical 13000-unit logical cells are deliberately independent of PNG resolution.

Supported terrain: `StrategicPlain`, `StrategicForest`, `StrategicSemiUrban`, `StrategicUrban`, `StrategicWater`. A complete cell entry can add `road: true`, except on blocking water. There is no public `StrategicMountain` or arbitrary per-edge road-cost field. Relief is a separate visible product.

Native AP raster size follows full map extent and the fixed 13000-unit step. Authored logical cells are projected onto it. Import JSON is a 101×101 full-rectangle preliminary grid; it cannot be pasted unchanged into a 48×55 playable grid. Select/resample the intended region and renumber rows/columns, or deliberately adopt a whole-map grid and matching profile/playable geometry. [A copyable whole-map import procedure](13-local-geodata.md#use-the-generated-whole-map-cells) is provided for that case.

## Place buildings and trees

Export `scenery.csv` through the catalog command. Add explicit instances under world.objects:

```yaml
- id: town_building_01
  asset: your_registered_point_asset
  position: [877500, 331500]
  rotation_degrees: 90
  scale: 1
  ground_offset_lbu: 0
```

Replace the asset with a supported registered point scenery name. Each object needs a unique lowercase ID, in-bounds position, finite rotation 0–360, finite positive scale and finite ground offset. Set normal ground offset to 0: engine terrain adaptation supplies height; adding sampled terrain height again can float the object above ground.

Repeat distinct instances for denser settlements/forests and reconcile their movement-cell types. Arbitrary native scenery patterns are not exposed as point objects. Scenery generation does not automatically infer high-rise districts, tactical urban density or road movement from the picture.

In scenery.csv, supported point registrations have descriptor_class
`TSceneryDescriptorModel3D`, `TSceneryDescriptorMultiState`,
`TSceneryDescriptorMultiLOD`, or `TSceneryDescriptorImpostor`. Select one of
these classes rather than an unrelated pattern/graph registration.

## Troubleshooting

Mirrored/upside-down map: releases through 1.1.0 emitted a known south-up reflection. New imports are north-up; check `raster_origin` and do not flip them again. For a legacy map, migrate surface, heightmap, movement rows/bounds and all geographic placements together; a camera rotation alone cannot repair a reflection. Water movement mismatch: review preliminary masks and manually correct cells. Old scenery in a new region: replace object positions and other campaign placements. Cache-source mismatch: change matching map_name in world/profile and use a new build output. Floating scenery: use ground offset rather than adding terrain twice. Flat/overlay-crossing mountains: distinguish normalization ceiling from absolute world altitude. For local GeoTIFF/OSM files and exact renderer layers continue with [the advanced input guide](13-local-geodata.md).
