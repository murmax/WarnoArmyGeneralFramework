# YAML reference: complete campaign format

For **framework 1.1.1**, using [Kacha V20](../campaigns/kacha/README.md). [Setup/build](GETTING_STARTED.md) · [Recipes](RECIPES.md) · [Русский справочник](YAML_REFERENCE_RU.md).

These are public authoring fields, not WARNO's internal script objects. Only documented keys are accepted. Required fields remain required when their value is `[]` or `null`. Asset paths are campaign-relative, use `/` and cannot escape through `..`.

## 0. Common rules

Save UTF-8. Indent with spaces, normally two per level. `-` starts a list item; `#` starts a comment outside quotes. `true`/`false` are booleans; `null` means no value; `[]` is an empty list; `{}` is an empty mapping. Quote text containing a colon, or use a block:

```yaml
text:
  ru: >-
    Разведка докладывает: противник готовит высадку.
    Подготовьте резервы.
  en: >-
    Intelligence reports an imminent landing.
    Prepare your reserves.
```

`>-` joins lines with spaces; `|-` preserves line breaks. Duplicate mapping keys are rejected. Keep all nested indentation when copying an object.

| Concept | Rule |
| --- | --- |
| Identifier | Usually `[a-z][a-z0-9_]*`; unique within its category, untranslated |
| Side | `nato` or `pact`, internal coalitions rather than necessarily USA/USSR |
| Country | Installed supported country code; common examples US, SOV, RFA, RDA, UK, FR. Visual bases additionally support BEL, NL, POL, CAN, ESP, TCH, CUB and DDR/RDA mapping |
| Localized text | Exactly `{ru: ..., en: ...}` with nonempty strings; additional languages use localization.yaml |
| Position | `[x,y]` in native game units, inside profile bounds; not kilometers or longitude/latitude |
| Bounds | `[min_x,min_y,max_x,max_y]` |
| Turn | Integer, first is 1; scheduled arrivals/events must be inside campaign duration |
| Short OOB names | Battalion, formation, company, platoon: 1–30 UTF-16 units, including translated versions |
| Fatigue | 0 fresh, 8 exhausted; 7/8 is not high readiness |
| AP | Initial current points differ from capacity/recovery; use the relevant field |

Required files: campaign.yaml, map.yaml, deployments.yaml, reinforcements.yaml, events.yaml, ai.yaml, at least one battalions/*.yaml and the supplied profile. The helper expects that profile at source/profile.yaml. Optional files become necessary when their content is referenced.

### Reference graph

`packs.yaml → battalions → deployment / production / event spawn / aviation`.
`map flags/waypoints → AI / events / victory / camera`.
`event choices → conditional production / aircraft availability`.
`event-images → profile tokens → events / cinematic slides`.
`world + profile + strategic grid → complete map build`.

## 1. campaign.yaml

**Optional `victory.pact_capture_immediate`:** boolean, default `true`. Kacha V20 sets it to `false`, so Soviet capture of `pact_capture` does not immediately end the campaign; the existing time-limit/score rules remain. NATO's `nato_capture` goal is unchanged. This option does not create a separate recapture timer.

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | Yes | 1 |
| `id` | Yes | Independent campaign identity; create forks with clone |
| `template` | Yes | Equals profile.id |
| `title`, `summary` | Yes | RU/EN title and short UI objective summary |
| `turns` | Yes | Integer ≥2 |
| `date` | Yes | Four integers `[year,month,day,period]`; period is not an hour. Kacha's `[1989,9,7,2]` starts at noon |
| `score_to_win` | Yes | Positive integer score threshold |
| `sides` | Yes | Both nato/pact, each with nonempty `countries` list and boolean `playable` |
| `victory` | No | Immediate capture goals and deadline outcome |
| `capture_deadline` | No | Early capture permanently prevents a reserve division deployment |
| `menu` | No | Independent campaign-menu metadata |
| `ai_policy` | No | General AI policy, section 7 |

Use a valid calendar date; shape validation does not establish calendar validity. The public format does not separately change period duration.

### victory and capture_deadline

```yaml
victory:
  nato_capture: sevastopol
  pact_capture: kacha_beach
  time_limit: pact
capture_deadline:
  flag: simferopol
  owner: nato
  before_turn: 9
  division: sov_157
```

Each block requires every displayed field. Victory goals are distinct map flag IDs; by default, capture by the corresponding side ends the campaign (see pact_capture_immediate above). `time_limit` is draw/nato/pact. Without victory, the base result/score mechanism applies. Flag scores and immediate capture victory are different rules.

The early-capture rule names an existing flag, side, cutoff 2…turns and production division. That division's groups cannot arrive before the cutoff. It requires directed production with AI plans for all groups. An early capture latches deployment prevention; later recapture does not undo it. The deadline-notice event reports the result but does not define the rule.

### menu

Required inside menu: `header`, `subtitle`, `description`, `side_forces`, `image`, `attacker`. First three are RU/EN strings; side_forces contains nato/pact RU/EN force descriptions. Use `|-` for paragraphs.

`image` is a landscape PNG, width 400–4096 and aspect ratio 1.5–2.5. The compiler produces a proportionate 400-pixel-wide texture. `attacker` is nato/pact and controls menu Attack/Defense captions, not the strategic AI role.

Optional `side_titles` contains nato/pact RU/EN labels for another army. Without it, the example's USA/USSR captions apply. Menu artwork is separate from a Workshop cover.

## 2. battalions/*.yaml

Every file has `schema: 1` and `battalions: [...]`. Split forces among files if useful; battalion IDs remain unique campaign-wide.

```yaml
schema: 1
battalions:
- id: my_infantry
  side: pact
  definition:
    country: SOV
    name: My Infantry Battalion
    name_text: {ru: Мой пехотный батальон, en: My Infantry Battalion}
    organization: My Brigade
    organization_text: {ru: Моя бригада, en: My Brigade}
    strategic:
      type: mechanized
      battle_role: fighter
      visual: {unit: BTR_80_Naval_SOV}
      icon: apc
    companies:
    - id: rifle
      name: Rifle Company
      name_text: {ru: Стрелковая рота, en: Rifle Company}
      hq: false
      platoons:
      - id: first
        name: First Platoon
        name_text: {ru: Первый взвод, en: First Platoon}
        hq: false
        units:
        - type: cr_Naval_Rifle_SOV_465cec9510
          count: 3
```

This is a minimal roster, not a complete playable force: place it through one arrival mechanism and provide real command/support units for a combat battalion.

Required: battalion id/side/definition; definition country, name, organization, strategic, companies. Optional: name_text, organization_text, formation, initial_state. Names are short OOB strings; localized versions are recommended.

Older `definition: {catalog: ...}` needs an authored profile.battalion_catalog entry. New campaigns should use full country-based definitions. Do not combine country and catalog.

### strategic

| Field | Values |
| --- | --- |
| `type` | mechanized, helicopter, airplane |
| `battle_role` | fighter, ground_support, auxiliary_support, air_support |
| `visual` | `{unit: tactical_ID}` from units.csv; appearance does not inherit roster/gameplay |
| `icon` | Optional for ground/helicopter: Infantry, apc, ifv, Armor, Armor_heavy, HQ, reco, AA, AT, hel, howitzer, mlrs, assault. Omit for airplanes; aircraft_role selects the icon |
| `aircraft_role` | Required for airplane only: fighter, bomber, sead |
| `support` | Optional `{kind: air_defence/artillery, radius_ap: number}` |

Airplane requires air_support; its icon follows aircraft_role. Fighter rosters need registered fighters, bomber accepts bombers/AT aircraft, SEAD needs SEAD tags; aircraft packs have no transport.

Artillery support requires mechanized/ground_support; AA requires mechanized/auxiliary_support. Radius is finite, >0 and ≤1000 in strategic AP scale, not kilometers. Native deployment/use remains an engine action, not guaranteed merely by this declaration.

Legacy appearance presets: west_german_infantry, east_german_infantry, west_german_armor, east_german_armor, soviet_armor (ground), us_helicopter (helicopter). Prefer explicit unit appearances for new work.

### formation and initial_state

```yaml
formation:
  division_id: my_brigade
  division_text: {ru: Моя бригада, en: My Brigade}
  regiment_id: my_regiment
  emblem: Texture_Division_Emblem_AGF_SOV_810
initial_state: {fatigue: 0, action_points: 12}
```

Formation requires division_id, division_text and regiment_id; emblem is optional. Matching division IDs within a side share formation metadata; keep name/emblem consistent. Custom tokens are declared in emblems.yaml; stock tokens must exist in installed WARNO.

Initial state contains at least one of fatigue 0–8 and action_points 0–12. Ground defaults are fatigue 0 and 12 AP/12 recovery; aircraft receive 4/4. Ground definition AP changes recovery as well as normal capacity: do not use zero for a temporary lock. Use deployment.frozen_turns. Artillery can use 5 and static AA 4.

### companies / platoons / units

Company requires id, name, boolean hq and nonempty platoons; optional name_text. Company IDs are unique within the battalion. Platoon requires id, name, boolean hq and nonempty units; optional name_text; IDs unique within the company.

The HQ flag describes structure; it does not convert ordinary infantry into commanders. Add genuine command cards/vehicles. Supply, AA, AT and engineers can be separate platoons in headquarters. A FOB is a normal pack entry, not a special `fob` key.

Each roster element is exactly `{type: pack_ID, count: integer_1…100}`. Type is a pack ID, not a tactical unit ID. Actual quantities also depend on pack.number: with number 1, count 3 yields three identical roster entries; number 2 puts two units in each entry.

## 3. packs.yaml

Optional root: `schema: 1`, `packs: [...]`. Creates tactical unit/transport/experience combinations absent from stock strategic packs.

```yaml
packs:
- id: my_marines_btr60
  unit: Naval_Rifle_SOV
  transport: BTR_60_Naval_SOV
  experience: 1
  number: 1
```

Every displayed field is required. ID is unique `[A-Za-z0-9_]+`, without duplicating a stock pack. Unit is the tactical ID from units.csv, without Descriptor_Unit_. Transport is a registered transport ID or null. Experience is integer 0–3; number is integer 1–10.

Use `type: my_marines_btr60` in platoons. Updating a shared pack affects every referencing platoon. Create another ID for a different transport/experience. Existence and transport classification are checked, not historical accuracy or balance. This file cannot change tactical armor, weapon stats, speed or cost.

## 4. map.yaml

Root requires schema 1, influence_sources, flags and labels. Optional waypoints, markers, strategic_grid. These are strategic positions/rules; visible scenery belongs in world.yaml.

### flags and influence

Flag fields, all required: id, position, initial_owner (nato/pact/null), capture_score and hold_score (integers ≥0), name RU/EN. Flags list is nonempty. IDs are referenced by victory, routes, events, reserve conditions and camera. A flag is not a separate geographic label; add a label for a place that should remain named.

Influence entries are exactly `{side,position,value}` with value numeric ≥0. The list is nonempty. They establish initial territorial control/frontline; value is not an AP radius or victory score. A flag's nearest initial source must agree with declared ownership; ambiguous nearest sources are rejected. Moving a flag behind another side's front requires a corresponding influence change.

### labels, markers and waypoints

| Section | Required fields |
| --- | --- |
| labels | id, position, text RU/EN, size large/medium/small |
| markers | id, position, name string; creates a small label with the same RU/EN text |
| waypoints | id, position; invisible route target |

Waypoint IDs do not duplicate flags/other waypoints. Labels and production points are not automatically AI targets: declare a flag or waypoint. Capture remains governed by native strategic influence, not the mere presence of an isolated unit nearby.

### strategic_grid

Requires dimensions `{width,height}`, bounds and default_terrain. Optional cells; omitting cells creates a uniform grid. A present cells list must enumerate **every** cell exactly once, zero-indexed row/column.

Cell required: row, column. Optional terrain (default), road boolean (false), id matching `r<row>c<column>`. Terrain values: StrategicPlain, StrategicForest, StrategicSemiUrban, StrategicUrban, StrategicWater. No road on blocking water. There is no public StrategicMountain value; visual relief and strategic terrain are separate.

Grid terrain/road affect movement; a painted road on surface.png does not. Forest/urban cells do not generate trees/buildings. Configure both world appearance and strategic rules.

Kacha's native AP step is 13,000 game units. Cell center is `min_x + (column + 0.5) * cell_width`, likewise for y. Align dimensions, playable/grid bounds and profile when changing scale; these are not geographic longitude/latitude.

## 5. deployments.yaml

Root: schema 1, deployments list. Each entry requires id, battalion, side, position, fatigue, action_points, frozen_turns. Optional initial_losses.

```yaml
deployments:
- id: dep_sov_880
  battalion: sov_880
  side: pact
  position: [890500, 500500]
  fatigue: 2
  action_points: 11
  frozen_turns: 0
  initial_losses: {max_percent: 25}
```

ID identifies **deployment**, whereas battalion identifies **roster**. Side must match. Aircraft are not ground deployments. Fatigue is integer 0–8; current initial AP is a nonnegative integer (keep it within normal capacity). Frozen turns is a nonnegative integer of locked owner turns. On release, normal AP recovery resumes. Do not permanently zero definition capacity to lock a formation.

Loss forms:

- `{max_percent: 25}` bounds the destroyed fraction of roster slots, integer 0…99. It is not an exact percent of soldiers, unit value or displayed readiness; heterogeneous packs differ.
- `{budget: 40, random_range: 0}` uses nonnegative native casualty budget/spread, spread ≤ budget and int32-safe sum. Budget is not a percentage; zero spread does not fix randomly selected casualties.

Losses apply once at startup to this formation, not to every similarly named unit.

## 6. ai.yaml

Root: schema 1, orders list. Every starting deployment ID needs exactly one order, including defense/reserve/support.

```yaml
orders:
- unit: dep_usmc_1st_landing
  type: attack
  target: sevastopol
  start_turn: 1
  route: [kacha_crossroads, orlovka, belbek, inkerman, sevastopol]
```

Required: unit (deployment.id, not battalion.id), type, target (flag/waypoint ID), start_turn integer ≥1. Optional route defaults to `[target]`; keep timing inside campaign for useful execution.

Types: attack, counterattack, move_to; defend, hold, reserve, support, air_support. These are native mission intentions, not guaranteed attacks irrespective of force assessment.

Route has 1–11 distinct known targets, ends with target; a multi-point route is allowed only for attack/counterattack/move_to. Arriving reserves get their AI in the relevant arrival document, not this initial-order table.

## 7. campaign.ai_policy

**Additional 1.1.1 options:** `cooperate_by_side` is an optional `{nato: boolean, pact: boolean}` mapping that overrides `cooperate` only for the specified sides. `recapture_if_lost` maps a scripted side to an existing flag ID, for example `{nato: kacha_beach}`. It requires `refresh_each_turn: true` and cannot name a side in `native_controller_sides`. On the side's AI turns, eligible ground missions target the lost objective; normal plans resume after ownership is restored. It does not issue orders to human-controlled armies.

Required inside the optional block: attack_radius and cooperate. Retain a working policy while changing one coordinated option set at a time. Inspect actual missions in play; valid settings do not guarantee desired AI maneuvers.

| Field | Constraint / meaning |
| --- | --- |
| attack_radius | Integer 530–2120, native GRU combat-search radius, not cell count |
| cooperate | Boolean, permit nearby formations to participate |
| refresh_each_turn | Boolean, refresh per-turn phased missions |
| continuous_route | Boolean, requires refresh; retain remaining route positions together |
| retain_route_progress | Boolean, requires continuous; latch secured intermediate positions, final target remains live |
| aggressive_until | Side→turn mapping, each 1…turns; requires refresh. Agressif mission battle profile until cutoff, then Default |
| phase_orders | Battalion ID→ordered phase list |
| native_strategies | Side→attacker/defender, sets stock strategic roles |
| native_controller_sides | Unique nato/pact list; native control instead of private missions |
| scripted_exceptions | Unique battalion IDs belonging to those native sides, retain private orders |
| attack_radius_cells | Finite number >0 and ≤12, combat search |
| transit_radius_cells | Same range, selected intermediate transit positions |
| support_radius_cells | Same range, rear/support orders |
| waypoint_radius_cells | Same range, waypoint arrival tolerance |
| transit_waypoints | Unique non-flag waypoint IDs using transit radius |

The four cell radii are supplied **together**, require refresh and continuous routes, and use the installed native unit conversion. Transit waypoints require them. Legacy waypoint tolerance is 707 GRU. Agressif is mission-scoped; it does not globally force native battle acceptance.

Each phase requires from_turn, type, target; optional route. Turns strictly increase within a battalion and are inside campaign duration. Types/targets follow section 6. Native-controlled formations execute private missions only when listed as exceptions; other source orders can remain as author intent but are not private runtime missions.

## 8. production.yaml

Root: schema 1, deployment_points, divisions, groups lists. Every point must be used by a division, and every division by a group; remove unused declarations together.

### deployment_points

Required: id, side, position, name RU/EN. These are reserve placement locations, not capture objectives. Their generated small-label ID is `production_<id>`; avoid duplicating it manually.

### divisions

Required: id, side, name RU/EN, short_name RU/EN, nonempty deployment_points IDs. Optional required_flag names a flag controlled by that side. All points belong to the same side, ordered preferred frontline first/fallback rear last. The engine also checks territory/enemy proximity.

Required-flag control is a live deployment restriction, different from a latched early capture_deadline.

### groups

```yaml
groups:
- id: sov_turn4_885
  division: sov_810
  name: {ru: 885-й обмп кадра, en: 885th Cadre Naval Bn}
  turn: 4
  battalions: [sov_885]
  ai: {type: defend, target: sevastopol}
```

Required: id, division ID, name RU/EN, turn 1…turns and nonempty unique battalions. Members are fully authored, same side as division, not aircraft and not instantiated elsewhere. One card can provide several separate battalions. An ID containing a turn number is just a label: **turn** controls availability.

Optional:

- ai: `{type,target,route?}` common AI plan. If any group has ai, **every** group must have one.
- member_ai: battalion ID→individual plan, only members of this card; others use common ai.
- when: previous-decision conditions.

### when

```yaml
when:
- {event: nato_difficulty, choice: 0}
- {event: pact_difficulty, choice: 1}
```

A nonempty list of requirements, each exactly event and choice 0/1 (first/second option), with distinct event IDs. All are **AND**. The event must have two choices and a dated trigger no later than this consumer. The validator does not specify a separate numeric maximum list length. Repeated event IDs and cyclic dependencies are rejected. For OR, use separate groups/events and unique battalion definitions, even for exclusive alternatives. A decision used by production can have empty immediate effects because its availability is the consequence.

## 9. reinforcements.yaml

Required file, empty in Kacha: schema 1 and `reinforcements: []`. An automatic arrival requires id, battalion ID, side, turn, position, ai `{type,target,route?}`. It appears without a reserve-card selection. Add a separate notice for understandable presentation, but do not spawn it twice in that notice. Aircraft use aviation.

## 10. events.yaml

Root: schema 1, events list (empty allowed). Required: id, side, trigger, title RU/EN, text RU/EN, image, choices, effects. Optional layout, ai_choice.

```yaml
events:
- id: my_notice
  side: pact
  trigger: {turn: 7}
  title: {ru: Резервы прибыли, en: Reserves Have Arrived}
  text: {ru: Резервы готовы к бою., en: The reserves are ready for action.}
  image: pact_naval_infantry
  layout: text
  choices: []
  effects: []
```

Side is the recipient, independent of UI language. Image is a logical profile.event_images ID, not a PNG path; a simple notice permits null, a choice requires artwork. An event executes once.

### trigger forms

| Form | Meaning |
| --- | --- |
| `{turn: 4}` | Specified recipient-side turn |
| `{turn: 4, when: [...]}` | Turn and prior choices, same AND rules as production |
| `{flag: belbek, owner: nato}` | Flag controlled by specified side |
| `{capture: belbek}` | Capture by event's side |
| `{first_enemy_destroyed: true}` | First recorded enemy destruction for this side |
| `{capture_deadline: blocked}` | Latched early deployment prevention |
| `{turn: 9, capture_deadline: not_blocked}` | Cutoff reached without prevention |

Blocked can also be dated; not_blocked requires a turn at/after cutoff. Only these shapes are supported, not arbitrary combinations. When is available only with turn.

### effects

A notice has no choices and zero/more effects. A decision has exactly two choices and an **empty** common effects list.

| Effect | Exact fields / constraints |
| --- | --- |
| Ground spawn | spawn battalion ID, position, ai `{type,target,route?}`; same side as event |
| Delayed ground spawn | Above plus at_turn, later than the dated trigger and inside duration |
| Score | score integer −1000…1000 excluding 0, side nato/pact |
| Current AP | action_points 0…12, battalion ID from initial deployments |
| Casualties | casualties 1…1000, random_range 0…1000, initially deployed battalion ID; budget rather than percentage |

There is no arbitrary remove/end_game/camera/fatigue/unlock effect. Use aviation withdrawal, deployment locks and victory rules respectively. Unsupported behavior needs a framework capability, not an invented YAML key.

### choices and cards

Each choice requires label RU/EN and effects list. Layout defaults to text. For graphic_cards, both choices also require card with image logical ID, title RU/EN, text RU/EN. A card is invalid in text layout. Choice indices are 0 and 1; ai_choice optionally selects one, default 0.

Consequences can be immediate effects, aircraft availability or production/event when consumers. A completely empty decision with no consumer is rejected. The graphic event background is a paired composite; card.image names its left/right source images. Update both recipe and card references when changing artwork.

Kacha schedules difficulty at 1, SEAL at 2, Soviet air decision at 4. Moving a trigger does not automatically move production/aircraft/notices: change related dates together.

## 11. aviation.yaml

Optional root: schema 1, airfields and wings. Every airplane battalion must be bound exactly once.

Airfield requires id, side, country, position, name RU/EN. It provides an aviation parent/location, not an automatically captureable objective. Side/country visual base must be supported.

Wing requires battalion ID, airfield ID and available. Battalion is fully authored airplane/air_support and matches side. Optional initial_losses `{max_percent: integer_0…99}` and withdraw_turn integer inside campaign.

Availability is **either** `{turn: 3}` **or** `{event: sov_air_choice, choice: 1}`; decision side must match. Do not put aircraft in ground production/deployment/event.spawn. Withdrawal must be after a dated arrival, including a dated choice. Removal tracks the current tagged aircraft, not merely its creation handle. A withdrawal notice is separate and does not perform removal.

Arrival fatigue belongs in definition.initial_state. Kacha's Su-24/MiG-23 arrive at 12 with fatigue 7 and max_percent 50. F-14/SEAD withdraw at 15; Harriers have no withdrawal.

## 12. cinematics.yaml

Optional document requires schema 1, intro and endings. Optional layout, layout_version, start_camera, encirclement_flags, ending_flags.

Intro has both nato/pact, **exactly four slides each**. A slide requires title RU/EN, text RU/EN, image logical ID; optional voice_script RU/EN. Voice script is a narration draft, not audio generation/playback.

| Field | Rule |
| --- | --- |
| layout | If present, briefing |
| layout_version | 1 or 2; current separate picture/body arrangement uses 2 |
| start_camera.focus | Existing flag ID |
| start_camera.altitude | Finite 100,000–2,000,000 game units, not geographic height |
| start_camera.north_up | Optional camera orientation setting, true in Kacha |
| encirclement_flags | Nonempty distinct map-flag IDs; NATO control denotes encirclement |
| ending_flags | Optional `{city,landing,inland}` with three different existing flags; requires explicit encirclement_flags |

Ending flags make another geography configurable without Python changes. Defaults are city=sevastopol, landing=kacha_beach, inland=simferopol. The technical axis name `sevastopol` stays unchanged even for another city; displayed text is yours.

Every side needs all these slide variants:

| Axis | Required variants |
| --- | --- |
| result | victory, stagnation, defeat |
| sevastopol | taken, surrounded, held |
| invasion | lost, beachhead, breakthrough |

Each variant is a full slide object. At ending, three slides are selected. City is taken if NATO controls city, otherwise surrounded if it controls all encirclement_flags, otherwise held. Invasion is lost if PACT controls landing, otherwise breakthrough if NATO controls both landing/inland, otherwise beachhead. Result follows actual campaign termination. Narrative does not itself change victory conditions.

## 13. event-images.yaml

Required: schema `agf-event-images/v2`, namespace, images mapping. Optional composites, plain. Legacy v1 supports original images only. Namespace/logical IDs start with lowercase letters, then lowercase letters/digits/underscores, at most 48 characters.

```yaml
schema: agf-event-images/v2
namespace: my_campaign
images:
  choice_left: artwork/events/left.png
  choice_right: artwork/events/right.png
composites:
  my_choice:
    kind: two_cards
    cards: [choice_left, choice_right]
plain:
  fallback_choice: text_choice
```

Images map logical ID to relative PNG/WebP. Static RGB/RGBA, each axis 2–8192. Composite IDs are unique, kind two_cards, exactly two **source-image** IDs in left/right order; composites cannot reference other composites. Plain creates a service text_choice background; choose actual artwork for illustrated decisions.

The generated token is `AGF_EVT_<namespace>_<id>`, matching the same logical ID in profile.event_images. Events do not take raw picture paths. Helper check/build prepares these inputs automatically; cooking adds them to a private texture bank.

## 14. emblems.yaml

Optional root: schema 1, emblems list. Each entry is exactly token and image.

```yaml
emblems:
- token: Texture_Division_Emblem_AGF_MyBrigade
  image: artwork/emblems/my-brigade.png
```

Unique token matches `Texture_Division_Emblem_AGF_[A-Za-z0-9_]+`. Image is a confined PNG, at least 64×64 and no larger than 4,000,000 bytes. Square transparent source is recommended.

Assign the token in formation.emblem. A custom token without a declaration is rejected; stock emblems need an existing game token rather than your PNG. Strategic national/coalition flags are separate native resources. Kacha retains Wikimedia SVG/metadata provenance; a general department insignia is not a verified individual-unit crest.

## 15. localization.yaml

Optional root is exactly schema 1, source_language en, translations.

```yaml
schema: 1
source_language: en
translations:
  fr:
    Reserves Have Arrived: Les renforts sont arrivés
  de:
    Reserves Have Arrived: Verstärkung eingetroffen
```

An enabled language table must cover **all** used English source strings, not just this partial structural example. Keys are exact English strings, including punctuation/newlines. Values are translations. Changing English narrative/title/name requires updating the source-string key in every enabled language.

Tables use en, fr, de, es, pl, zh; RU comes directly from content. Native banks: DEV/US→en, RU→ru, FR→fr, GER→de, SPA→es, POL→pl, SC→zh: seven languages, eight banks.

The optional en table handles shared base names lacking explicit name_text. A wholly absent language uses English fallback; a partially enabled language missing a required string is rejected. Keep all example tables complete for full multilingual publication.

Targets are nonempty, at most 20,000 characters and contain no NUL. Preserve `%0`, `%1` etc. and coalition markup #US/#SOV. Translated OOB names separately fit 30 UTF-16 units; long event/introduction prose does not use that widget limit. Voice scripts are narration preparation, not required screen translations.

## 16. world.yaml

Required: schema `agf-world/v1`, id, map_name, bounds, render_cases, raster_axes, heightmap, surface, objects. Optional georeference.

| Field | Rule |
| --- | --- |
| id | Unique lowercase world ID |
| map_name | `[A-Za-z][A-Za-z0-9_]*`, matches profile.strategic_map.map_name |
| bounds | `[0,0,max_x,max_y]`, positive extents |
| render_cases | Positive integer width/height |
| raster_axes | columns_x_rows_y, columns map to x and rows to y |
| surface | `{file: relative_image}`; opaque RGB PNG/WebP |
| heightmap | File or inline sample grid, below |
| objects | Explicit list of buildings/trees, [] allowed |

Each render case spans **655,360** game units. World preparation requires max_x=655360×width and max_y=655360×height. Kacha is 2×2/1,310,720 full extent, with a smaller playable AP region. Each image axis is 2–8192 pixels.

### heightmap

File form: `{file: artwork/heightmap.png, max_altitude_lbu: 22.3255814}` with a 16-bit grayscale PNG, black low/white high. Inline form: samples rectangular grid ≥2×2 of values 0…1, resolution `[width,height]` with axes 2…8192, max_altitude_lbu. Do not combine file and samples.

1 LBU=215 game units. Maximum altitude must be >0 and **strictly below 5000/215**, keeping terrain under the strategic overlay. Kacha peaks near 4,800 native units. Amplifying raster mountain relief differs from lifting its absolute ceiling.

### objects

Every object requires id, asset, position, rotation_degrees, scale, ground_offset_lbu. IDs are unique; asset is a supported registered point scenery name from scenery.csv. Position is in bounds; rotation finite 0–360; scale finite >0; ground offset finite, normally 0. Engine terrain adaptation supplies ground height; do not add sampled terrain height again. Arbitrary native pattern/graph scenery is not exposed as a point object.

More objects can increase city/forest density; terrain names do not automatically create buildings/trees. Painted roads and road cells need consistent authoring.

### georeference

If present, requires crs EPSG:4326, bounds_wgs84 `[west,south,east,north]`, elevation_ceiling_m 1…10000, source_sha256 64 lowercase hex characters, raster_origin northwest for new north-up geography (legacy southwest remains readable without automatic migration). Longitude is −180…180, latitude −90…90, ordered nonempty bounds. This is provenance/geographic mapping; units/events still use game x/y.

GeoTIFF/OSM tools: geotiff-inspect, geotiff-crop, geodata-import. Run `-m warno_ag <command> --help` for arguments and see the geography recipe. Retain source-data license/attribution.

## 17. profile.yaml

**Optional `frozen_turn_refresh_delay`:** a number greater than zero and at most 1 second, requiring `registration: dynamic`. Kacha V20 uses `0.125`. It delays each locked owner-turn AP clear until after the native AP refresh while preserving the formation's positive capacity/recovery. Omitting it retains the previous lifecycle. It is separate from `deployments[].frozen_turns`; do not set permanent AP capacity to zero for a temporary lock.

The profile binds the public source to an inspected native adapter. Kacha includes it. Usually change identities, map geometry/name and image tokens; do not guess script IDs or replace hashes.

Required: schema 1, id, template, bounds, capacity, slots, script, battalion_catalog, event_images. Optional registration, strategic_map, frozen_turn_refresh_delay.

| Field | Meaning |
| --- | --- |
| id | Matches campaign.template |
| registration | dynamic for new work; legacy_slots uses bounded pre-existing slots |
| template | campaign_id, definition_sha256, details_sha256 identify the compatible parent |
| bounds | Full native extents, bounds-check every position |
| capacity | Nonnegative integer initial_per_side, flags, influence_sources, labels, runtime_positions; dynamic zeros are not object limits |
| slots | spawns nato/pact lists plus flags, influence_sources, labels, runtime_positions; dynamic uses empty lists |
| script | Inspected root/launch/startup_groups/strategic_kernel/turn_loop/campaign_content/score_victory/legacy_launch_presentations; retain compatible recipe |
| battalion_catalog | Empty for explicit country rosters; legacy entries use unit_export, authored, optionally country/side |
| event_images | Logical ID→AGF_EVT namespace token matching event-images.yaml |
| strategic_map | Geometry/native map contract |

### strategic_map

Requires id, map_name, dimensions width/height, render_cases width/height, bounds, default_terrain, and **either** tactical_policy **or** fixed_battleground. Optional playable_bounds.

IDs/map_name are native identifiers starting with a Latin letter. Dimensions/render cases are positive integers. Bounds match profile/world extents; dimensions match authored grid/playable region, not PNG pixels or render-case count. Playable bounds form a nested ordered region.

Use `tactical_policy: terrain_pool` for the allowed terrain-based tactical-map pool. For a single battlefield, use the alternative `fixed_battleground: actual_tactical_map_ID`, rather than tactical_policy. Do not invent a battlefield ID or confuse it with strategic map_name; the compiler validates tactical availability. This does not create a new tactical map.

## 18. Supporting files and format boundaries

ASSET_CREDITS.md contains artwork licenses/attribution and enters complete mods as AGF_ASSET_CREDITS.txt (≤256 KB). GEODATA.json records geographic provenance, not gameplay settings. Wikimedia originals/metadata accompany the real custom emblems. README describes the example. None replaces a gameplay YAML document.

The reference covers the current supported authoring surface. Arbitrary triggers, Python/Lua scripts, tactical-stat edits, custom directional road-edge graphs/costs and unknown YAML commands are not activated by adding a key. Those need an actual framework capability first. This boundary is distinct from ordinary campaign changes fully described above.
