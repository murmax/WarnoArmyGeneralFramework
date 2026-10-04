"""Prepare private SteamCMD VDFs for first publication or an item update.

This script never logs in, uploads, activates a mod or touches the game tree.
The author runs SteamCMD interactively, without putting credentials in AGF
commands or reports. The first publication reserves an ID before the complete
upload. Later updates require the verified subscriber receipt and reuse it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil

from warno_ag.campaign_identity import campaign_identity
from warno_ag.full_campaign import verify_full_bundle
from warno_ag.storage import sha256
from warno_ag.workshop import _workshop_config, verify_workshop_stage, verify_workshop_subscriber


APP_ID = 1611600
PRIVATE_VISIBILITY = 2
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


def _vdf_quote(value):
    value = str(value)
    if any(char in value for char in ('\x00', '\r', '\n')):
        raise ValueError('SteamCMD VDF values must be single-line strings')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _vdf(path, item_id, content, preview, title, description, note):
    if type(item_id) is not int or item_id < 0 or not isinstance(content, Path) or not content.is_dir():
        raise ValueError('Invalid private Workshop item preparation')
    if not preview.is_file() or preview.stat().st_size >= 1_000_000:
        raise ValueError('Private Workshop preview must exist and be smaller than 1 MB')
    values = {
        'appid': APP_ID, 'publishedfileid': item_id,
        'contentfolder': content.resolve().as_posix(),
        'previewfile': preview.resolve().as_posix(),
        'visibility': PRIVATE_VISIBILITY, 'title': title,
        'description': description, 'changenote': note,
    }
    body = '"workshopitem"\n{\n' + ''.join(
        f'    {_vdf_quote(key)} {_vdf_quote(value)}\n' for key, value in values.items()) + '}\n'
    path.write_text(body, encoding='utf-8', newline='\n')
    return {'vdf': str(path), 'appid': APP_ID, 'publishedfileid': item_id,
            'visibility': PRIVATE_VISIBILITY, 'contentfolder': str(content),
            'previewfile': str(preview), 'vdf_sha256': sha256(path.read_bytes())}


def _stage(stage, bundle, config, *, allow_published=False):
    stage = Path(stage).resolve()
    verified = verify_workshop_stage(stage, bundle, config)
    report = json.loads((stage / 'stage.json').read_text(encoding='utf-8'))
    if (report['workshop_id'] != verified['workshop_id'] or
            report['workshop_id'] != 0 and not allow_published):
        raise ValueError('First private publication requires an unpublished ID-zero stage')
    if not 0 < verified['bytes'] <= MAX_UPLOAD_BYTES:
        raise ValueError('Private Workshop payload exceeds the 512 MiB upload ceiling')
    previews = list((stage / 'preview').glob('*'))
    if len(previews) != 1 or not previews[0].is_file():
        raise ValueError('Private Workshop publication requires one prepared cover')
    return stage, report, verified, previews[0]


def _description(path):
    text = Path(path).read_text(encoding='utf-8')
    text = ' '.join(line.strip().lstrip('#- ') for line in text.splitlines() if line.strip())
    if not 20 <= len(text) <= 6000:
        raise ValueError('Private Workshop description is empty or too long')
    return text


def _assigned_id(create_vdf):
    text = Path(create_vdf).read_text(encoding='utf-8')
    values = re.findall(r'"publishedfileid"\s+"([0-9]+)"', text)
    visibility = re.findall(r'"visibility"\s+"([0-9]+)"', text)
    app_ids = re.findall(r'"appid"\s+"([0-9]+)"', text)
    if (len(values) != 1 or len(visibility) != 1 or len(app_ids) != 1
            or not 0 < int(values[0]) < (1 << 63)
            or int(visibility[0]) != PRIVATE_VISIBILITY or int(app_ids[0]) != APP_ID):
        raise ValueError('SteamCMD has not assigned a private WARNO Workshop item ID')
    return int(values[0])


def prepare_create(stage, bundle, config, description):
    stage, report, verified, preview = _stage(stage, bundle, config)
    folder = stage / 'steamcmd-private'
    placeholder = folder / 'placeholder'
    pending = 'Temporary private identity reservation; complete campaign follows.\n'
    if folder.exists():
        if ((folder / 'create.vdf').exists() or not placeholder.is_dir()
                or (placeholder / 'PRIVATE_PREVIEW.txt').read_text(encoding='utf-8') != pending
                or set(folder.iterdir()) != {placeholder}):
            raise FileExistsError('Private Workshop reservation already exists or differs')
    else:
        placeholder.mkdir(parents=True)
        (placeholder / 'PRIVATE_PREVIEW.txt').write_text(pending, encoding='utf-8')
    compiled = json.loads(Path(config).read_text(encoding='utf-8'))
    title = compiled['campaign']['title']['en'] + ' [Private Preview]'
    receipt = _vdf(folder / 'create.vdf', 0, placeholder, preview, title,
                   _description(description), 'Private identity reservation')
    receipt.update(source_bundle_id=verified['source_bundle_id'],
                   publisher_folder=report['publisher_folder'], steam_upload_performed=False)
    (folder / 'create-prepared.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                                  encoding='utf-8')
    return receipt


def prepare_full_update(stage, bundle, config, description):
    stage, report, verified, preview = _stage(stage, bundle, config)
    folder = stage / 'steamcmd-private'
    receipt = json.loads((folder / 'create-prepared.json').read_text(encoding='utf-8'))
    if receipt.get('source_bundle_id') != verified['source_bundle_id']:
        raise ValueError('Private item reservation belongs to another bundle')
    item_id = _assigned_id(folder / 'create.vdf')
    full = folder / 'complete-content'
    if full.exists():
        raise FileExistsError(full)
    source = stage / 'mod' / report['publisher_folder']
    shutil.copytree(source, full)
    manifest, files = verify_full_bundle(bundle, config)
    compiled = json.loads(Path(config).read_text(encoding='utf-8'))
    identity = campaign_identity(compiled)
    (full / 'Config.ini').write_bytes(_workshop_config(files['Config.ini'], identity, item_id, preview))
    actual = {path.relative_to(full).as_posix(): sha256(path.read_bytes())
              for path in full.rglob('*') if path.is_file()}
    upload_bytes = sum(path.stat().st_size for path in full.rglob('*') if path.is_file())
    if upload_bytes > MAX_UPLOAD_BYTES:
        raise ValueError('Private Workshop payload exceeds the 512 MiB upload ceiling')
    expected = dict(report['files'])
    expected['Config.ini'] = sha256((full / 'Config.ini').read_bytes())
    if actual != expected or manifest['bundle_id'] != verified['source_bundle_id']:
        raise ValueError('Private Workshop content changed a game resource')
    receipt = _vdf(folder / 'full.vdf', item_id, full, preview,
                   compiled['campaign']['title']['en'] + ' [Private Preview]', _description(description),
                   'Private complete campaign preview with AI-directed reserves')
    receipt.update(source_bundle_id=verified['source_bundle_id'],
                   publisher_folder=report['publisher_folder'], file_count=len(actual),
                   upload_bytes=upload_bytes,
                   steam_upload_performed=False)
    (folder / 'full-prepared.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n',
                                                encoding='utf-8')
    return receipt


def prepare_existing_update(stage, bundle, config, description, *, change_note='Private campaign update'):
    """Prepare a private update for a previously verified Steam item ID."""
    stage, report, verified, preview = _stage(stage, bundle, config, allow_published=True)
    item_id = verified['workshop_id']
    if item_id <= 0 or not (stage / 'previous-publication.json').is_file():
        raise ValueError('Existing Workshop update needs a verified previous item receipt')
    folder = stage / 'steamcmd-private'
    if folder.exists():
        raise FileExistsError(folder)
    source = stage / 'mod' / report['publisher_folder']
    full = folder / 'complete-content'
    shutil.copytree(source, full)
    manifest, files = verify_full_bundle(bundle, config)
    compiled = json.loads(Path(config).read_text(encoding='utf-8'))
    identity = campaign_identity(compiled)
    expected_config = _workshop_config(files['Config.ini'], identity, item_id, preview)
    if (full / 'Config.ini').read_bytes() != expected_config:
        raise ValueError('Workshop update Config.ini does not carry the verified item identity')
    actual = {path.relative_to(full).as_posix(): sha256(path.read_bytes())
              for path in full.rglob('*') if path.is_file()}
    expected = dict(report['files'])
    expected['Config.ini'] = sha256(expected_config)
    upload_bytes = sum(path.stat().st_size for path in full.rglob('*') if path.is_file())
    if (actual != expected or manifest['bundle_id'] != verified['source_bundle_id']
            or upload_bytes > MAX_UPLOAD_BYTES):
        raise ValueError('Private Workshop update differs from its verified complete bundle')
    receipt = _vdf(folder / 'full.vdf', item_id, full, preview,
                   compiled['campaign']['title']['en'] + ' [Private Preview]',
                   _description(description), change_note)
    receipt.update(source_bundle_id=verified['source_bundle_id'],
                   previous_publication_sha256=sha256((stage / 'previous-publication.json').read_bytes()),
                   publisher_folder=report['publisher_folder'], file_count=len(actual),
                   upload_bytes=upload_bytes, steam_upload_performed=False)
    (folder / 'full-prepared.json').write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return receipt


def capture_download(stage, bundle, config, downloaded):
    stage, report, verified, _ = _stage(stage, bundle, config, allow_published=True)
    folder = stage / 'steamcmd-private'
    item_id = _assigned_id(folder / 'full.vdf')
    downloaded = Path(downloaded).resolve()
    if (downloaded.parent.name != str(APP_ID) or downloaded.parent.parent.name != 'content'
            or downloaded.parent.parent.parent.name != 'workshop'):
        raise ValueError('Subscriber evidence must come from Steam workshop/content/1611600')
    subscriber = verify_workshop_subscriber(stage, bundle, config, downloaded)
    if (subscriber['workshop_id'] != item_id or
            verified['workshop_id'] not in (0, item_id)):
        raise ValueError('Downloaded Workshop item differs from SteamCMD publication ID')
    publication = {
        'format': 'agf-workshop-publication/v1',
        'campaign_id': report['source_campaign_id'],
        'source_bundle_id': verified['source_bundle_id'],
        'publisher_folder': report['publisher_folder'],
        'workshop_id': item_id,
        'visibility_requested': 'private',
        'subscriber_verified': True,
        'subscriber_report': subscriber,
        'gameplay_verified': False,
    }
    (stage / 'publication.json').write_text(json.dumps(publication, ensure_ascii=False, indent=2) + '\n',
                                            encoding='utf-8')
    return publication


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('prepare-create', 'prepare-full', 'prepare-update', 'capture-download'):
        action = sub.add_parser(command)
        for name in ('stage', 'bundle', 'config'):
            action.add_argument(name)
        action.add_argument('description_or_downloaded')
        if command == 'prepare-update':
            action.add_argument('--change-note', default='Private campaign update')
    args = parser.parse_args(argv)
    action = {'prepare-create': prepare_create, 'prepare-full': prepare_full_update,
              'prepare-update': prepare_existing_update, 'capture-download': capture_download}[args.command]
    options = {'change_note': args.change_note} if args.command == 'prepare-update' else {}
    print(json.dumps(action(args.stage, args.bundle, args.config,
                            args.description_or_downloaded, **options), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
