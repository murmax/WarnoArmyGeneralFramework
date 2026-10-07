# 1. Campaign identity, titles and sides

[Recipe index](../RECIPES.md) · [Русская версия](01-identity.ru.md) · [File reference](../YAML_REFERENCE.md#1-campaignyaml)

## Basic procedure: give your copied campaign a new title

First create an independent source with `clone` as shown in [Getting started](../GETTING_STARTED.md#3-create-independent-source). Work in `campaigns/my-campaign`, not the supplied example.

1. Open `campaign.yaml` and edit the top-level `title` and `summary`.
2. Edit the existing `menu.header`, `subtitle`, `description` and both `side_forces` entries. Keep their indentation under `menu`.
3. Update translations for each changed English string, following [the translation guide](12-localization.md).
4. Check the source, then build and begin a new campaign.

```yaml
title:
  ru: Оборона побережья
  en: Coastal Defense
summary:
  ru: Удержите порт до прибытия резервов.
  en: Hold the port until reserves arrive.
```

This replaces existing fields. Do not add a second `title` or a second `menu` block.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/identity-check-01
```

Use a new output path on each run. The check does not change an installed mod.

## Name the armies in the menu

Add this optional block **inside the existing `menu` mapping**:

```yaml
side_titles:
  nato: {ru: Экспедиционный корпус, en: Expeditionary Corps}
  pact: {ru: Прибрежная армия, en: Coastal Army}
```

Both side keys and both languages are required when the block is present. They label the menu sides; they do not rename battalions or change their tactical units. For OOB names use [rosters](03-rosters.md); for insignia use [artwork](11-artwork.md).

## What else you can change

- Write a longer menu description with `|-` to preserve paragraphs.
- Give a side several supported countries and use battalions from them.
- Set which side is described as the attacker in the campaign-selection menu.
- Fork a campaign into another independent scenario using `clone`.
- Keep objective IDs stable while changing their displayed names and text.

To fork an existing source:

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py clone campaigns/my-campaign campaigns/coastal-defense --id coastal_defense
```

Choose a new destination and ID. Avoid renaming technical identities by hand after building a campaign.

## Settings and where to edit them

| Location | Accepted value | Effect and scope |
| --- | --- | --- |
| `campaign.yaml.schema` | `1` | Authoring format version; retain it |
| `campaign.yaml.id` | Use a cloned lowercase identifier | Technical campaign identity, not the screen title |
| `campaign.yaml.template` | Matches `profile.yaml.id` | Selects the compatible profile |
| `title`, `summary` | Nonempty `ru` and `en` strings | Campaign title and short summary |
| `sides.nato.countries`, `sides.pact.countries` | Nonempty supported country-code lists | Countries available to that coalition; roster countries must belong to the list |
| `sides.<side>.playable` | Boolean | Playability declaration; the current template requires both sides playable |
| `menu.header`, `subtitle`, `description` | Nonempty RU/EN text | Campaign-selection text; use block text for paragraphs |
| `menu.side_forces` | Both sides, each with RU/EN text | Descriptions of forces |
| `menu.side_titles` | Optional, both sides with RU/EN text | Menu army captions |
| `menu.attacker` | `nato` or `pact` | Menu Attack/Defense labels |
| `menu.image` | Campaign-relative landscape PNG | Selection artwork; [image constraints](11-artwork.md#menu-artwork) apply |
| `ai_policy.native_strategies` | Side → `attacker`/`defender` | Native strategic AI role; independent of `menu.attacker` |

The `menu` block, when used, requires `header`, `subtitle`, `description`, `side_forces`, `image` and `attacker`. Optional fields do not make required fields optional.

The clone helper accepts an ID of 1–48 lowercase Latin letters, digits and underscores, beginning with a letter. It updates campaign/profile identity and event-image tokens and creates an independent map name. Paths and technical identifiers remain untranslated.

The strategic visual-base adapter supports `US`, `RFA`, `SOV`, `RDA`/`DDR`, `UK`, `BEL`, `NL`, `POL`, `CAN`, `ESP`, `FR`, `TCH`, and `CUB`. A country code alone does not create corresponding tactical forces: select real units and transports from the installed catalog. Broader country support requires an adapter capability.

## How the mechanism works

The framework derives native scenario, unit and localization identities from source identifiers. It compiles human text into localization dictionaries separately. Renaming `title.en` changes text; it does not create another independent scenario. Conversely, cloning with a new technical ID creates independent descriptors even before you edit the displayed title.

The internal side names `nato` and `pact` are the two native coalition slots. They do not force every campaign to be specifically US versus Soviet. Country membership, actual rosters, menu wording, and native AI roles are separate settings.

Formation names have another scope: `definition.organization_text` names the regiment/subordination entry, while `definition.formation.division_text` names its shared higher formation. Neither is the menu army caption. [Formation settings](03-rosters.md#formation-and-names) explain this relationship.

## Related changes and common problems

| Symptom or intention | Action |
| --- | --- |
| New title, old menu description | Update existing menu fields and translations, not just `title` |
| Attack/Defense reversed in selection | Edit `menu.attacker`; inspect AI roles independently |
| A country change fails checking | Match battalion countries and supported strategic visual bases to `sides` |
| Two campaign copies collide | Recreate the fork with `clone` and a new identity |
| Rename an objective internally | Update victory, AI targets/routes, events, reserve requirements, camera and ending bindings together; see [objectives](10-objectives.md) |
| New source text appears untranslated | Update every enabled table keyed by that exact English string |

Do not reuse an old save to assess identity or OOB changes. Build a complete mod using [the build workflow](14-build.md).
