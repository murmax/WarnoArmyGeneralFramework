# 5. Reserve cards and deployment points

[Recipe index](../RECIPES.md) · [Русская версия](05-reserves.ru.md) · [Conditions](07-conditions.md)

## Basic procedure: one new battalion on turn 6

In the cloned example:

1. Copy one complete ground battalion object, such as `sov_885`, under `battalions/`.
2. Give the copy the unique ID `my_reserve`, appropriate short names and its intended roster. Keep its `side: pact` for this example.
3. Do not also put this definition in deployments, automatic reinforcements, event spawns or aviation.
4. Append the following to the existing `production.yaml.groups` list. The example uses the existing division `sov_810` and its deployment points.
5. Translate the new card name, check, build, then reach turn 6 in a fresh campaign.

```yaml
- id: my_reserve_card
  division: sov_810
  name: {ru: Резервная группа, en: Reserve Group}
  turn: 6
  battalions: [my_reserve]
  ai: {type: defend, target: sevastopol}
```

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/reserve-check-01
```

This creates a scheduled reserve **card**, not an unconditional appearance at a coordinate. The human player deploys the card through permitted points; the AI uses its plan. `my_reserve` names a full battalion definition, not a company or pack.

## Several battalions in one card

Create separate definitions with unique battalion IDs and list them in the same group:

```yaml
battalions: [reserve_rifle_1, reserve_rifle_2, reserve_tanks]
ai: {type: attack, target: sevastopol}
member_ai:
  reserve_rifle_2: {type: defend, target: belbek}
```

The three definitions must exist and belong to the division's side. The common `ai` is the fallback plan; the listed member gets its own plan. The group does not merge their tactical OOBs into one battalion.

A battalion can be instantiated once. Even exclusive alternative cards need separate battalion definitions: do not reuse `reserve_tanks` in another group's list. See [conditional variants](07-conditions.md).

## Add a deployment point and reserve division

Append the point to `deployment_points`, the division to `divisions`, and a group using it to `groups`. These fragments belong to their existing lists:

```yaml
# deployment_points
- id: rear_depot
  side: pact
  position: [877500, 331500]
  name: {ru: Тыловой пункт, en: Rear Depot}

# divisions
- id: rear_reserve
  side: pact
  name: {ru: Резерв армии, en: Army Reserve}
  short_name: {ru: Резерв, en: Reserve}
  deployment_points: [rear_depot]

# groups
- id: rear_reserve_turn6
  division: rear_reserve
  name: {ru: Пехотный резерв, en: Infantry Reserve}
  turn: 6
  battalions: [my_reserve]
  ai: {type: defend, target: sevastopol}
```

Adapt the position to friendly, reachable terrain. Remove the earlier sample group if using this alternative: `my_reserve` cannot be listed in both. Keep the document root `schema: 1` and the three required list keys.

Every declared point must be used by a division and every declared division by a group. Remove obsolete references and unused declarations together. A point receives an automatic small label; do not also add the same generated `production_rear_depot` label ID manually.

## Priority and territorial restrictions

Give a division several same-side points in priority order, preferred forward location first and safe rear fallback last:

```yaml
deployment_points: [forward_depot, rear_depot]
required_flag: belbek
```

Both points must be declared. `required_flag` is optional; if present, it must be a declared map flag. Its control by the reserve side is a **live** restriction: losing it prevents deployment while it is lost. The game also considers territory and nearby enemies. A fallback must actually be a safe position; a list order is not a guarantee of usable supply or clear ground.

For permanent prevention after an early enemy capture, use `campaign.yaml.capture_deadline` instead. It specifies flag, captor, cutoff and division; groups of that division cannot arrive before the cutoff. [Schedule](02-schedule.md) and [objectives](10-objectives.md) explain the full dependency.

## Parameters

| Section | Fields and limits |
| --- | --- |
| Root | Exactly `schema: 1`, `deployment_points`, `divisions`, `groups`, all lists |
| Point | Unique `id`, `side`, `[x,y] position` in profile bounds, nonempty RU/EN `name` |
| Division | Unique `id`, `side`, RU/EN `name`, RU/EN `short_name`, nonempty distinct `deployment_points` |
| Division option | `required_flag`: known map flag ID |
| Group | Unique `id`, known `division`, RU/EN `name`, integer `turn` 1…campaign duration, nonempty distinct `battalions` |
| Group option `ai` | `type`, known `target`, optional `route`; [mission values](10-objectives.md#mission-settings) |
| Group option `member_ai` | Nonempty battalion-ID→plan mapping; only members of that group |
| Group option `when` | Nonempty previous-decision requirements with distinct event IDs; all AND; [conditions](07-conditions.md) |

Points, divisions and groups each have their own ID namespace. Their IDs are not roster formation IDs: the production division schedules cards and places them, while `definition.formation` labels OOB subordination. They may represent the same real formation but are separate declarations.

All group members must be ground/helicopter authored battalions of the division's side. Aircraft cannot use ground production. If any production group has an `ai` plan, every group must have one; a partial conversion of a production table is invalid. `member_ai` refines the common plan rather than replacing that requirement.

The accepted schema does not expose card prices, production income, repeatable factories, custom resource currencies or an arbitrary choice of every map coordinate. Use the declared reserve schedule and points.

## How the mechanism works

The compiler creates native reserve divisions, permitted spawn locations and scheduled groups. A group becomes eligible when its turn and decision conditions are satisfied. For a human, it is added to the reserve interface. AI-directed production creates its distinct formations at eligible points and starts their common/member orders. These are independent from informational events.

Definition initial state supplies arrival fatigue and normal AP. There is no production-specific `fatigue` or `action_points` override; edit the unique battalion definition. A notice can announce the card, but must not spawn the same battalion again.

## Troubleshooting

| Symptom | Inspect |
| --- | --- |
| Missing reserve card | Turn, decision resolution, full `when` list, division restrictions |
| Card exists but cannot deploy | Friendly control, required flag, enemy proximity and declared points |
| Duplicate-use error | Battalion referenced by another card or arrival mechanism |
| Unused point/division error | Remove unused declarations or add the missing references |
| AI formation gets the wrong route | Common `ai`, member override, and later battalion phase orders |
| Empty card or missing member | Full battalion definitions and their side; names alone do not define forces |

Check the human reserve UI and the AI side separately in a new campaign. Source validation establishes a coherent schedule, not automatic runtime acceptance of every placement.
