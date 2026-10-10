# WARNO Army General Framework

Create and modify native **Army General campaigns for WARNO** using readable YAML. The framework builds a complete, standalone campaign mod; Workshop players do not need Python or a separate framework installation.

**1.1.1 · Windows · Python 3.11+ · MIT code license**

## Start here

| What you want to do | Read |
| --- | --- |
| Create your first campaign | [Getting started](docs/GETTING_STARTED.md) · [Начало работы](docs/GETTING_STARTED_RU.md) |
| Understand every campaign YAML file | [YAML reference](docs/YAML_REFERENCE.md) · [Справочник YAML](docs/YAML_REFERENCE_RU.md) |
| Change forces, reinforcements, events or the map | [Practical recipes](docs/RECIPES.md) · [Практические примеры](docs/RECIPES_RU.md) |
| Inspect a complete working source example | [Kacha source](campaigns/kacha/README.md) |
| Play the finished example | [Kacha in Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3811284575) |

The guides explain fields, identifiers, units, supported values, relationships between files and the complete build/install workflow. You do not need to read the framework's Python code or edit WARNO's NDF files to use the documented authoring format.

## What is included

- `campaigns/kacha/`: the **V20** example with corrected north-up geography, with battalion rosters, map, world, all seven campaign languages, events, aviation, Normal/Harsh decisions and the source artwork used by the campaign.
- `scripts/campaign.py`: prepare, clone, inspect catalogs, check and build commands.
- `warno_ag/`: the compiler, native adapters, asset tools and complete-bundle installer.
- `warno_ag/data/`: compatibility data used by the native adapters.
- `docs/`: setup guides, YAML field references and practical recipes.
- `tests/`: development checks for contributors.

## Short version

Install 64-bit Python 3.11 or newer, download this repository as a ZIP or clone it, and open PowerShell in the extracted folder:

```powershell
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
$game = 'C:/Program Files (x86)/Steam/steamapps/common/WARNO'
./.venv/Scripts/python.exe -B scripts/campaign.py prepare --game $game
./.venv/Scripts/python.exe -B scripts/campaign.py clone campaigns/kacha campaigns/my-campaign --id my_campaign
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/my-check-01
```

Edit your copied YAML files, then build:

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py build campaigns/my-campaign --game $game --output artifacts/my-build-01
```

A check validates and prepares inputs. A build runs the supplied official compiler and map bake, cooks resources and verifies a complete bundle. **Neither installs or activates your campaign.** Follow the getting-started guide for installation using the paths in `build-result.json`.

## Requirements and supported scope

Authors need Windows, Python 3.11+, this repository and a compatible WARNO installation containing `WARNO.exe`, `Mods/ModData/base.zip` and the game's supplied tools. The preparation command obtains catalogs and compatibility inputs locally. You can select a game in another library with `--game`; game-path resolution follows that selection.

The native compatibility adapter remains pinned to the **201602** layout and verified archive hashes. A game update can require an adapter update. Use the source checks to validate your inputs, then build and test your campaign in WARNO.

The public format covers the strategic map and scenery, ground and aviation rosters, initial deployment and locks, grouped reinforcements, two-option events, conditional availability, AI orders, presentation, translation and victory conditions. It does not expose arbitrary game scripting, tactical unit-stat changes or unimplemented engine behavior. The reference states these limits explicitly.

Cooperative campaign support is experimental. Event synchronization needs multiplayer testing before a campaign is released for cooperative play.

## Support development

- [Boosty](https://boosty.to/murmax98)
- [Donate.Stream](https://donate.stream/murmax)

## License

Original framework code is [MIT](LICENSE). WARNO resources are read from your installation and are not distributed as source here. The example's geographic data and third-party emblems have separate attribution and licensing in [ASSET_CREDITS.md](campaigns/kacha/ASSET_CREDITS.md) and [GEODATA.json](campaigns/kacha/GEODATA.json).

This is an independent community project. Include the framework version, game version, exact command, error report and a small source example when reporting a build problem.
