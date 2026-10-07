# 14. Validation, build, installation and distribution

[Recipe index](../RECIPES.md) · [Русская версия](14-build.ru.md) · [Workshop publication details](14-workshop.md)

## Basic procedure: check and build your edited campaign

From the repository root, with the installed environment and a source clone:

```powershell
$game = 'C:/Program Files (x86)/Steam/steamapps/common/WARNO'
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/my-check-01
./.venv/Scripts/python.exe -B scripts/campaign.py build campaigns/my-campaign --game $game --output artifacts/my-build-01
```

Replace the game path. Each output directory must be new: use suffix `02` for another attempt. Build also prepares/checks inputs, but a separate check gives faster feedback before official generation. Neither command installs or activates the mod.

When build succeeds, read `artifacts/my-build-01/build-result.json`. Its `package` contains:

| Field | Meaning |
| --- | --- |
| `candidate` | Complete assembled mod files |
| `bundle` | Verified immutable payload plus manifest |
| `config` | Compiled model/identity used with the bundle |

Keep bundle and compiled config from **the same build**. A failed folder without a successful final result is not an installable release.

## Basic procedure: install and play

Close WARNO first. Use result paths rather than hardcoding another campaign's bundle hash:

```powershell
$result = Get-Content artifacts/my-build-01/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
./.venv/Scripts/python.exe -B -m warno_ag full-install $result.package.bundle $result.package.config
./.venv/Scripts/python.exe -B -m warno_ag full-status $result.package.config
```

`full-install` installs **and activates**. There is no separate `full-activate` command in this CLI. Status should show installed, active, owned and integrity_verified as true.

Begin a new campaign and inspect the edited behavior. Saves retain previously serialized rosters, actions and state; changing YAML does not migrate them. Normally activate one framework campaign at a time, and do not activate the local and Workshop copies of the same campaign together.

## Update or remove your managed installation

After another successful build, load its new result and replace the complete owned installation:

```powershell
$result = Get-Content artifacts/my-build-02/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
./.venv/Scripts/python.exe -B -m warno_ag full-reinstall $result.package.bundle $result.package.config
./.venv/Scripts/python.exe -B -m warno_ag full-status $result.package.config
```

To remove that campaign from the local mod directory:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag full-uninstall $result.package.config
```

The installer works with its ownership/transaction records. Removal can retain the previous payload in a transaction directory for recovery; it is not a request to delete source, saves or every cache. Do not copy selected files over an installed mod or manually alter its ownership receipt.

## Helper commands and arguments

| Command | Required inputs | Result |
| --- | --- | --- |
| `scripts/campaign.py prepare` | `--game` | Prepare/check the compatible local game catalog and dictionaries |
| `clone` | source, new destination, `--id` | Independent campaign/profile/map identities |
| `catalog` | `--game`, new `--output` | units.csv, packs.csv, scenery.csv |
| `check` | source, `--game`, new `--output` | Compiled source model and prepared world/artwork inputs |
| `build` | source, `--game`, new `--output` | Official complete build and build-result.json |
| `-m warno_ag full-install` | bundle, config; optional `--mod-parent` | Install/activate complete owned mod |
| `full-reinstall` | bundle, config; optional `--mod-parent` | Replace the owned complete installation |
| `full-status` | config; optional `--mod-parent` | Ownership, activation and integrity status |
| `full-uninstall` | config; optional `--mod-parent` | Remove that owned local installation |

The source argument is a directory containing `campaign.yaml` and `profile.yaml`, not the YAML filename. `--game` names the folder containing WARNO.exe and official tools. Quote paths with spaces. `--mod-parent` is the parent local mod directory, not the individual campaign folder; when used, pass the same parent to install/status/reinstall/uninstall. Default is the current Windows user's Saved Games/EugenSystems/WARNO/mod.

`clone` needs a different 1–48-character lowercase identifier beginning with a letter, and a new destination outside the original source. It is unnecessary for a routine content update to the same independent campaign.

## What checking and building actually do

The helper prepares the selected game catalog, validates YAML references/rosters/translations, stages private images and prepares visible-world inputs. Checking does not run a campaign. Building additionally creates an isolated official compiler workspace, runs native map generation/baking where applicable, cooks resources and assembles a complete mod validated against its compiled model.

Reports and intermediate outputs remain under the chosen artifacts directory; compiler workspaces are under artifacts/compiler-workspaces. Do not publish these whole directories as a mod. A large raw source cache is not the same as the final payload size.

The native adapter is pinned to the supported 201602 layout and archive identities. A compatible installation needs WARNO.exe, Mods/ModData/base.zip, AssetCooker and the supplied tools. A hash/layout mismatch needs a matching adapter, not replacement of expected hashes to bypass checking.

Changed baked world source must use a new matching map_name in world and profile. A previously baked map with the same name and different source is rejected instead of silently reused. Changing output directory alone does not resolve a conflicting map identity.

## What to inspect in play

Start with the edited feature, then its dependencies: correct names/language, force counts and transport, normal AP recovery/locks, arrivals and deployment points, all decision alternatives, AI orders, ownership, aircraft lifecycle and deadline/endings. Try both sides where relevant. Cooperative presentation needs a separate multiplayer session; a successful single-player event is not its network acceptance.

Do not describe YAML validation, successful cooking or downloaded-byte equality as gameplay verification. They answer different questions. The check does not know whether a campaign is fun, historically plausible or balanced.

## Workshop staging

Prepare a separate publishable tree from the same verified build:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config artifacts/my-workshop-01 --preview campaigns/my-campaign/artwork/workshop-cover.jpg
```

Cover must be PNG/JPG/JPEG below 1,000,000 bytes. The export contains stage.json, preview and a mod tree, initially Workshop ID zero. Staging does not publish. The [detailed Workshop guide](14-workshop.md) covers private first upload, verified subscriber receipts and updates that preserve owner metadata.

For players, the finished campaign is a standalone mod: they subscribe/activate it in WARNO and do not need Python or a separate framework installation. Authors need their own item identity.

## Troubleshooting

| Error or symptom | Check |
| --- | --- |
| Output already exists | Read the old attempt's reports; choose a new path |
| Missing/extra/duplicate YAML key | Exact spelling, nesting and one mapping declaration |
| Unknown unit/pack/target | Correct catalog/category and declared ID |
| Duplicate battalion use | Independent definition for each possible appearance |
| Missing translation/long OOB text | Exact English key; resolved short-name limit in every locale |
| Flag/influence conflict | Nearest initial owner source |
| Missing texture | Relative file, logical ID, token and consumer |
| World cache mismatch | New matching map name in both source files |
| Native version/hash mismatch | Compatible game/adapter; retain the error |
| Official generation/cooking fails | build/editor-package-report.json and relevant stage process.json |
| Installation not owned or integrity changed | Correct build/config and original managed receipt; do not overlay files |
| Changes absent in play | Correct active full build and a fresh campaign |

Commit YAML, required source assets and attribution for a campaign source project. Keep generated game archives, caches, saves and installations separate. See [Getting started](../GETTING_STARTED.md) for environment setup and [the field reference](../YAML_REFERENCE.md) for exact schemas.
