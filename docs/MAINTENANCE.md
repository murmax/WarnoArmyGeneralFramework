# Maintenance and distribution boundaries

The author guides are the supported YAML workflow. Lower-level commands in `python -m warno_ag --help` also include developer/import tools; they are not additional campaign examples.

## Source and generated data

Track Python implementation, compatibility recipes, public YAML, required original artwork and licenses. Ignore `artifacts/`, `.venv/`, generated binaries, saved games and compiler workspaces. Compatibility recipes in `warno_ag/data/` preserve inspected adapter anchors and dictionary keys; they are not another playable campaign and should not be edited to bypass hash checks.

Full build output is bounded by the selected map/asset inputs and game toolchain, not by Git source size. Use a new output folder for each attempt. Retain a failed attempt's reports before cleanup. A world edited under the same native map name is rejected when its local bake does not match source; choose a new matching map name in both YAML files.

## Published campaign updates

Use a complete verified bundle and a prior verified publication receipt. `workshop-export --publication-receipt <publication.json>` reuses only that campaign's Workshop identity. Independent authors need their own item identity; Kacha's receipt is not included in this repository.

For an already owned item, the desktop-Steam updater requires a running authenticated Steam session:

```powershell
./.venv/Scripts/python.exe -B scripts/workshop_content_update.py --help
```

Supply the installed `steam_api64.dll`, your item number, complete staged content, cover below 1 MB and a new output receipt path. It changes content/cover only and verifies preservation of author-managed title, description, visibility and tags. It does not create a new item or log in for you.

For a first private item, inspect the bundled helper's explicit phases:

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py --help
```

The private flow prepares a small identity reservation, waits for the uploader-assigned ID, then uploads complete content and verifies a subscriber download. `Run-PrivateWorkshopUpload.ps1` launches the corresponding local SteamCMD interaction. Enter credentials in local prompts only. The ordinary game uploader does not provide the same private-first reservation contract.

Player installation is subscription/activation of a standalone campaign. No separate framework mod, loader or source runtime is required by the subscriber.

## Evidence and compatibility

The adapter is pinned to native layouts/hashes. Separate claims about YAML checking, native graph readback, official cooking, downloaded file equality and actual play. A compiler pass is not an AI/balance/cooperative test. Report optional integration checks that lack local game fixtures as skipped, not as successful gameplay.

The graphical editor is a separate deliverable. Its Python back-end modules support import/export/build, but this source release does not include a WPF editor installer or claim completed manual editor acceptance.
