# 11. Artwork, decision cards and emblems

[Recipe index](../RECIPES.md) · [Русская версия](11-artwork.ru.md) · [Presentation bindings](10-objectives.md#camera-introductions-and-endings)

## Basic procedure: replace an existing event picture

1. Find the event or slide's logical `image` ID in `events.yaml` or `cinematics.yaml`.
2. Find the same ID under `event-images.yaml.images`.
3. Replace the local image file at that relative path, keeping its name and declared ID.
4. Keep source attribution/licenses in `ASSET_CREDITS.md` when needed.
5. Check/build and inspect the new presentation in a fresh campaign.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/artwork-check-01
```

Keeping the logical ID avoids changing every consumer. Replacing a file without rebuilding does not update an installed texture bank.

## Register a new logical image

Add a source file inside the campaign, such as `artwork/events/reserve.png`, then add under `event-images.yaml.images`:

```yaml
reserve_picture: artwork/events/reserve.png
```

With namespace `my_campaign`, register the same ID under `profile.yaml.event_images`:

```yaml
reserve_picture: AGF_EVT_my_campaign_reserve_picture
```

Use `image: reserve_picture` in the event/slide. The image file, logical ID, namespace and token are four related pieces. A URL is source attribution, not a local image file. Paths are relative to the campaign root and cannot escape through `..` or an absolute path.

## Two illustrated choices

Register both source images, then create a composite in `event-images.yaml`:

```yaml
schema: agf-event-images/v2
namespace: my_campaign
images:
  reserve_left: artwork/events/reserve-left.png
  reserve_right: artwork/events/reserve-right.png
composites:
  reserve_cards:
    kind: two_cards
    cards: [reserve_left, reserve_right]
```

Merge these fields into the existing document rather than drop its other images. Add profile tokens for all referenced image/composite IDs. In the event use `image: reserve_cards`, `layout: graphic_cards`; in each choice add:

```yaml
card:
  image: reserve_left
  title: {ru: Первый вариант, en: First Option}
  text: {ru: Краткое описание варианта., en: A short description of the option.}
```

The second choice uses `reserve_right`. Preserve composite order: first source is the left card/choice 0, second the right card/choice 1. Both choice `label` and `effects` remain required. Text is localized UI content, not text you must bake into the source PNG. Changing images does not change the decision's effects.

An ordinary image-backed text event can use a single picture. `plain: {some_id: text_choice}` creates a service background for text choices, not a photograph or an automatically illustrated scene. Composites accept original image IDs only, not other composites.

## Menu artwork

`campaign.yaml.menu.image` is a relative path to a **landscape PNG**, not a logical event ID. Width must be 400–4096 pixels and aspect ratio 1.5–2.5. The compiler produces a proportional 400-pixel-wide menu texture.

Example:

```yaml
image: artwork/menu-map.png
```

This belongs inside `menu`. Menu artwork is separate from the Steam Workshop cover. A Workshop preview is PNG/JPG/JPEG below 1,000,000 bytes; see [distribution](14-build.md#workshop-staging).

## Custom formation emblem

Put a PNG in `artwork/emblems/`, then declare in `emblems.yaml`:

```yaml
schema: 1
emblems:
- token: Texture_Division_Emblem_AGF_Coastal
  image: artwork/emblems/coastal.png
```

Reference it inside the battalion's `definition.formation`:

```yaml
emblem: Texture_Division_Emblem_AGF_Coastal
```

The rest of formation still needs division_id, division_text, regiment_id. Assign a shared formation's members a consistent emblem. A custom token needs a declaration; an existing native token needs the matching installed resource. SVG originals can be retained for provenance, but this input requires a local PNG conversion.

National/coalition flags and strategic national bases are separate native resources. A brigade emblem does not change them. The current public format provides formation-emblem declarations, not an arbitrary national-flag replacement API.

## All image constraints

| Input | Accepted format and constraints |
| --- | --- |
| Event-image root | `agf-event-images/v2`, namespace, images; optional composites/plain |
| Namespace and logical IDs | Lowercase letter first, lowercase letters/digits/underscores, ≤48 characters |
| Event source images | Static RGB/RGBA PNG or WebP; each axis 2–8192 |
| `composites` | Unique IDs, `kind: two_cards`, exactly two original source-image IDs |
| `plain` | Logical ID → `text_choice` |
| Profile event token | `AGF_EVT_<namespace>_<logical_ID>` matching the declaration |
| Menu source | Landscape PNG, width 400–4096, ratio 1.5–2.5 |
| Emblem root | `schema: 1`, emblems list of exact `{token,image}` entries |
| Custom emblem token | Unique `Texture_Division_Emblem_AGF_[A-Za-z0-9_]+` |
| Emblem source | PNG at least 64×64, file ≤4,000,000 bytes; square transparency recommended |
| Credits file | Campaign `ASSET_CREDITS.md`, valid UTF-8, ≤256 KB |

Legacy event schema v1 supports original images only; use v2 for composite decisions. World surface and heightmap images have different formats/orientation rules in [geography](13-geography.md); do not apply event-image RGBA rules to them.

## How the mechanism works

Checking prepares source images and composite artwork. The complete build cooks private texture resources and registers their tokens in the mod's texture banks. Native presentations fill named picture/text components from the event or cinematic declarations. A valid local picture without a matching token/reference cannot be displayed by that presentation.

Emblems are cooked into their own registered resource path and referenced by formation metadata. The helper handles cooking; users do not need to edit TGV or NDF manually. Keep source originals and their permission/attribution records so future builds remain reproducible.

## Troubleshooting

Missing texture: inspect relative source path, declared ID, profile token and presentation reference. Wrong paired picture: inspect both composite order and choice.card.image. Old artwork after replacement: rebuild and inspect a new campaign. Emblem unchanged: inspect formation metadata, not the event-image table. Menu/cover confusion: use their separate input fields. Text overlaps: shorten card text and use the declared presentation layout; an image resolution change does not alter the text widget's bounds.
