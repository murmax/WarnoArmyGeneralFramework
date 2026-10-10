# Getting started: create a campaign from Kacha

This guide uses framework **1.1.1** and the **Kacha V20** source example. New geographic imports are north-up with `raster_origin: northwest`; do not flip them again. Kacha's surface, heightmap, movement cells and spatial placements were migrated together. Start a fresh campaign: older saves are not migrated. Legacy `southwest` metadata remains readable without automatic coordinate conversion. See [geographic inputs](recipes/13-geography.md) for the current coordinate formula and legacy-map guidance. V20's verified build and startup are separate from fresh-game gameplay acceptance.

No Python-programming or NDF knowledge is required. Copy these commands into PowerShell and edit YAML in a UTF-8 text editor. The [file reference](YAML_REFERENCE.md) describes fields and limits; [recipes](RECIPES.md) show coordinated changes. [Русская версия](GETTING_STARTED_RU.md).

## 1. Install the authoring environment

You need Windows, WARNO with its official tools, and 64-bit Python 3.11 or newer. Python is the framework runtime; do not use WARNO's older bundled Python. Install Python with Python Launcher from [python.org](https://www.python.org/downloads/windows/) if needed. The separate campaign editor is optional.

Download GitHub **Code → Download ZIP**, extract it to a directory with space, and open PowerShell there. You should see `README.md`, `scripts` and `campaigns`. Keep source separate from the game installation.

```powershell
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -e .
```

Run later commands from the repository root, using this environment.

## 2. Select your game

Use Steam's Installed Files → Browse, or locate the installation manually. Select the folder containing `WARNO.exe`, `Mods/ModData/base.zip` and `Tools/AssetCooker.exe`.

```powershell
$game = 'C:/Program Files (x86)/Steam/steamapps/common/WARNO'
./.venv/Scripts/python.exe -B scripts/campaign.py prepare --game $game
```

Replace the path with yours. Set `$game` again in each new terminal. Quoted paths can contain spaces. Preparation extracts the official catalog to ignored `artifacts/modgen-201602-template` and creates local dictionaries in `artifacts/compatibility`. It neither runs WARNO nor installs a mod. Repeated preparation checks the catalog against `base.zip`.

The adapter remains pinned to the compatible **201602** layout and archive hashes. A new game layout needs an appropriate adapter; do not replace expected hashes to defeat a compatibility error.

## 3. Create independent source

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py clone campaigns/kacha campaigns/my-campaign --id my_campaign
```

Use a new destination. The ID starts with a lowercase Latin letter, contains lowercase letters/digits/underscores and is at most 48 characters. It is separate from the displayed title. Clone changes campaign/profile/image identities and creates an independent map name. The original remains intact; future world changes will not share Kacha's map cache.

## 4. Edit the right file

| Change | Source |
| --- | --- |
| Title, date, duration, sides, victory, menu, AI policy | `campaign.yaml` |
| Battalions, companies, platoons, command and supply | `battalions/forces.yaml` |
| Tactical unit, transport, experience, units per roster entry | `packs.yaml` |
| Initial ground position, fatigue, AP, casualties, locks | `deployments.yaml` |
| Initial AI missions | `ai.yaml` |
| Reserve cards, divisions, arrival turns, points, conditions | `production.yaml` |
| Automatic ground arrivals without reserve cards | `reinforcements.yaml` |
| Notices, two-option decisions and consequences | `events.yaml` |
| Airfields, aircraft arrival and withdrawal | `aviation.yaml` |
| Objectives, influence, labels, waypoints, cell terrain/roads | `map.yaml` |
| Visible terrain, surface, buildings and trees | `world.yaml`, `artwork/` |
| Introduction, endings, start camera | `cinematics.yaml` |
| Event artwork and paired cards | `event-images.yaml` |
| Custom insignia | `emblems.yaml` |
| Other game languages | `localization.yaml` |
| Map dimensions, bounds and native bindings | `profile.yaml` |

A ground battalion appears through exactly one mechanism: deployment, production, event or automatic reinforcement. Aircraft belong in aviation. Even mutually exclusive variants require distinct battalion definitions: native mutable Pawn state cannot be shared. Start with a name and one roster; progress to reserve timing and terrain. Invented fields are rejected.

## 5. Obtain readable catalogs

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py catalog --game $game --output artifacts/catalog-01
```

Open these CSV files in a spreadsheet/text editor:

- `units.csv`: internal ID, English/Russian in-game names, category and tags. Use its ID in custom packs and `strategic.visual.unit`.
- `packs.csv`: existing unit/transport/experience/number combinations. Use its ID as platoon `type`.
- `scenery.csv`: registered scenery names for `world.yaml.objects[].asset`.

For inspected transport options:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag editor-pack-options Naval_Rifle_SOV
```

Replace the example ID. The existence of a vehicle does not make it an infantry transport; select an inspected option or declare a verified transport explicitly.

## 6. Check without running WARNO

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/my-check-01
```

This validates references, rosters, translations, artwork and prepared scene inputs. It writes intermediate output, does not run the game and does not install a playable mod. Edit YAML, not generated `campaign.compiled.json`. Each attempt needs a new output directory: use `my-check-02` after fixing an error. Source checks do not establish AI/balance/cooperative acceptance.

## 7. Build the complete mod

Save files and close WARNO before official compilation.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py build campaigns/my-campaign --game $game --output artifacts/my-build-01
```

The helper prepares artwork/world inputs, creates an isolated official workspace, runs map baking and ModGen, cooks resources and verifies a complete bundle. A first map build can take time. Keep `artifacts/` out of Git.

An existing bake with the same map name but different source is rejected. Set a matching **new** name in `world.yaml.map_name` and `profile.yaml.strategic_map.map_name`, such as `AGF_MyCampaignMap02`, then use a new output directory. Retain the old report rather than silently reusing stale geometry.

`artifacts/my-build-01/build-result.json` contains:

| `package` field | Meaning |
| --- | --- |
| `candidate` | Complete assembled mod directory |
| `bundle` | Verified immutable payload and manifest |
| `config` | Compiled campaign model/identity used for installation |

Use your own result paths, not another author's bundle hash.

## 8. Install, update and play

Close WARNO first. For a first installation:

```powershell
$result = Get-Content artifacts/my-build-01/build-result.json -Raw | ConvertFrom-Json
./.venv/Scripts/python.exe -B -m warno_ag full-install $result.package.bundle $result.package.config
./.venv/Scripts/python.exe -B -m warno_ag full-status $result.package.config
```

`full-install` installs **and activates**; there is no separate `full-activate`. Status should report `installed`, `active`, `owned`, `integrity_verified` as true. To replace an existing managed campaign:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag full-reinstall $result.package.bundle $result.package.config
```

To remove your owned campaign:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag full-uninstall $result.package.config
```

Install complete bundles, never selected files over old output. Normally activate one framework campaign at a time, and do not activate local Kacha together with its Workshop version. Begin a **fresh campaign**: saves retain old rosters/events/state. Play both sides, alternatives, reinforcement windows and endings. Cooperative event support is experimental and needs a separate multiplayer check.

## 9. Stage Workshop content

Staging is separate from publication:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config artifacts/my-workshop-01 --preview campaigns/my-campaign/artwork/workshop-cover.jpg
```

Create your own JPG/PNG cover below 1,000,000 bytes. The menu image is separate; this example supplies neither your publication identity nor a universal Workshop cover. Export creates `stage.json`, `preview/` and ready content under `mod/`, initially with ID zero. Upload that content tree, not the repository or all artifacts.

Updates use **your** verified prior `publication.json` through `--publication-receipt`, never Kacha's item ID. WARNO's uploader and SteamCMD have separate login/publication flows. Passwords belong only in local prompts. `workshop_content_update.py` updates an existing owned item through running Steam, submitting only content/cover. Private first-upload helpers are covered in [maintenance notes](MAINTENANCE.md).

## 10. Troubleshooting

| Error | Check |
| --- | --- |
| Missing Python | 64-bit Python and Launcher; recreate `.venv` |
| `missing`, `extra`, duplicate YAML key | Indentation, exact field and duplicated mapping keys |
| Unknown unit/pack/flag/battalion | Correct catalog and referenced declaration |
| Battalion used more than once | Distinct definition for every possible instance |
| OOB name longer than 30 UTF-16 units | Shorten all translations; narratives use different controls |
| Missing translation | Update the English source-string key |
| Flag/influence conflict | Nearby source belonging to the declared owner |
| Locked unit has permanent 0/0 AP | Positive capacity, `frozen_turns`, fresh campaign |
| Missing texture | Confined path, registered logical ID/token, readable PNG |
| Map cache mismatch | Matching new name in two YAML files; new output |
| Native hash/layout mismatch | Appropriate compatible adapter; retain report |
| Official generation failure | `build/editor-package-report.json` and stage `process.json` |
| Unexpected AI maneuver | Deployment ID, order/route/timing, unit state and controller policy |

Commit YAML, required original assets and attribution. Keep game archives, compiler caches, saves and bundles local. Read a failed attempt's report before discarding it.
