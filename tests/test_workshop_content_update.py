"""The content uploader must never submit author-managed item metadata."""
import ast
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'scripts/workshop_content_update.py'
spec = importlib.util.spec_from_file_location('content_updater', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContentUpdateTests(unittest.TestCase):
    def test_metadata_changes_are_rejected(self):
        before = dict(id=1, owner=2, creator=1611600, consumer=1611600,
                      title='Example', description='[h1]Author text[/h1]\r\n',
                      visibility=2, tags='Campaign')
        module.unchanged(before, dict(before))
        for key in before:
            after = dict(before)
            after[key] = 'changed'
            with self.assertRaisesRegex(RuntimeError, key):
                module.unchanged(before, after)

    def test_no_metadata_setter_is_bound_or_called(self):
        tree = ast.parse(PATH.read_text(encoding='utf-8'))
        strings = {node.value for node in ast.walk(tree)
                   if isinstance(node, ast.Constant) and isinstance(node.value, str)}
        for setter in ('SetItemTitle', 'SetItemDescription', 'SetItemVisibility', 'SetItemTags'):
            self.assertFalse(any(setter in text for text in strings))
        self.assertIn('SetItemContent', strings)
        self.assertIn('SetItemPreview', strings)


if __name__ == '__main__':
    unittest.main()
