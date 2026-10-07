# 8. Initial state, losses and temporary locks

[Recipe index](../RECIPES.md) · [Русская версия](08-readiness.ru.md) · [Support AP](04-support.md)

## Basic procedure: lock a starting formation for two turns

1. Find its entry in `deployments.yaml` by deployment ID or battalion reference.
2. Change `frozen_turns` to 2.
3. Keep a positive normal AP value in that battalion's `definition.initial_state`, such as 10.
4. Keep the starting deployment's AP consistent with that capacity.
5. Check, build, then start a new campaign and reach the release turn.

```yaml
# Inside the battalion's definition
initial_state: {fatigue: 0, action_points: 10}
```

```yaml
# Replace fields inside its existing deployment
fatigue: 0
action_points: 10
frozen_turns: 2
```

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/readiness-check-01
```

The lock uses owner turns: 2 locks the first two, with release at owner turn 3. It is not a two-hour timer. Do not set the formation's permanent normal AP to zero to simulate this lock.

## Three different state settings

| Setting | Meaning |
| --- | --- |
| `definition.initial_state.action_points` | Normal initial/recovery AP for a ground/helicopter formation |
| `deployments[].action_points` | Current AP at its initial on-map placement |
| `deployments[].frozen_turns` | Temporary movement/action lock with native countdown and release |

For a support formation with a normal 5 AP, use definition AP 5. Giving a deployment 5 current AP while leaving definition at 12 is only an initial state change. Later recovery follows the definition. Aircraft use the native 4/4 initial/recovery policy independently of an AP override in this definition block.

Deployment fatigue overrides the starting state of initially placed ground formations. For reserves and aircraft arrival, edit their unique battalion definition's `initial_state.fatigue` instead.

## Start with a depleted or fatigued battalion

Fatigue is **0 fresh through 8 exhausted**. Higher values mean worse condition, not better morale. For an initially deployed part, set `fatigue: 2` in deployments. For a reserve, set it under the battalion definition.

Add bounded losses to an existing ground deployment:

```yaml
initial_losses:
  max_percent: 25
```

This bounds losses using the authored roster, rather than setting an exact displayed strength percentage. You can combine losses, fatigue and a lock, but these remain independent mechanics. Do not infer that a 25% casualty limit produces a precise 75% readiness bar for every heterogeneous OOB.

For native loss-budget control use the alternative form:

```yaml
initial_losses:
  budget: 40
  random_range: 0
```

Use one form, not both. Budget/spread are not percentages. A zero spread fixes the budget spread, not the random selection of which units are lost.

## Complete deployment entry

```yaml
- id: dep_my_infantry
  battalion: my_infantry
  side: pact
  position: [877500, 331500]
  fatigue: 2
  action_points: 10
  frozen_turns: 2
  initial_losses: {max_percent: 25}
```

Use a declared, unique ground battalion with matching side and positive normal AP. Add exactly one starting order in `ai.yaml` referencing `dep_my_infantry`, not `my_infantry`. For example `type: defend`, target an existing friendly objective, `start_turn: 1`. Starting orders do not remove the lock.

## Parameters

| Location | Accepted values |
| --- | --- |
| Deployment root | `schema: 1`, `deployments` list |
| Deployment required fields | Unique `id`, known `battalion`, matching `side`, in-bounds `position`, `fatigue`, `action_points`, `frozen_turns` |
| Deployment `fatigue` | Integer 0–8 |
| Deployment `action_points` | Nonnegative integer; keep it within the intended normal capacity |
| Deployment `frozen_turns` | Nonnegative integer; 0 means unlocked |
| Definition `initial_state` | Optional nonempty mapping with `fatigue` and/or `action_points` |
| Definition fatigue | Integer 0–8; normal default 0 |
| Definition AP | Integer 0–12; ground normal default 12, aircraft generated as 4 |
| Deployment losses `max_percent` | Integer 0–99; requires an explicit authored roster |
| Deployment losses `budget` | Nonnegative native integer |
| Deployment losses `random_range` | Nonnegative integer ≤budget; budget+spread ≤2³¹−1 |
| Aircraft arrival losses | `aviation.wings[].initial_losses.max_percent`, integer 0–99 |

There is no public upper `frozen_turns` limit tied to duration. For a temporary lock, choose a value that releases before the campaign ends; otherwise the formation will remain locked throughout play. Loss forms are optional; omitting them means no authored initial casualties.

## How the mechanism works

Normal AP/recovery is compiled into the unit's state modules. Initial deployment state is applied separately. A nonzero lock creates native frozen state and a countdown/action chain that prevents early action and releases according to owner-turn progression while preserving normal recovery.

Initial losses are applied once at startup. Aircraft loss limits are applied once after their arrival. A loss budget consumes roster slots with their native costs; it is not an exact percentage of soldiers, armor value or the visual OOB bar. Later [event effects](06-events.md) can alter current AP or apply casualty budget to initially deployed battalions, but do not offer a general fatigue or unlock command.

## Troubleshooting

Permanent 0/0 AP: inspect definition capacity/recovery; use positive normal AP and the lock field. Wrong first-turn AP: inspect both definition and deployment. A reserve arrives fresh despite intended exhaustion: set definition fatigue, not an unrelated deployment. Unexpected loss percentage: distinguish bounded percent, native budget and visual readiness. A change absent in a saved session: start a new campaign; existing serialized unit state is not automatically repaired by edited YAML.
