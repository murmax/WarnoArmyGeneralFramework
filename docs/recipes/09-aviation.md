# 9. Aircraft, airfields and withdrawal

[Recipe index](../RECIPES.md) · [Русская версия](09-aviation.ru.md) · [Rosters](03-rosters.md) · [Events](06-events.md)

## Basic procedure: change an aircraft arrival turn

1. In `aviation.yaml.wings`, find the wing by `battalion`.
2. Change `available.turn` to an in-campaign turn.
3. If it has `withdraw_turn`, keep withdrawal later than arrival.
4. Update any arrival notice and translations separately.
5. Check, build, and reach the date in a new campaign.

```yaml
available: {turn: 5}
```

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/aviation-check-01
```

Arrival date belongs to the wing record, while tactical aircraft belong to its battalion roster. Changing the aircraft's displayed name does neither.

## Create another aircraft formation

Copy a complete airplane battalion definition under a unique ID, for example `my_strike_wing`. Select real aircraft packs from the catalogs and set:

```yaml
strategic:
  type: airplane
  battle_role: air_support
  visual: {unit: your_registered_strike_aircraft}
  aircraft_role: bomber
initial_state: {fatigue: 0}
```

Replace the visual placeholder with a registered unit. This fragment goes inside `definition`; retain its country, names, organization and nonempty companies/platoons. Each aircraft pack has `transport: null`.

Bind it to an existing friendly airfield by appending to `wings`:

```yaml
- battalion: my_strike_wing
  airfield: your_existing_airfield
  available: {turn: 5}
```

Every airplane battalion must have exactly one aviation binding. It cannot simultaneously be in deployments, ground reserves, automatic ground reinforcements or event `spawn` effects.

## Choice-dependent aircraft

Use a same-side two-option event and availability:

```yaml
available: {event: air_support_choice, choice: 1}
```

The referenced decision must exist; index 1 is its second option. Use either turn availability or event/choice availability, not both in one mapping. For alternatives, define separate wings and battalion IDs. The event itself can have empty choice effects when its outcome is consumed by aviation.

When changing the option's aircraft, update actual packs, declared aircraft role, map appearance, names, formation/emblem, decision card picture and translated explanation as separate settings. They are not inferred from each other.

## Losses and fatigue on arrival

Give the wing a bounded casualty limit:

```yaml
initial_losses: {max_percent: 40}
```

Arrival fatigue belongs to its battalion `definition.initial_state`, for example `fatigue: 6`. Fatigue 0 is fresh, 8 is exhausted. Losses are roster-based bounded budget, not a command to set an exact displayed strength percentage. There is no wing-level `fatigue` field.

Airplane AP is generated as native 4 initial/4 recovery. A different value in `definition.initial_state.action_points` does not provide a public custom aircraft AP policy.

## Withdraw an aircraft formation

Add to every wing intended to leave:

```yaml
withdraw_turn: 15
```

It must follow a known dated arrival. For choice availability, the choice event must itself have a dated trigger. A notice saying aircraft leave is presentation only; the wing's `withdraw_turn` performs removal.

You can remove some wings while retaining others at the same airfield, such as withdrawing carrier fighters but retaining short-range strike aircraft. Do not remove the airfield to represent wing withdrawal. The current public format offers wing lifecycle removal, not arbitrary ground-unit removal or carrier damage simulation.

## Create or move an airfield

An airfield record requires all fields below:

```yaml
- id: rear_airbase
  side: pact
  country: SOV
  position: [1267500, 695500]
  name: {ru: Тыловой аэродром, en: Rear Airbase}
```

Use a supported country listed for that coalition and a point safely inside playable bounds. The current adapter permits one authored airfield per side; to replace a location, update the existing field and its wing bindings rather than add a second airport for the same side.

The airfield needs a one-native-cell neighborhood inside the playable area, so do not place its center directly on the border. A point within full profile bounds alone may still fail this requirement. Move a rear airfield away from a ground front if that better suits the operation.

An airfield is a native aviation building/parent, not an ordinary capture objective. Define a separate map flag and victory rule if a nearby location should control the campaign outcome. Naming the airfield “Objective” does not make it captureable.

## Complete parameter table

| Location | Accepted value / role |
| --- | --- |
| Root | `schema: 1`, `airfields` and `wings` lists |
| Airfield `id` | Unique lowercase identifier |
| Airfield `side` | `nato`/`pact` |
| Airfield `country` | Supported country belonging to that side |
| Airfield `position` | Native `[x,y]`, with one-cell playable neighborhood |
| Airfield `name` | Nonempty RU/EN |
| Wing `battalion` | Unique fully authored airplane battalion |
| Wing `airfield` | Existing field on the same side |
| Wing `available` | Exactly `{turn}` or `{event,choice}` |
| Arrival `turn` | Integer 1…campaign duration |
| Decision `choice` | Integer 0/1, valid same-side decision |
| `initial_losses` | Optional exact `{max_percent}`, integer 0–99 |
| `withdraw_turn` | Optional integer in duration, strictly after dated arrival |
| `strategic.aircraft_role` | `fighter`, `bomber`, `sead` |
| `strategic.battle_role` | `air_support` for airplanes |
| Aircraft `strategic.icon` | Do not supply it: generated from aircraft role |
| Aircraft pack transport | `null` |

Fighter rosters require registered fighter aircraft. Bomber roles accept bomber/anti-tank aircraft. SEAD needs aircraft bearing the appropriate SEAD tags. The check validates roster category/role, not just the visual model. A fighter renamed “SEAD” does not become a suppression unit.

The tags column in units.csv lets you identify these directly: fighter needs
`Avion_Chasseur`; bomber accepts `Avion_Bombardier` or `Avion_AT`; SEAD needs
`Avion_SEAD`. The unit category must also be airplane.

## How the mechanism works

The framework creates native airport descriptors and binds airplane battalions to their airport position. Dated wings receive turn-based creation; decision-bound wings receive choice-based creation. Initial casualties apply once after the formation is created.

Withdrawing formations carry a unique runtime tag. The lifecycle action finds surviving matching aircraft and removes that group, rather than trusting only its original creation handle. Game airfield mechanics and battle aircraft selection remain native behavior. `aircraft_role: sead` declares its role; it does not guarantee that an AI commander always selects it for every protected battle.

## Troubleshooting

Unbound aircraft: add a wing record. Wrong-side availability: match decision, battalion and field sides. Role failure: choose tagged aircraft packs and no transport. Border-airfield failure: move the whole one-cell neighborhood inside playable bounds. A wing stays after a notice: configure its own withdrawal field. Extra national/formation insignia: inspect country and `formation.emblem` separately. Changed wing data in an existing save needs a fresh campaign for reliable inspection.
