# Workshop publication and updates

[Build/install workflow](14-build.md) · [Русская версия](14-workshop.ru.md) · [Recipe index](../RECIPES.md)

## Prepare a verified publishable tree

First complete [the build](14-build.md) and load its result. This step does not publish:

```powershell
$result = Get-Content artifacts/my-build-01/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$stage = 'artifacts/my-workshop-01'
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config $stage --preview campaigns/my-campaign/artwork/workshop-cover.jpg
./.venv/Scripts/python.exe -B -m warno_ag workshop-verify $stage $result.package.bundle $result.package.config
```

The destination must be new. Cover is a local PNG/JPG/JPEG below 1,000,000 bytes. The content tree is inside stage/mod; upload that complete tree, not the repository, source campaign or all artifacts. The initial Config.ini has Workshop ID 0 because Steam has not assigned an item yet.

## First private upload: supported two-phase flow

This optional publication flow requires the author's Steam account and Valve [SteamCMD](https://developer.valvesoftware.com/wiki/SteamCMD). Place the extracted steamcmd.exe in `artifacts/steamcmd/` for the bundled runner. You need permission to publish for WARNO and may need to accept the Workshop agreement.

Create a UTF-8 `workshop-description.txt` with your mod description. The helper flattens nonempty lines into a single-line description; the result must be 20–6000 characters. Its private title is the English campaign title with `[Private Preview]`. This is a private staging presentation; edit richer public text in Steam when you choose to publish openly.

### 1. Reserve a private identity

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py prepare-create $stage $result.package.bundle $result.package.config workshop-description.txt
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase create
```

The preparation creates `steamcmd-private/create.vdf` with visibility 2 (private) and a small placeholder. The runner asks for the Steam login locally; enter password/Guard only in the local SteamCMD prompts, not command arguments or files.

Wait for successful Steam completion. `create.vdf` must now contain its assigned nonzero `publishedfileid`. Do not substitute another author's ID. A timeout or failed login is not a completed reservation; inspect the SteamCMD output/log before retrying. Do not start several create uploads concurrently.

### 2. Prepare and upload complete content

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py prepare-full $stage $result.package.bundle $result.package.config workshop-description.txt
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase full
```

The helper copies the complete verified payload into `steamcmd-private/complete-content`, inserts the assigned item ID into its Config.ini and writes `full.vdf` requesting private visibility. Wait for Steam's success and confirm the item's actual visibility in Workshop.

The preparation is bound to the same source bundle as its reservation. If a full-content preparation already exists, read its receipt before attempting another operation; it is not silently overwritten.

### 3. Verify the owner download and retain its receipt

```powershell
./scripts/Run-PrivateWorkshopUpload.ps1 -Stage $stage -Phase download
```

Find the assigned numeric ID in full.vdf and the actual download folder under SteamCMD's `steamapps/workshop/content/1611600/<ID>`. Then:

```powershell
./.venv/Scripts/python.exe -B scripts/private_workshop_release.py capture-download $stage $result.package.bundle $result.package.config artifacts/steamcmd/steamapps/workshop/content/1611600/YOUR_ITEM_ID
```

Replace the final path with the existing download path. This compares the received mod with the verified stage and writes stage/publication.json. Retain it for subsequent updates. The receipt records private visibility requested and byte/identity verification; inspect actual Steam visibility separately. Download equality does not establish campaign gameplay quality.

A private item is not generally available to volunteers on unrelated accounts. Arrange Steam visibility/access deliberately before recruiting testers; publication code does not grant their access automatically. Start a new campaign with the same build on all participants.

## Update an existing item without changing its description

Create a new complete build and stage using **your verified prior publication receipt**:

```powershell
$result = Get-Content artifacts/my-build-02/build-result.json -Raw -Encoding UTF8 | ConvertFrom-Json
$stage = 'artifacts/my-workshop-02'
./.venv/Scripts/python.exe -B -m warno_ag workshop-export $result.package.bundle $result.package.config $stage --preview campaigns/my-campaign/artwork/workshop-cover.jpg --publication-receipt artifacts/my-workshop-01/publication.json
```

The receipt must identify this campaign, an assigned positive item ID and verified subscriber content. The new stage now contains your existing item identity. To use the authenticated running desktop Steam client:

```powershell
$metadata = Get-Content "$stage/stage.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$content = Join-Path "$stage/mod" $metadata.publisher_folder
$preview = Get-ChildItem "$stage/preview" -File | Select-Object -First 1
./.venv/Scripts/python.exe -B scripts/workshop_content_update.py --dll "$game/steam_api64.dll" --item $metadata.workshop_id --content $content --preview $preview.FullName --note 'Campaign content update' --output artifacts/workshop-update-02.json
```

Steam must already be logged in as the owner. This updater submits content/cover only, checks ownership and verifies preservation of title, description, tags and visibility. It does not create an item or handle login. Private SteamCMD `prepare-update` is another flow, but it explicitly supplies private title/description/visibility; it is not the metadata-preserving choice.

## Arguments and limits

| Tool | Inputs and behavior |
| --- | --- |
| workshop-export | bundle, config, new destination; optional preview and verified publication-receipt |
| workshop-verify | stage, bundle, config; offline stage/resource equality |
| private helper prepare-create/prepare-full | stage, same bundle/config, UTF-8 description path |
| private helper prepare-update | existing-item stage, bundle/config, description; optional change-note |
| private helper capture-download | stage, bundle/config, actual workshop/content/1611600 item directory |
| Runner Stage | Prepared private stage path |
| Runner Phase | create, full or download |
| Runner SteamLogin | Optional login name; otherwise asks locally; never a password |
| Desktop updater dll | Installed compatible steam_api64.dll path |
| Desktop updater item | Existing item number owned by authenticated Steam user |
| Desktop updater output | New receipt file |
| Desktop updater content/preview | Supply both for update; omit both for read-only item query |
| Desktop updater note | Change note; default Campaign content update |

Private preparation and the desktop updater impose a 512 MiB content ceiling. The runner also rejects a suspiciously small full payload (fewer than 200 files), a placeholder other than one small file, invalid phase IDs, nonprivate VDFs or mismatched stage paths. Report a legitimate payload outside these supported assumptions rather than padding it with unrelated files. A small cover does not reduce mod content size.

## Alternative official uploader tools

The CLI also offers workshop-plan-upload / workshop-prepare-upload (stage, bundle, config, game_root, optional mod-parent), workshop-verify-subscriber (plus item directory), and workshop-capture-upload (optional item-directory). They prepare/record the game's own uploader path. That is a separate flow from private reservation; do not assume it inherits the private VDF contract.

Use one publication flow and its corresponding receipts consistently. Do not change a local campaign's deliberately different mod identity to a guessed Steam item ID. Update subscriptions only from complete verified payloads, and keep source, local installed mod and Workshop staging trees distinct.
