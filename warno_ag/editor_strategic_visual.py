"""Extract one verified strategic pawn preview without recapturing a map.

The output is an ignored editor cache bound to a source snapshot or installed game.
It is not a campaign build input and does not modify the installed game.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

from .editor_visuals import (COMMIT, EXTRACTOR_SHA256, UPSTREAM, VisualReader,
                             _copy_mesh_pack, _load_extractor, ensure_extractor)
from .game_resources import GameResources
from .native_campaign_source import verify_native_snapshot
from .storage import safe_child, sha256
from .visual_catalog import current_visual_catalog


COUNTRIES = frozenset({'US', 'RFA', 'SOV', 'DDR', 'UK', 'BEL', 'NL', 'POL',
                       'CAN', 'ESP', 'FR', 'TCH', 'CUB'})


def capture_strategic_visual(source, unit_id, country, destination, *, cache=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    if country == 'RDA':
        country = 'DDR'
    if country not in COUNTRIES:
        raise ValueError('Unsupported strategic pawn base country: ' + str(country))
    catalog = current_visual_catalog()
    visual = catalog.get(unit_id)
    if visual is None:
        raise ValueError('Unknown verified strategic visual unit: ' + str(unit_id))
    if visual['category'] not in {'infantry', 'vehicle', 'helicopter', 'airplane'}:
        raise ValueError('Unsupported strategic visual category: ' + visual['category'])
    game_only = not (source / 'native-source.json').is_file()
    if game_only:
        if not (source / 'Data').is_dir() or not (source / 'Mods').is_dir():
            raise ValueError('Expected a captured source snapshot or installed WARNO directory')
        game = GameResources(source)
        reader = VisualReader(None, game)
        manifest = {'scenario': 'BaseGame', 'game_root': str(source)}
    else:
        verify_native_snapshot(source)
        manifest = json.loads((source / 'native-source.json').read_text(encoding='utf-8'))
        game = GameResources(manifest['game_root'])
        reader = VisualReader(source, game)
    cache = Path(cache or Path(__file__).resolve().parents[1] / 'artifacts/editor-visual-cache')
    extractor = ensure_extractor(cache)
    shared = game.shared()
    pack = shared.require('MeshPack/Base.spk') if 'MeshPack/Base.spk' in shared.paths else shared.require('PC/Mesh/Pack/Base.spk')
    if game_only:
        provenance = {'depiction_resources': sha256(game.definitions().read('NDF/GFX/DepictionResources.ndfbin')),
                      'common_resources': sha256(game.definitions().read('NDF/GFX/DepictionCommonResources.ndfbin')),
                      'mesh_pack': pack.checksum, 'visual': visual['mesh']}
        manifest['projection_sha256'] = sha256(json.dumps(provenance, sort_keys=True).encode('utf-8'))
    spk_path = _copy_mesh_pack(pack, cache)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.single-visual-', dir=destination.parent) as temporary:
        staged = Path(temporary) / 'visual'
        staged.mkdir()
        models = {}
        issues = []
        with _load_extractor(extractor).SpkMeshExtractor(spk_path) as spk:
            def model(asset):
                if asset in models:
                    return models[asset]
                key = sha256(asset.encode('utf-8'))[:20]
                folder = staged / 'models' / key
                folder.mkdir(parents=True)
                result = subprocess.run([sys.executable, '-B', str(extractor), '--spk', str(spk_path),
                    '--asset', asset, '--out', str(folder), '--flat'], capture_output=True, text=True,
                    encoding='utf-8', errors='replace', timeout=180)
                if result.returncode:
                    raise ValueError('Single-visual SPK extraction failed: ' + result.stderr[-2000:])
                extracted = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
                if extracted['errors'] or len(extracted['items']) != 1:
                    raise ValueError('Single-visual mesh was not extracted: ' + asset)
                item = extracted['items'][0]
                materials = []
                for material in item['materials']:
                    names = spk.material_texture_names_by_id.get(material['id'], {})
                    texture_name = next((names[name] for name in
                        ('DiffuseTextureNoAlpha', 'DiffuseTexture', 'DiffuseTextureAlpha') if name in names), None)
                    row = {'name': material['name'], 'texture': None}
                    if texture_name is not None:
                        try:
                            image, origin = reader.material_texture(asset, texture_name)
                            texture_path = folder / (sha256(texture_name.encode('utf-8'))[:16] + '.png')
                            image.save(texture_path)
                            row.update(texture=texture_path.relative_to(staged).as_posix(), origin=origin)
                        except (ValueError, KeyError) as error:
                            # A verified mesh still gives a useful 3D preview
                            # when an ambiguous source atlas lacks one safe
                            # texture choice. Record the missing material.
                            issues.append({'asset': asset, 'material': material['name'],
                                           'error': str(error)})
                    materials.append(row)
                obj = Path(item['obj'])
                positions = [list(map(float, line.split()[1:4])) for line in
                    obj.read_text(encoding='utf-8').splitlines() if line.startswith('v ')]
                if not positions:
                    raise ValueError('Single-visual mesh is empty: ' + asset)
                anchors = dict(item['skeleton']['bone_positions'])
                meta = spk.fat[asset]
                if meta['nodeIndex'] != 0xffffffff:
                    names = spk.parse_node_names(meta['nodeIndex'])
                    positions_by_node = spk.parse_node_exact_world_positions(meta['nodeIndex'])
                    if positions_by_node is not None and len(names) == len(positions_by_node):
                        anchors.update({name.lower(): list(point) for name, point in zip(names, positions_by_node)})
                row = {'asset': asset, 'file': obj.relative_to(staged).as_posix(), 'materials': materials,
                       'anchors': anchors, 'bounds': [[min(p[i] for p in positions), max(p[i] for p in positions)] for i in range(3)]}
                models[asset] = row
                return row

            stand_asset = reader.mesh('$/GFX/DepictionResources/MeshModele_Socle_' + country)
            stem_asset = reader.mesh('$/GFX/DepictionResources/MeshModele_Tige_courte')
            body_asset = reader.mesh('$/GFX/DepictionResources/' + visual['mesh'])
            stand, stem, body = model(stand_asset), model(stem_asset), model(body_asset)
            tip = stem['anchors'].get('sommet')
            if tip is None or len(tip) != 3:
                raise ValueError('Strategic pawn stem has no verified top anchor')
            parts = [
                {'mesh': stand['file'], 'scale': 6, 'offset': [0, 0, 0]},
                {'mesh': stem['file'], 'scale': 6, 'offset': [0, 0, 0]},
                {'mesh': body['file'], 'scale': 6, 'offset': [float(v) * 6 for v in tip]},
            ]
        files = []
        for path in sorted(staged.rglob('*')):
            if path.is_file() and path.suffix in {'.obj', '.png'}:
                files.append({'file': path.relative_to(staged).as_posix(), 'sha256': sha256(path.read_bytes())})
        report = {'format': 'agf-editor-single-strategic-visual/v1',
                  'scenario': manifest['scenario'], 'source_projection_sha256': manifest['projection_sha256'],
                  'unit_id': unit_id, 'country': country, 'category': visual['category'],
                  'mesh': visual['mesh'], 'icon_token': visual['texture'], 'parts': parts,
                  'models': list(models.values()), 'files': files, 'issues': issues,
                  'extractor': {'upstream': UPSTREAM, 'commit': COMMIT, 'sha256': EXTRACTOR_SHA256},
                  'runtime_verified': False}
        (staged / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        verify_strategic_visual(staged, manifest['projection_sha256'], unit_id, country)
        staged.rename(destination)
    return report


def verify_strategic_visual(directory, expected_projection=None, expected_unit=None, expected_country=None):
    directory = Path(directory).resolve()
    report = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if report.get('format') != 'agf-editor-single-strategic-visual/v1':
        raise ValueError('Unsupported single strategic visual manifest')
    if expected_projection is not None and report['source_projection_sha256'] != expected_projection:
        raise ValueError('Strategic visual cache belongs to another source capture')
    if expected_unit is not None and report['unit_id'] != expected_unit:
        raise ValueError('Strategic visual unit id changed')
    if expected_country is not None and report['country'] != expected_country:
        raise ValueError('Strategic visual country changed')
    files = {row['file']: row['sha256'] for row in report['files']}
    if len(files) != len(report['files']) or not files:
        raise ValueError('Strategic visual cache has duplicate or no files')
    for name, digest in files.items():
        path = safe_child(directory, name)
        if not path.is_file() or sha256(path.read_bytes()) != digest:
            raise ValueError('Strategic visual cache file changed: ' + name)
    if len(report['parts']) != 3 or len(report['models']) != 3:
        raise ValueError('Strategic visual requires stand, stem and unit model')
    for part in report['parts']:
        if part['mesh'] not in files:
            raise ValueError('Strategic visual part has no verified mesh')
    for model in report['models']:
        if model['file'] not in files:
            raise ValueError('Strategic visual model has no verified mesh')
        for material in model['materials']:
            if material['texture'] is not None and material['texture'] not in files:
                raise ValueError('Strategic visual material has no verified texture')
    return report
