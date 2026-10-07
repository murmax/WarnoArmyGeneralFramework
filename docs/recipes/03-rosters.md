# 3. Battalion rosters and custom packs

[Recipe index](../RECIPES.md) · [Русская версия](03-rosters.ru.md) · [Support formations](04-support.md)

## Basic procedure: add one vehicle or squad

1. In `battalions/forces.yaml`, locate the battalion by its top-level `id`.
2. Under `definition.companies`, select a company, then a platoon under `platoons`.
3. Increase the intended `units` entry's `count`, for example `3` to `4`.
4. Check, build, and inspect the OOB of a new campaign.

```yaml
units:
- type: my_rifle_pack
  count: 4
```

This fragment belongs inside an existing platoon. `my_rifle_pack` must already be a stock or custom pack ID. Replace it with the actual referenced pack; it is not a tactical unit ID.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/roster-check-01
```

`count` controls roster entries of this pack. Check its `number` before interpreting the total: `count: 4` with `number: 2` represents eight units rather than four. A displayed company name does not select its equipment.

## Select a different tactical unit or transport

Export the installed catalogs once to a new directory:

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py catalog --game $game --output artifacts/catalog-01
```

Open `units.csv` to identify the actual tactical unit. Open `packs.csv` to find an existing combination of unit, transport, experience and number. Use the pack's `id` as the platoon entry's `type`.

If the combination is not present, add a custom entry to the existing `packs.yaml.packs` list:

```yaml
- id: my_rifle_btr60
  unit: Naval_Rifle_SOV
  transport: BTR_60_Naval_SOV
  experience: 1
  number: 1
```

Then change only the intended platoon's `type` to `my_rifle_btr60`. These example IDs must exist in your compatible game catalog. For a unit without a transport use YAML `null`, not the string `"null"`.

Transport inspection:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag editor-pack-options Naval_Rifle_SOV
```

Existence, transport classification and roster role are checked. The framework does not judge historical suitability or campaign balance.

## Make a change local to one platoon

Packs are shared definitions. If three platoons reference the same pack, changing that pack changes all three. To improve only one platoon:

1. Copy the entire custom pack entry under a new unique ID.
2. Change `unit`, `transport`, `experience` or `number` in the copy.
3. Reference the new ID only in the selected platoon.

For stock packs, create a new custom entry from the catalog values rather than redefining the stock ID. A custom ID that duplicates a stock pack is rejected.

## Add or reorganize companies

Copy the full company or platoon mapping, including required names, `hq` and subordinate lists. Company IDs are unique within their battalion; platoon IDs within their company. Different battalions may each have a company named `rifle_1`.

Every company needs at least one platoon, every platoon at least one unit entry. Move actual unit entries when reorganizing; changing the heading alone does not move their contents. Keep command, supply and support units appropriate to the formation's intended use; see [support](04-support.md).

For a new strategic battalion, copy its **whole** battalion object, give it a new campaign-wide ID, then choose exactly one appearance mechanism: [initial deployment](08-readiness.md), [reserve card](05-reserves.md), [automatic/event arrival](06-events.md), or [aviation](09-aviation.md). A new roster definition alone does not appear on the map.

## Parameters: roster structure and packs

| Path | Constraint | Purpose |
| --- | --- | --- |
| Battalion file root | `schema: 1`, `battalions: [...]` | One or more source files under `battalions/` |
| Battalion `id` | Unique lowercase identifier campaign-wide | Reference from deployment/arrival/AI phase |
| Battalion `side` | `nato`/`pact` | Coalition membership |
| `definition.country` | Supported country code in that side's countries | National identity/visual base |
| `definition.name`, `organization` | Nonempty short strings, ≤30 UTF-16 units | Base OOB names |
| `definition.name_text`, `organization_text` | Optional RU/EN, each short | Explicit localized OOB names |
| Company `id`, `name`, `hq`, `platoons` | Required; `hq` boolean, list nonempty | OOB company structure |
| Platoon `id`, `name`, `hq`, `units` | Required; `hq` boolean, list nonempty | OOB platoon structure |
| Company/platoon `name_text` | Optional RU/EN, each ≤30 UTF-16 units | Localized headings |
| Unit entry `type` | Existing pack ID | Tactical unit/transport combination |
| Unit entry `count` | Integer 1–100 | Number of roster entries |
| Custom pack `id` | Unique `[A-Za-z0-9_]+`, not a stock pack ID | New reusable combination |
| Custom pack `unit` | Tactical ID from `units.csv` | Actual combat unit |
| Custom pack `transport` | Registered transport ID or `null` | Actual transport |
| Custom pack `experience` | Integer 0–3 | Native experience level |
| Custom pack `number` | Integer 1–10 | Units represented by one entry |

All five custom pack fields are required. Short-name limits apply in every translated OOB language too; [localization](12-localization.md) explains UTF-16 counting. They do not apply to long campaign briefings.

## Formation and names

Optional `definition.formation` contains:

```yaml
formation:
  division_id: coastal_brigade
  division_text: {ru: Береговая бригада, en: Coastal Brigade}
  regiment_id: coastal_regiment
  emblem: Texture_Division_Emblem_AGF_Coastal
```

`division_id`, `division_text` and `regiment_id` are required together; `emblem` is optional. Battalion members sharing the same division ID on a side share formation metadata, so keep their higher name and emblem consistent. Register a custom emblem before using its token. The example token above is not a built-in resource.

`organization_text` is the battalion's regiment/subordination caption; `division_text` is the shared higher formation. These are independent of `campaign.menu.side_titles`.

## Strategic appearance and function

`definition.strategic` has required `type`, `battle_role`, `visual`. Ground and helicopter formations can also have `icon`; airplane roles select their icon automatically.

| Field | Accepted values |
| --- | --- |
| `type` | `mechanized`, `helicopter`, `airplane` |
| `battle_role` | `fighter`, `ground_support`, `auxiliary_support`, `air_support` |
| `visual` | Prefer `{unit: actual_tactical_ID}` |
| Ground/helicopter `icon` | `Infantry`, `apc`, `ifv`, `Armor`, `Armor_heavy`, `HQ`, `reco`, `AA`, `AT`, `hel`, `howitzer`, `mlrs`, `assault` |
| Airplane `aircraft_role` | `fighter`, `bomber`, `sead` |
| `support` | Artillery/AA radius, explained in [support](04-support.md) |

An infantry battalion still uses strategic `type: mechanized`; there is no separate `type: infantry`. Its icon and visible model can be infantry. `airplane` requires `air_support` and an appropriate aircraft roster; ground/helicopter formations cannot declare `air_support`.

Changing `visual` or `icon` changes the strategic representation, not the tactical roster. The framework cannot change unit armor, weapon statistics, tactical movement speed or cost through packs or names.

Legacy visual presets are `west_german_infantry`, `east_german_infantry`, `west_german_armor`, `east_german_armor`, `soviet_armor`, and `us_helicopter`. Use explicit catalog appearances for new formations. Normal AP/fatigue settings belong in [initial state](08-readiness.md).

## Troubleshooting

Unknown `type`: check the pack catalog, not only `units.csv`. A duplicate battalion-use error requires distinct battalion definitions for each possible strategic instance, even exclusive choices. Unexpected changes in other formations usually indicate a shared pack. A new tactical unit with an unchanged map model needs a separate `strategic.visual` change. A country/air-role error requires matching country membership, visual support and aircraft tags rather than a different displayed name.
