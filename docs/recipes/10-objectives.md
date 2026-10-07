# 10. Objectives, influence, routes and endings

[Recipe index](../RECIPES.md) · [Русская версия](10-objectives.ru.md) · [Map field reference](../YAML_REFERENCE.md#4-mapyaml)

## Basic procedure: move an existing objective

1. Find its `id` under `map.yaml.flags` and change `position`.
2. Check its declared `initial_owner` against nearby `influence_sources`. Move/add a friendly source if the new location belongs behind that side's initial front.
3. If its place-name label should move too, edit that separate `labels` entry.
4. Review initial deployments, reserve points and route waypoints nearby; none moves automatically with a flag.
5. Check/build and inspect ownership, approach routes and the label in a new campaign.

```yaml
position: [877500, 331500]
```

Positions are native game coordinates in the profile's full bounds, not longitude/latitude. Prefer reachable terrain inside the playable region. Use [the geography guide](13-geography.md) when converting geographic points.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/objective-check-01
```

## Add a geographic name or invisible route target

Flags and labels serve different purposes. A label keeps a settlement named even without an objective there:

```yaml
# Append under labels
- id: rear_town_label
  position: [1085500, 487500]
  text: {ru: Тыловой город, en: Rear Town}
  size: medium
```

A waypoint gives AI a target without a victory flag:

```yaml
# Append under waypoints
- id: rear_junction
  position: [1085500, 487500]
```

Declare each reference before using it. A label ID or production-point ID is not automatically a mission target: use a flag or waypoint. `markers` are another small-label convenience with `id`, `position`, `name` string; their names are copied to RU and EN, so use `labels` when translations are needed.

## Basic procedure: route one starting formation

In `ai.yaml.orders`, reference the **deployment ID**:

```yaml
- unit: dep_my_infantry
  type: attack
  target: sevastopol
  start_turn: 1
  route: [belbek, inkerman, sevastopol]
```

This example uses declared targets from the cloned map. Every initial deployment needs exactly one order. For reserves/arrivals put the AI plan in that arrival's own document. [Reserves](05-reserves.md) also support member-specific plans.

The final route element is the same as `target`. Intermediate positions are actual flags/waypoints, not text road names. Routes guide strategic missions; they do not paint roads or build a supply corridor.

## Mission settings

| Setting | Values / rule |
| --- | --- |
| Starting `orders[].unit` | Existing deployment ID |
| `type` | `attack`, `counterattack`, `move_to`, `defend`, `hold`, `reserve`, `support`, `air_support` |
| `target` | Known flag/waypoint ID |
| Starting `start_turn` | Integer ≥1; choose a useful in-campaign turn |
| `route` | Optional, defaults to `[target]`; initial/arrival plans accept 1–11 distinct targets, final one equals target |
| Multi-point route | For attack/counterattack/move_to; static plans use the single target |
| `ai_policy.phase_orders` | Battalion ID → ordered list of `from_turn`, `type`, `target`, optional `route` |

`attack` and `counterattack` express mission intentions; `move_to` gives movement intent. Static defend/hold/reserve/support/air_support plans keep the relevant position/role. Native force assessment, legal paths, AP, fatigue, control and supply can affect actual execution. No mission type guarantees an attack regardless of odds.

To change a battalion's plan later, add under `campaign.yaml.ai_policy.phase_orders`:

```yaml
my_infantry:
- from_turn: 8
  type: counterattack
  target: sevastopol
  route: [belbek, inkerman, sevastopol]
```

Use the battalion ID here, not its deployment ID. Entries for a battalion must have strictly increasing `from_turn` inside the campaign. Keep routes consistent with the declared targets and movement mission type. A phase is an override of its plan from that point, not a second battalion.

## General AI policy: every available setting

If `ai_policy` is present, `attack_radius` and `cooperate` are required. Start by retaining a working policy; change one coordinated group of settings at a time.

| Field under `ai_policy` | Range / prerequisites | Effect |
| --- | --- | --- |
| `attack_radius` | Integer 530–2120 | Legacy native GRU combat-search radius, not cells |
| `cooperate` | Boolean | Nearby formations can participate in missions |
| `refresh_each_turn` | Boolean | Refresh per-turn missions/phase plans |
| `continuous_route` | Boolean; requires refresh | Retain remaining route positions together |
| `retain_route_progress` | Boolean; requires continuous | Latch secured intermediate progress; final target remains live |
| `aggressive_until` | Side→turn 1…duration; requires refresh | Mission battle profile Agressif until cutoff, then Default |
| `phase_orders` | Known battalion IDs and ordered valid plans | Dated changes of mission intent |
| `native_strategies` | Side→`attacker`/`defender` | Native strategic controller roles |
| `native_controller_sides` | Distinct `nato`/`pact` list | Give those sides native rather than private mission control |
| `scripted_exceptions` | Distinct battalion IDs on those native sides | Keep private missions for selected formations |
| `attack_radius_cells` | Finite >0…12 | Search radius at normal/final objectives |
| `transit_radius_cells` | Finite >0…12 | Search radius at selected transit waypoints |
| `support_radius_cells` | Finite >0…12 | Radius for support/rear plans |
| `waypoint_radius_cells` | Finite >0…12 | Waypoint-arrival tolerance |
| `transit_waypoints` | Distinct known non-flag waypoint IDs; needs cell radii | Intermediate points using transit search radius |

Supply the **four** cell radii together, with both refresh and continuous route enabled. They use native AP cells and installed conversion data; they are not raster pixels or the logical authoring grid's cell count. Legacy waypoint tolerance is 707 GRU when that option set is absent.

`aggressive_until` modifies the scripted mission's battle profile, not every global native battle-acceptance rule. Native-controlled battalions receive private runtime missions only if listed as exceptions; their source orders can remain author intent without becoming private missions. `menu.attacker` changes menu labels independently of these roles.

## Ownership and victory settings

| Map/campaign field | Accepted value / meaning |
| --- | --- |
| Flag `id` | Unique technical objective ID |
| Flag `position` | In-bounds native `[x,y]` |
| Flag `initial_owner` | `nato`, `pact`, `null` |
| Flag `capture_score`, `hold_score` | Integers ≥0; capture and ongoing ownership scoring |
| Flag `name` | Nonempty RU/EN |
| Influence source | Exact `side`, `position`, numeric `value` ≥0 |
| Label `size` | `large`, `medium`, `small` |
| `campaign.score_to_win` | Positive integer; base score threshold |
| `victory.nato_capture`, `pact_capture` | Two distinct declared flags; capture by corresponding side ends the campaign |
| `victory.time_limit` | `draw`, `nato`, `pact` |
| `capture_deadline` | Exact `flag`, captor `owner`, cutoff `before_turn` 2…duration, production `division` |

A declared owned flag needs a compatible nearest initial influence source; conflicting/ambiguous ownership is rejected. Influence strength is not a victory score or an AP-circle radius. Merely reaching a flag with an isolated unit does not guarantee territorial control: native influence rules govern capture.

Live production `required_flag` and permanent early-capture prevention differ. The latter latches if the captor controls the specified objective before the cutoff; later recapture does not restore that division. Its groups need AI plans and cannot arrive earlier than the cutoff. [Reserve guide](05-reserves.md) covers deployment implications.

## Camera, introductions and endings

In `cinematics.yaml`, move camera focus by ID:

```yaml
start_camera:
  focus: sevastopol
  altitude: 900000
  north_up: true
```

Focus is a flag, altitude a finite native value 100000–2000000. Camera orientation does not rotate or georeference the map raster.

The file requires both sides' introductions, exactly four slides each, and all ending variants. Each slide has RU/EN `title`, `text`, logical `image`; optional RU/EN `voice_script` is a narration draft, not audio playback. Optional layout is `briefing`; `layout_version` is 1/2, with 2 separating picture/body presentation.

For another main city, bind real objectives explicitly:

```yaml
ending_flags: {city: main_city, landing: beachhead, inland: rear_hub}
encirclement_flags: [north_gate, south_gate]
```

Declare these as actual flags and use distinct city/landing/inland IDs. Explicit ending_flags requires explicit nonempty distinct encirclement_flags. Technical ending-axis keys remain:

| Axis | Required variants for each side |
| --- | --- |
| `result` | `victory`, `stagnation`, `defeat` |
| `sevastopol` | `taken`, `surrounded`, `held` |
| `invasion` | `lost`, `beachhead`, `breakthrough` |

At termination three slides are selected. City: NATO control → taken; otherwise all encirclement flags NATO-controlled → surrounded; otherwise held. Invasion: PACT control of landing → lost; otherwise NATO control of landing and inland → breakthrough; otherwise beachhead. Result follows actual termination. Text does not define victory. Defaults without explicit bindings use the example's `sevastopol`, `kacha_beach`, `simferopol`; configure bindings when changing geography.

## Mechanism and troubleshooting

The compiler creates separate native objective/influence descriptors, labels, route tags, AI missions, camera path and ending conditions. Shared IDs connect them but do not merge their purposes. Change a caption independently; when changing its technical flag ID, update every consumer, including events, reserves, victory, camera and endings.

For an inactive AI, first inspect unit state, starting/arrival plan, target coordinates and controller mode. For a wrong front, inspect influence, not only flag text. For a route targeting a label, add a waypoint. For a wrong ending, inspect objective bindings and ownership logic rather than only the slide prose. A map or mission change in an old save requires a new campaign for inspection.
