"""Fast offline checks for the private two-phase SteamCMD publisher."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.private_workshop_release import (_assigned_id, _vdf, _stage,
                                              MAX_UPLOAD_BYTES, prepare_full_update,
                                              prepare_existing_update, capture_download)
from warno_ag.storage import sha256
from warno_ag.workshop import _workshop_config


ROOT = Path(__file__).resolve().parents[1]


class PrivateWorkshopReleaseTests(unittest.TestCase):
    def test_oversized_bundle_is_rejected_before_any_steam_step(self):
        with tempfile.TemporaryDirectory(prefix='agf-private-size-', dir=ROOT / 'artifacts') as folder:
            root = Path(folder)
            (root / 'stage.json').write_text(json.dumps({'workshop_id': 0}), encoding='utf-8')
            with patch('scripts.private_workshop_release.verify_workshop_stage', return_value={
                    'workshop_id': 0, 'bytes': MAX_UPLOAD_BYTES + 1}):
                with self.assertRaisesRegex(ValueError, '512 MiB'):
                    _stage(root, 'unused', 'unused')

    def test_vdf_is_private_before_and_after_steam_assigns_an_id(self):
        with tempfile.TemporaryDirectory(prefix='agf-private-vdf-', dir=ROOT / 'artifacts') as folder:
            root = Path(folder)
            self.assertTrue(root.resolve().is_relative_to((ROOT / 'artifacts').resolve()))
            content = root / 'content'
            content.mkdir()
            preview = root / 'preview.jpg'
            preview.write_bytes(b'jpeg preview')
            vdf = root / 'create.vdf'
            report = _vdf(vdf, 0, content, preview, 'Example', 'Private campaign', 'Initial')
            self.assertEqual(report['visibility'], 2)
            self.assertIn('"visibility" "2"', vdf.read_text(encoding='utf-8'))
            with self.assertRaisesRegex(ValueError, 'not assigned'):
                _assigned_id(vdf)
            vdf.write_text(vdf.read_text(encoding='utf-8').replace(
                '"publishedfileid" "0"', '"publishedfileid" "1234567890"'), encoding='utf-8')
            self.assertEqual(_assigned_id(vdf), 1234567890)
            vdf.write_text(vdf.read_text(encoding='utf-8').replace(
                '"visibility" "2"', '"visibility" "0"'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not assigned'):
                _assigned_id(vdf)

    def test_complete_update_receives_steam_id_without_changing_map(self):
        with tempfile.TemporaryDirectory(prefix='agf-private-complete-', dir=ROOT / 'artifacts') as folder:
            root = Path(folder)
            self.assertTrue(root.resolve().is_relative_to((ROOT / 'artifacts').resolve()))
            stage = root / 'stage'
            name = 'WarnoAGF_example_WorkshopBuild12345678'
            source = stage / 'mod' / name
            (source / 'Maps').mkdir(parents=True)
            map_bytes = b'complete strategic map'
            (source / 'Maps' / 'example.dat').write_bytes(map_bytes)
            original_config = (b'[Properties]\nName = Example\nID = 8000000000000000\n'
                               b'PreviewImagePath = \nDeckFormatVersion = 1\nModGenVersion = 201602\n'
                               b'CosmeticOnly = 0\n[Config]\nGFX/Pawn=' + b'a' * 32 + b'\n')
            stage_config = original_config.replace(b'ID = 8000000000000000', b'ID = 0')
            (source / 'Config.ini').write_bytes(stage_config)
            preview = stage / 'preview' / 'cover.jpg'
            preview.parent.mkdir(parents=True)
            preview.write_bytes(b'jpeg preview')
            private = stage / 'steamcmd-private'
            placeholder = private / 'placeholder'
            placeholder.mkdir(parents=True)
            vdf = private / 'create.vdf'
            _vdf(vdf, 1234567890, placeholder, preview, 'Example', 'Private campaign', 'Initial')
            (private / 'create-prepared.json').write_text(json.dumps({
                'source_bundle_id': 'bundle'}), encoding='utf-8')
            description = root / 'description.md'
            description.write_text('A private campaign description for testing.', encoding='utf-8')
            compiled = root / 'compiled.json'
            compiled.write_text(json.dumps({'campaign': {'id': 'example',
                'title': {'en': 'Example', 'ru': 'Example'}}}), encoding='utf-8')
            stage_report = {'publisher_folder': name, 'files': {
                'Config.ini': sha256(stage_config), 'Maps/example.dat': sha256(map_bytes)}}
            verified = {'source_bundle_id': 'bundle'}
            identity = {'display_name': 'Example', 'local_mod_id': 8000000000000000}
            with patch('scripts.private_workshop_release._stage', return_value=(
                    stage, stage_report, verified, preview)), \
                 patch('scripts.private_workshop_release.verify_full_bundle', return_value=(
                    {'bundle_id': 'bundle'}, {'Config.ini': original_config, 'Maps/example.dat': map_bytes})), \
                 patch('scripts.private_workshop_release.campaign_identity', return_value=identity):
                result = prepare_full_update(stage, 'unused', compiled, description)
            self.assertEqual(result['publishedfileid'], 1234567890)
            self.assertEqual(result['visibility'], 2)
            self.assertEqual((private / 'complete-content' / 'Maps' / 'example.dat').read_bytes(), map_bytes)
            self.assertIn(b'ID = 1234567890', (private / 'complete-content' / 'Config.ini').read_bytes())

    def test_existing_private_item_update_keeps_id_and_can_capture_download(self):
        with tempfile.TemporaryDirectory(prefix='agf-private-existing-', dir=ROOT / 'artifacts') as folder:
            root = Path(folder)
            stage = root / 'stage'
            name = 'WarnoAGF_example_WorkshopBuildABCDEF12'
            source = stage / 'mod' / name
            source.mkdir(parents=True)
            preview = stage / 'preview' / 'cover.jpg'
            preview.parent.mkdir(parents=True)
            preview.write_bytes(b'jpeg preview')
            old = (b'[Properties]\nName = Example\nID = 8000000000000000\n'
                   b'PreviewImagePath = \nDeckFormatVersion = 1\nModGenVersion = 201602\n'
                   b'CosmeticOnly = 0\n[Config]\nGFX/Pawn=' + b'a' * 32 + b'\n')
            identity = {'display_name': 'Example', 'local_mod_id': 8000000000000000}
            item_id = 3811284575
            (source / 'Config.ini').write_bytes(_workshop_config(old, identity, item_id, preview))
            (source / 'map.dat').write_bytes(b'unchanged map')
            (stage / 'previous-publication.json').write_text(json.dumps({
                'format': 'agf-workshop-publication/v1', 'workshop_id': item_id,
                'subscriber_verified': True}), encoding='utf-8')
            description = root / 'description.md'
            description.write_text('Updated private campaign with stronger support.', encoding='utf-8')
            compiled = root / 'compiled.json'
            compiled.write_text(json.dumps({'campaign': {'id': 'example',
                'title': {'en': 'Example', 'ru': 'Example'}}}), encoding='utf-8')
            stage_report = {'publisher_folder': name, 'source_campaign_id': 'example',
                            'workshop_id': item_id,
                            'files': {'Config.ini': sha256(old),
                                      'map.dat': sha256(b'unchanged map')}}
            verified = {'source_bundle_id': 'bundle', 'workshop_id': item_id}
            with patch('scripts.private_workshop_release._stage', return_value=(
                    stage, stage_report, verified, preview)), \
                 patch('scripts.private_workshop_release.verify_full_bundle', return_value=(
                    {'bundle_id': 'bundle'}, {'Config.ini': old, 'map.dat': b'unchanged map'})), \
                 patch('scripts.private_workshop_release.campaign_identity', return_value=identity):
                prepared = prepare_existing_update(stage, 'bundle', compiled, description,
                                                    change_note='Balanced forces')
                self.assertEqual(prepared['publishedfileid'], item_id)
                self.assertEqual(prepared['visibility'], 2)
                self.assertEqual(prepared['upload_bytes'], sum(
                    path.stat().st_size for path in (stage / 'steamcmd-private/complete-content').rglob('*')
                    if path.is_file()))
                downloaded = root / 'steamapps/workshop/content/1611600' / str(item_id)
                downloaded.mkdir(parents=True)
                with patch('scripts.private_workshop_release.verify_workshop_subscriber',
                           return_value={'workshop_id': item_id, 'runtime_files_identical': True}):
                    publication = capture_download(stage, 'bundle', compiled, downloaded)
            self.assertEqual(publication['workshop_id'], item_id)
            self.assertTrue(publication['subscriber_verified'])


if __name__ == '__main__':
    unittest.main()
