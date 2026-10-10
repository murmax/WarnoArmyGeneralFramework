# Changelog

## 1.1.1 — north-up geographic generation

- Removed the erroneous north/south reflection from OSM surfaces, GeoTIFF heightmaps and generated terrain-cell rows. New imports retain northwest origin; no author-side transposition is required.
- Kacha V20 migrates the V19 geography, movement cells/bounds, every spatial placement and scenery heading together. Its campaign identity, rosters, events and AI rules remain unchanged.
- Python and editor import/export retain explicit raster orientation. Legacy southwest records remain readable and are never silently converted.
- Geographic-coordinate examples now use `y = min_y + (north - latitude)/(north - south)*(max_y - min_y)`.
- Source example now uses V20 and the approved historical photographs; unfinished nuclear modules are excluded from the public source stage.

Old saved campaigns are not migrated. Official map/campaign compilation and offline checks are separate from fresh-game visual and gameplay acceptance.

## 1.1.0 — authoring reference and Kacha example

- Complete current Kacha V17.2 YAML/world/artwork source as the main example.
- Removed historical demo campaigns, obsolete guides, redundant pictures and release-by-release narrative from the public authoring tree.
- English/Russian getting-started instructions, full per-file YAML reference and practical coordinated changes.
- Prepare, clone, catalog, check and complete-build helper commands.
- Selected installation path used by core authoring readers; compatibility dictionaries prepared locally.
- Explicit configurable ending-status flag bindings and menu side titles for another campaign.
- Current choice-dependent reserve/event schema and native decision-readiness correction included in source.

Source release only: this does not replace installed campaign files or migrate saves. Source validation, official compilation, single-player acceptance and cooperative acceptance are separate. Kacha V17.2's four decisions were accepted by its author; multiplayer remains unvalidated.

## Earlier releases

1.0.0 introduced the public authoring toolchain. 1.0.1 corrected frozen AP capacity and added translation tables. 1.0.2–1.0.4 expanded AI radius/controller authoring options. Kacha ultimately retained its earlier V11 AI policy; option availability does not establish accepted gameplay.
