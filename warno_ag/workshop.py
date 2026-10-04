"""Prepare a verified, self-contained WARNO Workshop upload without publishing it.

The game's UploadMod tool assigns the real Steam item ID.  A local AGF bundle
uses a deliberately different numeric identity, so the two artifacts must
never be confused or installed over one another.
"""
from __future__ import annotations

import configparser
import json
from pathlib import Path
import re
import shutil

from .campaign_identity import campaign_identity
from .deployment import default_mod_parent, plain_path, read_tree
from .full_campaign import verify_full_bundle
from .native_toolchain import prepare_native_compiler_workspace
from .storage import sha256, safe_child
from .trial import framework_fingerprint


FORMAT = "agf-workshop-stage/v1"


def _properties(raw: bytes) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",), strict=True)
    parser.optionxform = str
    parser.read_string(raw.decode("utf-8-sig"))
    if set(parser.sections()) != {"Properties", "Config"}:
        raise ValueError("Unexpected Workshop Config.ini sections")
    return parser


def _workshop_config(raw: bytes, identity: dict, workshop_id: int,
                     preview: Path | None = None) -> bytes:
    if type(workshop_id) is not int or not 0 <= workshop_id < (1 << 63):
        raise ValueError("Invalid Workshop item ID")
    parser = _properties(raw)
    if (parser["Properties"].get("Name") != identity["display_name"]
            or parser["Properties"].get("ID") != str(identity["local_mod_id"])):
        raise ValueError("Source bundle is not the expected local campaign")
    text = raw.decode("utf-8-sig")
    text, count = re.subn(r"(?m)^ID\s*=.*$", f"ID = {workshop_id} ; Steam Workshop ID assigned by UploadMod", text)
    if count != 1:
        raise ValueError("Source bundle needs exactly one ID field")
    if preview is not None:
        text, count = re.subn(r"(?m)^PreviewImagePath\s*=.*$",
                              lambda _: "PreviewImagePath = " + str(preview), text)
        if count != 1:
            raise ValueError("Source bundle needs exactly one preview field")
    result = text.encode("utf-8")
    changed = _properties(result)
    original = _properties(raw)
    if (dict(changed["Config"]) != dict(original["Config"])
            or changed["Properties"].get("ID") != str(workshop_id)
            or changed["Properties"].get("Name") != identity["display_name"]):
        raise ValueError("Workshop Config.ini changed its game compatibility contract")
    return result


def export_workshop_stage(bundle, config_path, destination, *, preview=None,
                          publication_receipt=None):
    """Create an immutable candidate for the official uploader, without touching WARNO.

    The caller must pass a complete verified AGF bundle.  The output's ``mod``
    child is the tree to place under Saved Games/WARNO/mod for upload.  It has a
    separate folder name so it cannot overwrite the locally installed campaign.
    ``ID = 0`` is the official pre-publication state.  Updates reuse only an
    uploader-assigned ID from a verified earlier publication receipt.
    """
    manifest, files = verify_full_bundle(bundle, config_path)
    compiled = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if compiled.get("format") != "authored-campaign-v1":
        raise ValueError("Workshop export currently requires a public authored campaign")
    identity = campaign_identity(compiled)
    if identity.get("local_mod_id") is None:
        raise ValueError("Workshop export requires an isolated local campaign identity")
    destination = plain_path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    name = identity["mod_name"] + "_WorkshopBuild" + manifest['bundle_id'][:8].upper()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,100}", name):
        raise ValueError("Invalid Workshop staging name")
    preview_source = Path(preview).resolve() if preview is not None else None
    if preview_source is not None and (not preview_source.is_file()
                                       or preview_source.suffix.lower() not in {".png", ".jpg", ".jpeg"}):
        raise ValueError("Workshop preview must be a PNG or JPEG file")
    if preview_source is not None and preview_source.stat().st_size >= 1_000_000:
        raise ValueError('Steam Workshop preview must be smaller than 1 MB')
    if "Config.ini" not in files:
        raise ValueError("Complete bundle has no Config.ini")
    preview_target = destination / "preview" / preview_source.name if preview_source else None
    receipt_source = Path(publication_receipt).resolve() if publication_receipt is not None else None
    workshop_id = 0
    receipt_data = None
    if receipt_source is not None:
        receipt_data = json.loads(receipt_source.read_text(encoding='utf-8'))
        if (receipt_data.get('format') != 'agf-workshop-publication/v1'
                or receipt_data.get('campaign_id') != compiled['campaign']['id']
                or type(receipt_data.get('workshop_id')) is not int
                or not 0 < receipt_data['workshop_id'] < (1 << 63)
                or receipt_data.get('subscriber_verified') is not True):
            raise ValueError('Workshop update needs a verified prior publication receipt')
        workshop_id = receipt_data['workshop_id']
    transformed_config = _workshop_config(files["Config.ini"], identity, workshop_id, preview_target)
    report = {
        "format": FORMAT,
        "source_bundle_id": manifest["bundle_id"],
        "source_campaign_id": compiled["campaign"]["id"],
        "source_scenario": identity["scenario"],
        "source_local_mod_id": identity["local_mod_id"],
        "publisher_folder": name,
        "workshop_id": workshop_id,
        "files": {key: sha256(value) for key, value in files.items()},
        "staged_config_sha256": sha256(transformed_config),
        "preview_sha256": sha256(preview_source.read_bytes()) if preview_source else None,
        "publication_receipt_sha256": sha256(receipt_source.read_bytes()) if receipt_source else None,
        "runtime_verified": False,
        "workshop_verified": False,
    }
    payload = destination / "mod" / name
    for relative, data in files.items():
        target = safe_child(payload, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(transformed_config if relative == "Config.ini" else data)
    if preview_target is not None:
        preview_target.parent.mkdir(parents=True, exist_ok=True)
        preview_target.write_bytes(preview_source.read_bytes())
    if receipt_source is not None:
        (destination / 'previous-publication.json').write_bytes(receipt_source.read_bytes())
    (destination / "stage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                              encoding="utf-8")
    verify_workshop_stage(destination, bundle, config_path)
    return report


def verify_workshop_stage(destination, bundle, config_path):
    """Prove that a stage differs from a verified bundle only in Config identity."""
    manifest, source_files = verify_full_bundle(bundle, config_path)
    compiled = json.loads(Path(config_path).read_text(encoding="utf-8"))
    identity = campaign_identity(compiled)
    root = plain_path(destination)
    report = json.loads((root / "stage.json").read_text(encoding="utf-8"))
    if (report.get("format") != FORMAT or report.get("source_bundle_id") != manifest["bundle_id"]
            or report.get("source_campaign_id") != compiled["campaign"]["id"]
            or report.get("source_scenario") != identity["scenario"]
            or report.get("source_local_mod_id") != identity["local_mod_id"]
            or type(report.get("workshop_id")) is not int
            or not 0 <= report['workshop_id'] < (1 << 63)):
        raise ValueError("Workshop stage identity or source bundle mismatch")
    name = report["publisher_folder"]
    if name != identity["mod_name"] + "_WorkshopBuild" + manifest['bundle_id'][:8].upper():
        raise ValueError("Workshop publisher folder mismatch")
    if report['workshop_id']:
        receipt = root / 'previous-publication.json'
        if not receipt.is_file() or sha256(receipt.read_bytes()) != report['publication_receipt_sha256']:
            raise ValueError('Workshop update lost its verified prior publication')
        previous = json.loads(receipt.read_text(encoding='utf-8'))
        if (previous.get('format') != 'agf-workshop-publication/v1'
                or previous.get('campaign_id') != compiled['campaign']['id']
                or previous.get('workshop_id') != report['workshop_id']
                or previous.get('subscriber_verified') is not True):
            raise ValueError('Workshop update publication receipt differs')
    elif report['publication_receipt_sha256'] is not None:
        raise ValueError('Unpublished Workshop stage has a prior publication receipt')
    payload = root / "mod" / name
    if not payload.is_dir():
        raise ValueError("Workshop payload folder is missing")
    staged_files = read_tree(payload)
    if set(staged_files) != set(source_files) or report["files"] != {
            key: sha256(value) for key, value in source_files.items()}:
        raise ValueError("Workshop stage inventory differs from its verified source")
    for relative, data in source_files.items():
        if relative != "Config.ini" and staged_files[relative] != data:
            raise ValueError("Workshop stage changed a compiled game resource: " + relative)
    preview_path = None
    if report["preview_sha256"] is not None:
        previews = list((root / "preview").glob("*"))
        if len(previews) != 1 or sha256(previews[0].read_bytes()) != report["preview_sha256"]:
            raise ValueError("Workshop preview changed")
        preview_path = previews[0]
    expected_config = _workshop_config(source_files["Config.ini"], identity,
                                       report['workshop_id'], preview_path)
    if (staged_files["Config.ini"] != expected_config
            or sha256(expected_config) != report["staged_config_sha256"]):
        raise ValueError("Workshop stage Config.ini differs from the unpublished identity")
    return {"source_bundle_id": manifest["bundle_id"], "publisher_folder": name,
            "file_count": len(staged_files), "bytes": sum(map(len, staged_files.values())),
            "workshop_id": report['workshop_id'], "verified": True}


def plan_official_upload(stage, bundle, config_path, game_root, *, mod_parent=None,
                         allow_existing=False):
    """Read-only preflight for the game's dedicated uploader workspace."""
    evidence = verify_workshop_stage(stage, bundle, config_path)
    source_manifest = json.loads((Path(bundle) / 'bundle.json').read_text(encoding='utf-8'))
    if source_manifest['framework_sha256'] != framework_fingerprint():
        raise ValueError('Framework changed since this Workshop bundle was built')
    game = plain_path(game_root)
    mod_root = plain_path(mod_parent if mod_parent is not None else default_mod_parent())
    if mod_root.name.casefold() != 'mod' or mod_root == Path(mod_root.anchor):
        raise ValueError('Workshop staging requires a dedicated WARNO mod parent')
    template = game / 'Mods' / 'ModData'
    for item in (game / 'WARNO.exe', template / 'base.zip', template / 'UploadMod.bat'):
        if not item.is_file():
            raise FileNotFoundError('Official WARNO uploader input is missing: ' + str(item))
    name = evidence['publisher_folder']
    workspace = (game / 'Mods' / name).resolve()
    generated = (mod_root / name).resolve()
    if workspace.parent != (game / 'Mods').resolve() or generated.parent != mod_root:
        raise ValueError('Workshop destination escaped its dedicated parent')
    exists = workspace.exists() or generated.exists()
    if exists and (not allow_existing or not workspace.is_dir() or not generated.is_dir()):
        raise FileExistsError('Workshop publisher workspace already exists or is incomplete')
    return {'format': 'agf-workshop-upload-plan/v1', 'publisher_folder': name,
            'source_bundle_id': evidence['source_bundle_id'], 'game_root': str(game),
            'compiler_workspace': str(workspace), 'generated_mod': str(generated),
            'file_count': evidence['file_count'], 'bytes': evidence['bytes'],
            'already_staged': exists, 'writes_performed': False, 'steam_upload_performed': False}


def prepare_official_upload(stage, bundle, config_path, game_root, *, mod_parent=None):
    """Stage the complete mod under a fresh official uploader name; no Steam call."""
    plan = plan_official_upload(stage, bundle, config_path, game_root,
                                mod_parent=mod_parent, allow_existing=True)
    workspace = Path(plan['compiler_workspace'])
    generated = Path(plan['generated_mod'])
    source = plain_path(stage) / 'mod' / plan['publisher_folder']
    if plan['already_staged']:
        marker = workspace / 'agf-compiler-workspace.json'
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('workspace') != str(workspace):
            raise ValueError('Existing Workshop workspace is not an owned official compiler workspace')
    else:
        prepare_native_compiler_workspace(plan['game_root'], plan['publisher_folder'])
        generated.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, generated)
    original = {name: sha256(raw) for name, raw in read_tree(source).items()}
    copied = {name: sha256(raw) for name, raw in read_tree(generated).items()}
    if copied != original:
        raise ValueError('Official Workshop upload staging differs from verified source')
    upload_template = Path(plan['game_root']) / 'Mods' / 'ModData' / 'UploadMod.bat'
    upload_batch = workspace / 'UploadMod.bat'
    if not upload_batch.exists():
        shutil.copyfile(upload_template, upload_batch)
    if sha256(upload_batch.read_bytes()) != sha256(upload_template.read_bytes()):
        raise ValueError('Official Workshop upload batch differs from WARNO template')
    result = {**plan, 'writes_performed': True,
              'official_workspace_ready': True, 'copied_payload_verified': True}
    (plain_path(stage) / 'upload-prepared.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def verify_workshop_subscriber(stage, bundle, config_path, item_directory):
    """Verify the Steam-downloaded copy, not the author's local generated mod."""
    source = verify_workshop_stage(stage, bundle, config_path)
    item = plain_path(item_directory)
    if not item.is_dir() or not item.name.isdecimal() or int(item.name) <= 0:
        raise ValueError('Expected a downloaded Workshop item ID directory')
    report = json.loads((plain_path(stage) / 'stage.json').read_text(encoding='utf-8'))
    publisher = plain_path(stage) / 'mod' / source['publisher_folder']
    runtime_roots = {'Gen', 'DatasMap', 'Maps', 'Scenarios', 'DecorsSets'}
    expected = {relative: sha256(raw) for relative, raw in read_tree(publisher).items()
                if relative.split('/', 1)[0] in runtime_roots}
    actual = {relative: sha256(raw) for relative, raw in read_tree(item).items()
              if relative.split('/', 1)[0] in runtime_roots}
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(key for key in set(actual) & set(expected) if actual[key] != expected[key])
        raise ValueError(f'Workshop subscriber runtime differs: missing={missing[:5]}, '
                         f'extra={extra[:5]}, changed={changed[:5]}')
    source_config = _properties((publisher / 'Config.ini').read_bytes())
    subscriber_config = _properties((item / 'Config.ini').read_bytes())
    properties = subscriber_config['Properties']
    if (properties.get('ID') != item.name or properties.get('Name') != source_config['Properties'].get('Name')
            or properties.get('DeckFormatVersion') != source_config['Properties'].get('DeckFormatVersion')
            or properties.get('ModGenVersion') != source_config['Properties'].get('ModGenVersion')
            or properties.get('CosmeticOnly') != source_config['Properties'].get('CosmeticOnly')
            or dict(subscriber_config['Config']) != dict(source_config['Config'])):
        raise ValueError('Workshop subscriber ID or compatibility settings differ')
    return {'format': 'agf-workshop-subscriber-verification/v1',
            'source_bundle_id': report['source_bundle_id'], 'campaign_id': report['source_campaign_id'],
            'workshop_id': int(item.name), 'runtime_files': len(expected),
            'runtime_bytes': sum((item / name).stat().st_size for name in expected),
            'runtime_files_identical': True, 'config_matches_steam_id': True,
            'gameplay_verified': False}


def capture_official_upload(stage, bundle, config_path, *, item_directory=None):
    """Record the item ID assigned by WARNO's uploader after its own upload step."""
    expected = verify_workshop_stage(stage, bundle, config_path)
    root = plain_path(stage)
    prepared = json.loads((root / 'upload-prepared.json').read_text(encoding='utf-8'))
    if (prepared.get('format') != 'agf-workshop-upload-plan/v1'
            or prepared.get('source_bundle_id') != expected['source_bundle_id']
            or prepared.get('publisher_folder') != expected['publisher_folder']
            or prepared.get('writes_performed') is not True):
        raise ValueError('Official upload preparation receipt does not match this stage')
    generated = plain_path(prepared['generated_mod'])
    stage_config = _properties((root / 'mod' / expected['publisher_folder'] / 'Config.ini').read_bytes())
    published_config = _properties((generated / 'Config.ini').read_bytes())
    value = published_config['Properties'].get('ID', '')
    if not value.isdecimal() or int(value) <= 0 or int(value) >= (1 << 63):
        raise ValueError('Official uploader has not assigned a Steam Workshop ID')
    if (published_config['Properties'].get('Name') != stage_config['Properties'].get('Name')
            or published_config['Properties'].get('ModGenVersion') != stage_config['Properties'].get('ModGenVersion')
            or dict(published_config['Config']) != dict(stage_config['Config'])):
        raise ValueError('Official uploader changed the campaign compatibility contract')
    report = {'format': 'agf-workshop-publication/v1',
              'source_bundle_id': expected['source_bundle_id'],
              'campaign_id': json.loads((root / 'stage.json').read_text(encoding='utf-8'))['source_campaign_id'],
              'publisher_folder': expected['publisher_folder'], 'workshop_id': int(value),
              'official_config_sha256': sha256((generated / 'Config.ini').read_bytes()),
              'subscriber_verified': False, 'gameplay_verified': False}
    if item_directory is not None:
        subscriber = verify_workshop_subscriber(stage, bundle, config_path, item_directory)
        if subscriber['workshop_id'] != int(value):
            raise ValueError('Downloaded Workshop item differs from the uploader-assigned ID')
        report['subscriber_verified'] = True
        report['subscriber_report'] = subscriber
    (root / 'publication.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8')
    return report
