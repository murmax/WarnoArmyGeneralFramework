# Campaign authoring recipes

[Getting started](GETTING_STARTED.md) · [YAML field reference](YAML_REFERENCE.md) · [Русская версия](RECIPES_RU.md)

Use this page to choose a task. Each linked guide starts with a basic procedure, then explains related changes, every relevant setting and the current implementation's limits. Examples assume an independent `campaigns/my-campaign` cloned from the supplied campaign.

## Prepare once

After installing the environment as described in Getting started, run from the repository root in PowerShell:

```powershell
$game = 'C:/Program Files (x86)/Steam/steamapps/common/WARNO'
./.venv/Scripts/python.exe -B scripts/campaign.py prepare --game $game
./.venv/Scripts/python.exe -B scripts/campaign.py clone campaigns/kacha campaigns/my-campaign --id my_campaign
```

Replace the game path with your installation. Set `$game` again in a new terminal. `clone` needs a new destination. Keep the source campaign intact.

## Choose a change

| # | Task and detailed guide | Smallest useful edit |
| --- | --- | --- |
| 1 | [Campaign identity, titles and sides](recipes/01-identity.md) | Edit `campaign.yaml.title`; retain the cloned technical ID |
| 2 | [Duration, dates and schedules](recipes/02-schedule.md) | Change `campaign.yaml.turns`; review dated consumers |
| 3 | [Battalion rosters and custom packs](recipes/03-rosters.md) | Change a platoon's `units[].count`, or copy a pack for a local change |
| 4 | [Command, supply, artillery and AA](recipes/04-support.md) | Add real support packs to a headquarters platoon |
| 5 | [Reserve cards and deployment points](recipes/05-reserves.md) | Add a unique battalion to `production.groups` |
| 6 | [Automatic arrivals and event effects](recipes/06-events.md) | Use `reinforcements.yaml` for a scheduled automatic arrival |
| 7 | [Difficulty and conditional force variants](recipes/07-conditions.md) | Add a `when` requirement to a separate reserve group |
| 8 | [Initial state, losses and temporary locks](recipes/08-readiness.md) | Set `deployments[].frozen_turns`, keeping positive normal AP |
| 9 | [Aircraft, airfields and withdrawal](recipes/09-aviation.md) | Change a wing's `available.turn` |
| 10 | [Objectives, influence, routes and endings](recipes/10-objectives.md) | Move a flag's `position` and review nearby influence |
| 11 | [Artwork, decision cards and emblems](recipes/11-artwork.md) | Replace a referenced local source image |
| 12 | [Names and translations](recipes/12-localization.md) | Update an English source string and every enabled translation table |
| 13 | [Terrain, OSM, heightmaps and scenery](recipes/13-geography.md) | Import a geographic rectangle or replace existing raster assets |
| 14 | [Validation, build, installation and distribution](recipes/14-build.md) | Check, build a complete bundle, then install using its result paths |

## Check each coordinated change

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/my-check-01
```

Use a new output directory for the next attempt, such as `my-check-02`. A check prepares and validates source inputs; it does not launch or install the campaign. If an English name or text changes, update all enabled `localization.yaml` tables too.

## Build when the source is ready

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py build campaigns/my-campaign --game $game --output artifacts/my-build-01
```

This runs official generation, map baking when applicable, resource cooking and complete-bundle validation. It does not install. Continue with [the build/install guide](recipes/14-build.md). Play changes in a fresh campaign because saves retain previous definitions and state.

**Three reading levels:** this index → the basic procedure at the top of a topic → settings, mechanics and troubleshooting further down that topic. The [YAML reference](YAML_REFERENCE.md) supplies the full file schema. Supported examples use the existing format; adding an undocumented key does not add a game feature.
