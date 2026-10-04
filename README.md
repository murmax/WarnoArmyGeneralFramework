# WARNO Army General Framework

Create original **Army General campaigns for WARNO**: choose the battlefield, build battalions, place forces, schedule reinforcements, write events and define victory conditions. The framework compiles campaign source into a complete native WARNO mod for Steam Workshop.

**Release 1.0.3 · Windows · Python 3.11+ · MIT**

[Русская инструкция](docs/GETTING_STARTED_RU.md) · [Authoring guide](docs/GETTING_STARTED.md) · [Kacha example campaign](https://steamcommunity.com/sharedfiles/filedetails/?id=3811284575)

## I want to play a campaign

You do **not** need this repository, Python, a loader or a separate framework mod. Each campaign is packaged with its required framework output.

1. Subscribe to the campaign in Steam Workshop and let Steam finish downloading.
2. Enable that campaign in WARNO's mod menu and apply the game's requested restart.
3. Open Army General and start a **new campaign**.

Activate one framework-built campaign at a time unless that exact combination has been tested. Independent campaign mods can replace the same global resource paths. Updates do not migrate existing saves.

The example is **Kacha: Defense of Sevastopol**, an alternative-1989 campaign: US Marines try to seize Sevastopol, while Soviet naval infantry and arriving reserves defend the city. It demonstrates original terrain, combined forces, timed reinforcements, illustrated choices, aviation and conditional endings. The Workshop item may remain private until its author enables public visibility.

## I want to create a campaign

Version 1.0.1 corrects frozen battalion action-point capacity and adds optional
complete campaign translation catalogs. Kacha V11 includes Russian, English,
French, German, Spanish, Simplified Chinese and Polish. Start a fresh campaign
after updating: the framework does not rewrite action-point modules in saves.

This repository is an **authoring toolchain**. Campaigns are editable YAML documents; the included small example is a useful starting point. A playable build requires a compatible WARNO installation and its official mod tools.

### Requirements

- Windows and a local WARNO installation containing `WARNO.exe` and `Mods/ModData/base.zip`.
- Python **3.11 or newer**. Do not use the older Python bundled with WARNO.
- Space for an extracted official catalog and temporary compiler output. Keep `artifacts/` on a drive with room; it is build output, not source for Git.

The compatibility adapter is pinned to the **ModGen 201602** resource layout. Game updates can invalidate hashes or native layouts; investigate a failed compatibility check before building or installing a mod. Complete authoring is currently verified against the default Steam installation path. The compiler accepts an explicit game root, but some baseline readers still use that Steam path; other layouts need further adaptation.

### 1. Get the tools

```powershell
git clone https://github.com/murmax/WarnoArmyGeneralFramework.git
cd WarnoArmyGeneralFramework
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Run the commands below from the repository root. Players subscribing to a finished mod do not need the authoring environment.

### 2. Prepare your installed game's catalog

```powershell
$game = 'C:\Program Files (x86)\Steam\steamapps\common\WARNO'
.\.venv\Scripts\python.exe -B scripts/prepare_game_template.py $game
.\.venv\Scripts\python.exe -B scripts/bootstrap_authored_localisation.py artifacts/full-campaign-work/RedLine1989-v12
```

The first command extracts the installed game's official ModGen catalog into ignored `artifacts/` — approximately 141 MB. The second generates small local compatibility dictionaries. Neither launches WARNO or installs a mod. The commands expect new destination folders and refuse to overwrite prepared data.

### 3. Compile the example

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag campaign-compile campaigns/canvas-regression profiles/canvas-8x8.yaml artifacts/canvas-compiled
```

This validates YAML and writes a compiled model and report. It is **not** yet a playable mod. Copy the example to a new source folder and give your campaign its own ID before developing a release.

### 4. Build a complete mod

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag editor-public-package campaigns/red-line-demo profiles/bruderkrieg-map.yaml $game artifacts/demo-package --workspace-parent artifacts
```

The first full-build example uses the included `red-line-demo` on the installed Bruderkrieg geography. The small canvas example above validates a new-map layout and needs an authored world to become playable. This prepares an isolated official workspace, runs the official compiler in headless mode, cooks assets and verifies a complete bundle. It does not install or activate the bundle. For a new geographic world and custom event pictures, pass prepared `--world-source` and `--event-images` inputs described in the [authoring guide](docs/GETTING_STARTED.md).

Use the **bundle and config paths printed by the build** for installation:

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag full-install <bundle-folder> <campaign.compiled.json>
.\.venv\Scripts\python.exe -B -m warno_ag full-activate <campaign.compiled.json>
.\.venv\Scripts\python.exe -B -m warno_ag full-status <campaign.compiled.json>
```

Close WARNO before deployment. For an existing managed installation, use `full-reinstall` with the complete new bundle. Do not copy selected files over an old campaign: stale resources can produce misleading errors. The installer records ownership and checks file hashes; backups and logs remain separate from the playable mod.

## What campaigns can contain

| Area | Authoring capabilities |
| --- | --- |
| Strategic map | Playable area, terrain cells, movement data, geographic input, labels, objectives and scenery |
| Forces | Companies/platoons, counts, transports, experience, command/support, formations and emblems |
| Campaign flow | Starting forces, turn locks, grouped reinforcements and control-dependent deployment |
| Events | Localized text, illustrated choices, spawning, losses, AP changes and score effects |
| Aviation/support | Airfields, timed/selected wings, damaged arrivals, withdrawal, artillery and deployable AA |
| AI | Attack/defense routes, individual reinforcement orders, phases and cooperative attacks |
| Presentation | RU/EN text, menu metadata, four introduction slides per side and conditional endings |
| Distribution | Verified native bundles and self-contained Workshop staging |

The goal is ordinary original campaigns. Tutorial-menu integration and tutorial-specific action restrictions or UI highlighting are outside the scope.

## Repository contents

- `warno_ag/` — compiler, native adapters, map/asset tools and bundle verification.
- `campaigns/canvas-regression/` — a compact new-map YAML validation example.
- `campaigns/red-line-demo/` — an authored example using installed Bruderkrieg geography.
- `profiles/` — map adapters and compatibility recipes.
- `scripts/` — preparation and private Workshop-upload helpers.
- `tests/` — public checks and clearly marked optional local integration checks.
- `docs/` — setup, authoring, deployment and release notes.

The WPF editor is a separate component, undergoing manual UX acceptance before its source release. It is **not included** here. The YAML/CLI workflow works without it; this repository contains its Python back end, not a downloadable editor app.

## Publishing and verification

See [Workshop distribution](docs/GETTING_STARTED.md#prepare-a-self-contained-workshop-mod) for staging a verified bundle. Private-upload helpers check item identity and size. Enter passwords and Steam Guard only in your local SteamCMD window; do not put credentials in YAML or source control.

Static checks verify structure, references and packaged data. They do not prove AI behavior, balance or every event path in play. Playtest both sides of a **fresh campaign**, including reinforcement windows and endings, before release.

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Some integration checks require local game fixtures and report a skip when those fixtures are absent. A skip is not a passed integration test. The internal development checkout has a larger acceptance suite and runtime evidence.

## License and attribution

Original framework code is licensed under [MIT](LICENSE). WARNO resources are not included and retain their owners' rights. Geographic data and artwork have their own licenses and attribution requirements. A campaign may contain game-derived resources produced locally by the official mod tools; this source repository does not redistribute those files.

This is an independent community project, not an Eugen Systems product. For a reproducible problem report, include the WARNO/ModGen version, command, compiler report and a small source example. Never include passwords, Steam Guard codes or private credentials.
