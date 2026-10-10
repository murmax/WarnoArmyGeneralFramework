# Kacha: Defense of Sevastopol — source example

This folder contains the authoring source of **Kacha V20**, with corrected north-up geography and the V19 rosters, events and AI rules. The map surface, heightmap, movement cells and spatial placements were migrated together; see ORIENTATION_MIGRATION.json. New geographic imports need no transposition. It is a complete source example, not a precompiled game mod. The [Workshop campaign](https://steamcommunity.com/sharedfiles/filedetails/?id=3811284575) may be at a different release; source validation is separate from gameplay acceptance.

Start with [the guide](../../docs/GETTING_STARTED.md) or [русской инструкцией](../../docs/GETTING_STARTED_RU.md). Every YAML file is described in the [reference](../../docs/YAML_REFERENCE.md) / [справочнике](../../docs/YAML_REFERENCE_RU.md).

## Main relationships

- `campaign.yaml`: 20-turn scenario, playable sides, objectives, menu and AI policy.
- `battalions/forces.yaml` + `packs.yaml`: all battalion/company/platoon rosters and tactical-unit/transport combinations.
- `deployments.yaml` + `ai.yaml`: starting ground forces, initial state, locks and orders.
- `production.yaml`: reserve cards, divisions, arrival turns, placement points and conditional difficulty variants.
- `events.yaml`: Normal/Harsh choices, SEAL landing choice, air-support choice and notices.
- `aviation.yaml`: airfields, arriving aircraft, losses and carrier withdrawal.
- `map.yaml` + `world.yaml`: strategic rules/positions and visible terrain/scenery.
- `cinematics.yaml`, `event-images.yaml`, `emblems.yaml`, `localization.yaml`: presentation and translated text.
- `profile.yaml`: the bundled native map adapter. Use it together with this source.

The native game catalogs, prepared LevelBuild data and cooked textures are generated from the author's installed WARNO. They do not belong in this source folder. The original example identity is retained for reproducibility; use the `clone` command to create your own independent campaign and map identities.

Only referenced artwork and the Wikimedia provenance of custom emblems are included. Superseded pictures and old campaign-version notes have been removed. The modern real 810th brigade patch is deliberately retained as an identity cue, rather than represented as a verified 1989 insignia. Read the attribution files before reusing assets.

Russian and English are authored in the content files; French, German, Spanish, Polish and Simplified Chinese are supplied through `localization.yaml`. Change the corresponding translations when editing English source text. Short unit/company/platoon names must fit the game's 30 UTF-16-unit limit in every language.

A finished standalone mod is built with:

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py build campaigns/kacha --game $game --output artifacts/kacha-build-01
```

Do not activate a local copy together with the Workshop version. Build output and save-game acceptance are separate; cooperative behavior has not been validated.
