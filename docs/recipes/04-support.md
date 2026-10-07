# 4. Command, supply, artillery and AA

[Recipe index](../RECIPES.md) · [Русская версия](04-support.ru.md) · [Rosters and packs](03-rosters.md)

## Basic procedure: add supply to a combat battalion

1. Export catalogs with `scripts/campaign.py catalog` if you have not already done so.
2. Find a suitable supply unit and its strategic pack in `units.csv` and `packs.csv`. Prefer `number: 1` when you want to count vehicles directly.
3. In the intended battalion, find its headquarters/support company and a suitable platoon.
4. Append a unit entry using that real pack ID and the desired count.
5. Check, build and inspect the resulting OOB in a fresh campaign.

```yaml
units:
- type: your_existing_supply_pack
  count: 10
```

Replace the placeholder with the catalog ID. This is an entry under a platoon, not a top-level supply setting. There is no `supply: 10` field.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/support-check-01
```

Supply vehicles affect the actual battle roster. Merely naming a platoon “Logistics” does not give it supply capability.

## Command and headquarters

A headquarters company/platoon has `hq: true`, but that flag describes its OOB structure. Add genuine command vehicles or command infantry packs so the formation has tactical command units. Copy a complete headquarters company as a structural starting point, then choose units for your side and deployment method.

To create a logistics company with a FOB and vehicles, add a real FOB pack with `count: 1` and a vehicle pack with `number: 1`, `count: 10`. Keep the platoon's required ID, names and `hq` field. A FOB is a unit entry; no `fob` object is created by a special company name.

For a helicopter force, select command/transport/supply combinations suitable for aviation and airlift. A strategic helicopter model does not convert ground commanders or trucks into helicopters. Use [custom packs](03-rosters.md#select-a-different-tactical-unit-or-transport) to define actual transport combinations.

## Basic procedure: make a dedicated artillery formation

In the battalion's existing `definition`, use a support role and real artillery roster. This fragment replaces its strategic/state settings:

```yaml
strategic:
  type: mechanized
  battle_role: ground_support
  visual: {unit: 2S1_Gvozdika_Naval_SOV}
  icon: howitzer
  support: {kind: artillery, radius_ap: 12}
initial_state:
  fatigue: 0
  action_points: 5
```

Select an appearance and artillery packs from your catalog; the illustrated appearance is not the roster itself. For an initially deployed formation, set its `deployments.yaml.action_points` consistently, such as 5. For a reserve formation, its definition supplies normal AP/recovery on arrival.

## Basic procedure: make a dedicated AA formation

Use the same ground `type`, but change its role, actual roster and support kind:

```yaml
strategic:
  type: mechanized
  battle_role: auxiliary_support
  visual: {unit: your_registered_aa_unit}
  icon: AA
  support: {kind: air_defence, radius_ap: 8}
initial_state:
  fatigue: 0
  action_points: 4
```

The visual placeholder must be replaced by a real tactical ID. `radius_ap` is a strategic grid/AP-scale radius, not meters or kilometers. Choose it in relation to map cells and positions rather than to the vehicle's tactical weapon range.

The generated AA formation receives the native anti-air deployment/fortification order. The game governs deployment and active coverage. Declaring support does not guarantee that its AI always deploys or uses it optimally; verify both player and AI behavior in play.

## Organic support versus strategic support

You can add AA teams, anti-tank weapons, mortars, engineers and supply inside a normal combat battalion's companies. Those are tactical roster contents. They do not turn every contained weapon into a separate strategic support circle.

Use an independent support formation with `strategic.support` when you want a dedicated strategic artillery/AA unit. Use headquarters platoons when you want organic units participating in the battalion's battle. These mechanisms can coexist in the same campaign.

Other reasonable variations include a mobile artillery group, static rear AA, a supply-heavy division headquarters, a reconnaissance support battalion, or a lightly equipped territorial formation. Select actual roster units and an appropriate strategic role; avoid using a support label to imply abilities that are not present.

## Settings and units

| Location | Values/limits | Meaning |
| --- | --- | --- |
| Company/platoon `hq` | Boolean | Headquarters structure, not automatic command ability |
| `units[].type` | Existing stock/custom pack | Actual command, supply, engineer or support unit |
| `units[].count` | Integer 1–100 | Entries of that pack; multiply by its `number` |
| Custom pack `number` | Integer 1–10 | Units per entry; 1 is easiest for exact vehicle totals |
| `strategic.type` for dedicated support | `mechanized` | Required for current artillery/AA support declarations |
| `strategic.battle_role` | Artillery: `ground_support`; AA: `auxiliary_support` | Native strategic battle function |
| `strategic.support.kind` | `artillery` or `air_defence` | Support behavior |
| `strategic.support.radius_ap` | Finite number >0 and ≤1000 | Strategic support/air-denial radius |
| `strategic.visual.unit` | Registered tactical ID | Map appearance |
| `strategic.icon` | Supported icon | Visual marker; artillery/AA support generation selects howitzer/AA |
| `definition.initial_state.action_points` | Integer 0–12 | Normal initial/recovery AP; use a positive value for active support |
| `definition.initial_state.fatigue` | Integer 0–8 | Arrival/definition fatigue |
| `deployments[].action_points`, `fatigue` | Initial current AP / 0–8 fatigue | Starting on-map state, separate from normal recovery |

`support` requires both `kind` and `radius_ap`. A ground fighter or helicopter cannot use the current dedicated artillery/AA support mapping. There is no additional public support deployment delay, tactical AA range override, support ammo multiplier or guarantee-of-use parameter.

## How the mechanism works

The framework compiles unit packs into the company's tactical roster. It separately compiles strategic role, movement, icons, tags and orders. For artillery, the support radius becomes native battle-support coverage; for AA it becomes native air-denial coverage and adds the deployment order. These properties are not derived automatically from the list of weapons in the roster.

Normal AP determines future recovery. A start deployment's current AP only sets its first state. [Readiness](08-readiness.md) explains this distinction and temporary locks. The actual game decides whether a formation can join a battle and how AI support is selected.

## Troubleshooting

No command units: inspect actual pack units, not `hq` labels. Wrong supply quantity: inspect `count × number`. No strategic circle: inspect role/support configuration and the unit's deployed state. Wrong appearance: change `visual` independently of the packs. Support cannot keep up: review AP, starting position and AI mission; a larger radius does not correct an unreachable or inappropriate position. A declaration passes checking but AI does not use it: investigate native behavior and [orders](10-objectives.md), rather than inventing a YAML force-use field.
