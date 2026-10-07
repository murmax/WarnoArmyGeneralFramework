# 12. Names and translations

[Recipe index](../RECIPES.md) · [Русская версия](12-localization.ru.md)

## Basic procedure: change one displayed sentence

1. Edit the intended `text.ru` and `text.en` in its event, slide or menu field.
2. In `localization.yaml`, find the **old exact English string** under every enabled language table.
3. Replace that key with the new English string and update its translated value.
4. Check the campaign. Resolve missing-string and short-name errors before building.
5. Build and inspect the relevant UI in a fresh campaign with the intended game language.

```yaml
text:
  ru: Резерв прибудет вечером.
  en: Reserves will arrive this evening.
```

```yaml
# Under translations.fr; update corresponding entries in other enabled tables
"Reserves will arrive this evening.": "Les renforts arriveront ce soir."
```

Do not add a second `translations` mapping or lose the other entries. The quoted key is the actual English content, not an event ID.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/localization-check-01
```

## How to rename an OOB entry

For a battalion, edit `definition.name` and, when present, `name_text`:

```yaml
name: Coastal Infantry Bn
name_text:
  ru: Береговой пехотный бат.
  en: Coastal Infantry Bn
```

Use the corresponding `organization_text`, company/platoon `name_text`, or `formation.division_text` for those headings. Keep the base names short too. Explicit localized fields have their own purpose; changing only a base `name` while leaving the old `name_text` can retain the old displayed heading.

After changing the English localized heading, update every enabled translation key. [Rosters](03-rosters.md) identifies each name's structural scope.

## Supported languages and fallback

| YAML locale | Game dictionary bank | Source |
| --- | --- | --- |
| `ru` | RU | Bilingual fields directly; no translations.ru table |
| `en` | US and DEV | English fields, optional en table for base strings |
| `fr` | FR | translations.fr |
| `de` | GER | translations.de |
| `es` | SPA | translations.es |
| `pl` | POL | translations.pl |
| `zh` | SC | translations.zh |

These are seven languages/eight native banks. Use YAML locale codes, not native bank names such as `GER` as table keys.

The `localization.yaml` root is exactly `schema: 1`, `source_language: en`, `translations`. Each table maps nonempty English strings to nonempty translated strings. Any enabled non-English table must cover the whole required campaign vocabulary. A half-filled French table is not completed automatically from English.

A wholly absent language uses English fallback. To author RU/EN only, omit `localization.yaml`, or remove entire optional language tables instead of leaving incomplete ones. A mod using fallback is not fully translated into that language. The optional `en` table can resolve shared base-name strings where explicit RU/EN fields are absent.

## Exact matching and YAML text

Keys are case-sensitive source strings, including punctuation, spaces and actual line breaks. “Reserve” and “Reserves” are different keys. Quote keys/values containing YAML punctuation or words that YAML might parse as booleans/null. A duplicate key is rejected.

`>-` folds consecutive source lines into spaces; `|-` preserves newlines. Their displayed content differs from the source file's indentation. When changing a long block, keep the translation key aligned with its **parsed** English text. The missing-translation error reports the actual expected string. Update matching paragraphs rather than a guessed shortened version.

Native presentation may combine separately authored title/body paragraphs. The translator can resolve multi-line combined content paragraph by paragraph; still provide translations for the original title/body strings and preserve intended paragraph boundaries.

## Short names: the important limit

Battalion, organization, shared formation, company and platoon OOB names must fit **1–30 UTF-16 units** after resolution in every game language. The limit includes spaces and punctuation. Common Latin/Cyrillic characters usually occupy one unit; many supplementary characters occupy two.

For a candidate abbreviation in PowerShell:

```powershell
$name = 'Coastal Infantry Bn'
$name.Length
```

.NET strings count UTF-16 units. This is a convenient name-length check, not a replacement for the full campaign check. Use a meaningful military abbreviation per language, not blind slicing that destroys the word or unit identity.

Event, introduction and menu narratives use other controls; do not impose the OOB's 30-unit limit on all text. Translation values may be up to 20,000 characters, but that maximum does not imply they fit a particular screen. Write short card subtitles and readable slide paragraphs, then inspect their layouts.

## Placeholders and formatting

- Preserve every `%0`, `%1` and similar numbered placeholder, with the same occurrences. Their order can follow grammar.
- Preserve native `#US`/`#SOV` coalition markup and its order where present.
- Keep required translated values nonempty and without NUL characters.
- Keep both RU and EN fields even when additional tables exist.
- `voice_script` is narration preparation, not a required on-screen translation or an audio file.

The validator checks placeholder occurrences and coalition markup. It does not judge translation quality, geographic terminology or whether an abbreviation is understandable.

## Additional useful workflows

Use one consistent translation for repeated English source strings: the dictionary is global by text, not separately keyed by each event. If the same English word needs different meanings, author distinct English source phrases first. To add another supported language, create its table and complete every required source string, using the check's errors and the supplied full example as a structural starting point.

Stock tactical-unit names are generally supplied by WARNO's own localization. Your campaign headings, custom prose and formation names are separate. Renaming a company does not rename the native tactical unit cards within it.

## How the mechanism works

The compiler gathers bilingual campaign strings and generated presentation vocabulary, resolves the selected locale, writes native dictionaries and checks short OOB strings after translation. RU is taken directly from its fields; other locales use English as their source key. Disabled tables fall back as described above.

Shared text matching is why a changed English key must be changed in every enabled table. It is also why a valid source name can fail only after its longer translated version is resolved.

## Troubleshooting

Missing translation: copy the exact string shown in the error, including newline semantics. Russian text in English OOB: check explicit name_text/organization_text/division_text and source-language entries. A crash-prone long heading: shorten the resolved short name in every table and run check. Unchanged text after installation: use the new complete build and start fresh. A formatting error: preserve placeholders/markup and YAML quoting instead of deleting them.
