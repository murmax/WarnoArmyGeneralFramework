# 6. Automatic arrivals and event effects

[Recipe index](../RECIPES.md) · [Русская версия](06-events.ru.md) · [Reserve cards](05-reserves.md)

## Basic procedure: an automatic ground arrival

Use this when the formation should appear at a fixed position without the player selecting a reserve card.

1. Create a unique ground battalion definition named `my_auto_reserve`, as described in [rosters](03-rosters.md).
2. Append an arrival to `reinforcements.yaml.reinforcements`.
3. Choose a friendly, reachable position and an existing flag/waypoint target.
4. Check, build, and reach the arrival turn in a new campaign.

```yaml
schema: 1
reinforcements:
- id: arrival_my_reserve
  battalion: my_auto_reserve
  side: pact
  turn: 6
  position: [877500, 331500]
  ai: {type: defend, target: sevastopol}
```

If the file already has entries, append to its list rather than replacing it with the whole example. Adapt IDs/position to your campaign. Do not also deploy or offer this battalion through another appearance mechanism.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/event-check-01
```

## Tell the player what happened

Append an ordinary notice to `events.yaml.events`:

```yaml
- id: reserve_arrival_notice
  side: pact
  trigger: {turn: 6}
  title: {ru: Резервы прибыли, en: Reserves Have Arrived}
  text: {ru: Пехотный резерв прибыл в тыловой район., en: Infantry reserves have reached the rear area.}
  image: null
  choices: []
  effects: []
```

The automatic reinforcement and notice are separate one-shot actions. Leave `effects` empty in this notice, because the arrival already creates the formation. Adding another spawn of the same battalion is a duplicate. Update translations for both new strings.

`side` is the event recipient; it does not select a language. A `pact` notice can be displayed in English. A normal notice permits `image: null`; illustrated decisions need registered artwork.

## Spawn a formation after a decision

For an immediate choice consequence, use a unique battalion and put this effect **inside that choice's `effects` list**:

```yaml
effects:
- spawn: my_event_reserve
  position: [877500, 331500]
  ai: {type: defend, target: sevastopol}
```

The event and battalion must have the same side. The battalion must not already be deployed, in production or in another arrival. Aircraft instead use [aviation availability](09-aviation.md).

For a delayed arrival selected on turn 3 and executed on turn 6, the event needs `trigger: {turn: 3}` and its spawn effect adds:

```yaml
at_turn: 6
```

This field belongs in the spawn mapping beside `spawn`, `position`, `ai`. It is supported only when the event has a dated trigger, and its turn must be later than that trigger and within campaign duration.

For two alternative landing sites, define two separate battalions and place one in each choice. Similar composition does not permit reuse of the same native battalion descriptor.

## Two-option decision structure

```yaml
- id: reserve_direction
  side: pact
  trigger: {turn: 3}
  title: {ru: Направление резерва, en: Reserve Direction}
  text: {ru: Выберите задачу резерва., en: Choose the reserve mission.}
  image: reserve_choice
  layout: text
  ai_choice: 0
  effects: []
  choices:
  - label: {ru: Удержать порт, en: Hold the Port}
    effects:
    - spawn: port_reserve
      position: [877500, 331500]
      ai: {type: defend, target: sevastopol}
  - label: {ru: Усилить аэродром, en: Reinforce the Airfield}
    effects:
    - spawn: airfield_reserve
      position: [877500, 487500]
      ai: {type: defend, target: belbek}
```

Declare both unique battalions and register logical artwork ID `reserve_choice` before using this complete example. [Artwork](11-artwork.md) explains image registration. The two choices are indices 0 and 1; `ai_choice: 0` selects the first for the AI. Exactly two choices are supported. Common event `effects` must be empty when choices exist.

For illustrated cards, use `layout: graphic_cards`, a paired composite event image, and a `card` with `image`, RU/EN `title`, RU/EN `text` in each choice. Do not put a `card` into `layout: text`.

## Trigger settings

Only the following forms are supported:

| `trigger` | Meaning and limits |
| --- | --- |
| `{turn: 6}` | Once on the recipient's specified turn, 1…campaign duration |
| `{turn: 6, when: [...]}` | Dated event additionally requiring earlier decisions; [conditions](07-conditions.md) |
| `{flag: belbek, owner: nato}` | Once when that flag is controlled by the specified side |
| `{capture: belbek}` | Once after capture by the event's recipient side |
| `{first_enemy_destroyed: true}` | First recorded enemy destruction for the side, not an arbitrary unit-type predicate |
| `{capture_deadline: blocked}` | Report the permanent early-capture prevention latch |
| `{turn: 9, capture_deadline: not_blocked}` | Report no prevention at/after the configured cutoff |

`blocked` can also be dated. Deadline triggers require `campaign.capture_deadline`; `not_blocked` requires a turn at/after its cutoff. `when` is permitted only with `turn`. Do not combine these forms into an arbitrary condition expression.

## Effect settings

| Effect | Exact supported fields | Limits |
| --- | --- | --- |
| Spawn | `spawn`, `position`, `ai`, optional `at_turn` | Unique same-side ground battalion; position in profile bounds |
| Score | `score`, `side` | Integer −1000…1000 excluding zero; side `nato`/`pact` |
| Current AP | `action_points`, `battalion` | Integer 0–12; initially deployed battalion |
| Casualties | `casualties`, `random_range`, `battalion` | Casualties integer 1–1000; spread 0–1000; initially deployed battalion |

Score target side can differ from the recipient. Casualties are native loss budget/spread, not a percentage of troops. Changing current AP does not change normal recovery/capacity. There are no public general-purpose `remove`, `end_game`, `camera`, `fatigue`, `unlock` or free-form script effects. Use the respective aircraft withdrawal, victory and lock mechanisms.

## How the mechanism works

The compiler creates native event conditions, presentation descriptors and effect dispatch. Human decisions store the selected index; AI uses the declared default. Immediate spawn consequences follow the event decision; a deferred spawn installs a later turn condition. Production and aircraft can consume a choice through their own availability declarations without immediate event effects.

The presentation title/text are localization entries, not executable instructions. Saying “reinforcements arrive” does not create them. An empty notice is valid; a decision with empty consequences is valid only if an actual supported consumer uses its outcome. [Conditional variants](07-conditions.md) describes persistent decision use.

Cooperative event synchronization is experimental. Verify that every participant receives and completes presentations before describing a campaign as cooperative-ready.

## Troubleshooting

Wrong recipient: inspect `side`, not UI language. Missing image: use a registered logical ID, not a file path. No arrival: inspect the actual effect or reinforcement record, unique battalion and trigger. Duplicate-use error: separate definitions for alternative spawns. Deferred effect rejected: put `at_turn` on a spawn of a dated event and choose a later turn. Outcome text without force changes: add the appropriate consumer. A new event absent from a saved campaign requires a fresh start after rebuilding.
