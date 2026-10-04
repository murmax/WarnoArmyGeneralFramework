import unittest

from warno_ag.localisation import compile_localisation, field, translate


class LocalisationTests(unittest.TestCase):
    def document(self, values):
        return {'schema': 1, 'source_language': 'en', 'translations': {'fr': values}}

    def test_native_language_mapping_and_legacy_compatibility(self):
        value = {'ru': 'Пример', 'en': 'Example'}
        c = {'localisation': self.document({'Example': 'Exemple', 'Body': 'Texte'})}
        self.assertEqual(field(c, value, 'RU'), value['ru'])
        self.assertEqual(field(c, value, 'FR'), 'Exemple')
        self.assertEqual(field({}, value, 'GER'), 'Example')
        self.assertEqual(translate(c, 'Example\n\nBody', 'FR'), 'Exemple\n\nTexte')

    def test_declared_locale_never_silently_falls_back(self):
        c = {'localisation': self.document({'Example': 'Exemple'})}
        with self.assertRaisesRegex(ValueError, 'Missing fr'):
            translate(c, 'Missing', 'FR')

    def test_bad_placeholder_and_markup_are_rejected_before_compilation(self):
        for source, target, error in (
            ('Locked for %1 turns', 'Bloqué', 'placeholder'),
            ('{#US} Attack', 'Attaque', 'coalition markup'),
        ):
            with self.assertRaisesRegex(ValueError, error):
                compile_localisation(self.document({source: target}), {})

    def test_unknown_language_and_empty_text_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'language/table'):
            compile_localisation({'schema': 1, 'source_language': 'en',
                                  'translations': {'unknown': {}}}, {})
        with self.assertRaisesRegex(ValueError, 'translation entry'):
            compile_localisation(self.document({'Example': ''}), {})


if __name__ == '__main__':
    unittest.main()
