# Getting started with the framework

## Requirements

- Windows with WARNO installed for game compilation and play.
- Python 3.11 or newer for authoring. Use a project virtual environment, not
  the older Python bundled with WARNO's mod tools.
- WARNO's official ModGen/compiler tools, supplied with the installed game.
  The framework does not redistribute their files.

Run commands from the repository root. PowerShell examples use the Steam
default game path. The official compiler commands accept another game root,
but parts of the pinned Bruderkrieg compatibility adapter still read their
baseline archives from that default Steam path. A non-Steam authoring
installation has not passed the complete build path yet. Workshop players do
not need this authoring environment.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
$game = 'C:\Program Files (x86)\Steam\steamapps\common\WARNO'
.\.venv\Scripts\python.exe -B scripts/prepare_game_template.py $game
.\.venv\Scripts\python.exe -B scripts/bootstrap_authored_localisation.py artifacts/full-campaign-work/RedLine1989-v12
```

## Make and inspect campaign source

The current Crimea example has optional `campaign.yaml.menu` metadata:
localized `header`, `subtitle`, `description`, localized `side_forces.nato`
and `.pact`, `attacker` (`nato` or `pact`) and a campaign-relative `image` PNG.
This supplies independent native menu fields instead of inheriting the
template's map, role captions and force descriptions. Keep `campaign.summary`
brief for in-game UI. The original landscape image is preserved in source;
the compiler stages an aspect-preserving 400-pixel-wide menu texture and
verifies its pixels, declaration and native binding. Editor import/export
preserves the metadata and original image. The menu recipe is optional; use the published YAML examples to begin. A dedicated menu workbench is not included in this release.

Campaign source consists of public YAML documents for the campaign, map,
deployments, battalions, AI, events, aviation, production and reinforcements.
The preparation step above extracts the installed game's official ModGen
catalog into ignored `artifacts/` (about 141 MB) without launching WARNO.
The dictionary bootstrap writes only locally generated compatibility data.
Its source recipe records hash IDs and font character inventories, not WARNO
archives or narrative text. A complete V4U candidate built using this
bootstrap was compared with the historical corpus: all runtime resources and
223 of 224 payload files were byte-identical. The sole differing file was a
service JSON with identical parsed data and a different key order. The
bootstrap does not remove the requirement for a
matching installed WARNO version and an official compiler run.
Use the small YAML example to check the compiler:

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag campaign-compile campaigns/canvas-regression profiles/canvas-8x8.yaml artifacts/canvas-compiled
```

`campaign.compiled.json` is an intermediate authoring product, not a WARNO
mod. The example uses a tiny test map; replace it with an original source map
and campaign for a real release. The map authoring tools accept an author's
GeoTIFF height data, images and explicitly requested OSM data. Follow the
license and attribution terms of each geographic source. Do not bulk download
the public OSM tile server for offline map building.

## Build a complete campaign

The V9 example adds timed aviation lifecycle fields. `aviation.yaml.wings`
can specify `withdraw_turn` after a dated arrival, and
`initial_losses: {max_percent: 50}`. Losses use a bounded native ticket budget;
with heterogeneous rosters the percentage is a maximum, not an exact count.
The two homogeneous V9 aircraft rosters represent exactly half their planes.
Arrival fatigue remains in the battalion's `definition.initial_state`.
New builds attach a private tag to each withdrawing wing and rescan a native
circular detector on each remaining owner turn. Removal therefore resolves
the current actor instead of relying only on its original creation handle.
The detector filters both its unique tag and side; unrelated wings are excluded.

Ground-attack (`bomber`) wings may include native `Avion_AT` aircraft as well
as bombers. V10 uses MiG-27s for its strike option. Air group formations can
use a separate parent and the native `Texture_Division_Emblem_SOV_AirForce`.

New dynamic frozen deployments use lifecycle version 4: the native descriptor
retains its normal AP capacity and recovery. Only current AP are cleared before
the campaign kernel starts and on subsequent locked owner turns. The release
action restores current AP once; normal turn recovery continues afterward.
Older 0/0 descriptors in existing saves require a fresh campaign. No persistent
supply-malus effect is used.
`ai_policy.continuous_route: true` requires per-turn refresh and retains the
remaining attack waypoints in one native mission. `cooperate: true` allows
nearby formations to participate in attacks.

With refreshed continuous routes, `retain_route_progress: true` remembers
intermediate positions once secured by the army. Each operational group owns
one-shot capture latches; a later rear-area recapture does not reset its
advance. Final objectives remain live and can be recaptured. This records
secured positions, not a per-pawn movement log.
`aggressive_until: {nato: 9}` assigns the native `Agressif` battle-start profile
only to NATO attack missions on turns 1–9. On turn 10 they receive `Default`;
Soviet and defensive/support missions remain `Default`. The profiles are
mission-scoped, with no global attack/fatigue threshold changes. An aggressive
profile permits less favorable predicted outcomes; it does not guarantee that
the engine accepts every attack or commits every nearby battalion.

For maps with a different cell scale, do not copy stock GRU radii blindly.
With refreshed continuous missions you can specify all four native AP-cell
radii: `attack_radius_cells`, `transit_radius_cells`, `support_radius_cells`,
and `waypoint_radius_cells`. `transit_waypoints` lists non-flag intermediate
positions that should avoid opportunistic fights. Other assault waypoints
and frontline defenders use the attack radius; support/reserve orders use
the support radius. The legacy `attack_radius` remains the GRU fallback.
The compiler reads the installed LBU/GRU conversion and records its checksum.
Example: attack 1.5 cells, transit/support 0.5 cells, waypoint tolerance 0.8.
On Kacha's 13,000-GU native AP grid, stock values 2120/707 GRU were approximately
12/4 cells. They allowed inland routes to divert toward Sevastopol prematurely.

`victory.time_limit` accepts `draw`, `nato` or `pact`. The latter two are
scripted deadline outcomes when the configured final turn begins. V10 closes
at the start of turn 20: turns 15–19 provide its five-turn carrier-withdrawal
window. The legacy draw rule remains after the final playable turn.

`campaign.yaml.capture_deadline` declares `{flag, owner, before_turn, division}`.
Capture is strictly before the deadline and permanently blocks that production
division, including its human and AI paths. Groups cannot precede the cutoff;
the division must have authored AI production. Events can use
`trigger: {capture_deadline: blocked}` or a dated `not_blocked` result at/after
the cutoff. The companion Kacha campaign demonstrates this policy. These fields round-trip through
the editor, but dedicated editing controls are not part of this revision.

### Additional languages

RU/EN fields remain the primary source. To translate every campaign screen,
add optional `localization.yaml` next to `campaign.yaml`:

```yaml
schema: 1
source_language: en
translations:
  fr:
    "Locked for %1 turns": "Bloqué pendant %1 tours"
```

This fragment shows the format; a declared language needs a complete table.
Keys are exact English source strings. Supported additional table codes are
`fr`, `de`, `es`, `pl` and `zh` (Simplified Chinese); optional `en` entries
correct English display names without changing stable source identifiers.
Translate menu descriptions, objectives, events, choices, introduction/ending
slides, map labels and formation/company/platoon names. The compiler rejects
missing strings, changed `%1` placeholders and changed coalition tags.
Translations are written into native bootstrap and runtime dictionaries.
Voice scripts are separate and do not create recordings. Campaigns without
a catalog retain the earlier English fallback.

For an existing Workshop item, `scripts/workshop_content_update.py` updates
only content and preview through an already logged-in Steam client. It checks
the owner and records title, description, visibility and tags before and after.
It does not change those fields or accept credentials. Pass the installed
game's `steam_api64.dll`; do not redistribute that DLL with framework source.

`editor-public-package` prepares a fresh official compiler workspace and
verifies a complete, isolated bundle. It does not install or activate the
campaign:

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag editor-public-package <source-folder> <profile.yaml> $game artifacts/my-campaign-package --world-source <world-source-folder> --event-images <event-images-folder> --workspace-parent artifacts
```

Use the output paths printed by this command for the bundle and compiled
campaign. If the source has no custom world or event images, omit those
optional arguments. A complete bundle is necessary: copying selected files
over another mod can leave stale scenario and map resources.
`--workspace-parent artifacts` keeps the large ModGen compiler workspace on
the project drive. WARNO still writes its small official `Config.ini` receipt
under Saved Games. If a new strategic world is baked in the same command,
the separate world compiler may use a game-managed workspace.

## Prepare a self-contained Workshop mod

Export the verified bundle into a separate Workshop staging directory. The
first export uses item ID zero; an update uses the previous verified
`publication.json` receipt to keep the same item ID.

```powershell
.\.venv\Scripts\python.exe -B -m warno_ag workshop-export <bundle> <compiled-campaign.json> artifacts/my-workshop-stage --preview <cover.jpg>
.\.venv\Scripts\python.exe -B -m warno_ag workshop-verify artifacts/my-workshop-stage <bundle> <compiled-campaign.json>
```

The stage is not uploaded by these commands. For a private first upload,
`scripts/private_workshop_release.py` prepares SteamCMD VDFs with
`visibility=2`. Its `prepare-create` phase obtains a new item ID with a tiny
placeholder; `prepare-full` then stages the complete bundle with that same ID.
`scripts/Run-PrivateWorkshopUpload.ps1` checks the item ID, private visibility
and a 512 MiB size limit before invoking SteamCMD. Enter the Steam password
and Guard approval only in the local SteamCMD window. After uploading, use its
`download` phase and `capture-download` to compare the Steam-downloaded item
with the source bundle and record `publication.json` for later updates.

For a later private update, export a new complete bundle with
`workshop-export ... --publication-receipt <previous-publication.json>`.
Then run `scripts/private_workshop_release.py prepare-update STAGE BUNDLE
COMPILED_CONFIG DESCRIPTION --change-note "What changed"`. This creates a
single private `full.vdf` with the existing item ID. Run the PowerShell
uploader with `-Phase full`, download the item again and call
`capture-download` against the new stage. This never creates a second
Workshop item; the old receipt is checked before the update is prepared.

Workshop subscribers activate the finished mod in WARNO's Mod Center. A
campaign package is self-contained; a separate framework installation is not
needed on the player's computer. Multiple independent complete campaign mods
can overlap in WARNO's global resource dictionaries, so avoid simultaneous
activation unless that combination has been verified.

## Verification and boundaries

The public snapshot's smoke suite is:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Some checks are skipped without local game assets and integration fixtures;
report failures and skips separately. The complete internal gate covers
additional campaign and editor fixtures. Build reports, checksums, and Steam downloads
verify generated files; they cannot replace manual testing of movement, AI,
events, victory conditions and the 3D scene in WARNO.

Keep game-derived binaries, downloaded data, compiler workspaces, Steam
credentials and runtime reports outside Git. `artifacts/` is ignored. Do not
commit or redistribute files extracted from WARNO.
Complete bundles record a fingerprint of the exact framework source checkout.
Rebuild a campaign from this public checkout before publishing or updating
it; a private test bundle made by a different research checkout is not a
verified input for this repository's Workshop exporter.
