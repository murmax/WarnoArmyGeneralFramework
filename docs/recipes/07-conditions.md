# 7. Difficulty and conditional force variants

[Recipe index](../RECIPES.md) · [Русская версия](07-conditions.ru.md) · [Events](06-events.md) · [Reserves](05-reserves.md)

## Basic procedure: gate one reserve card on a decision

The supplied campaign already defines two-option decisions `nato_difficulty` and `pact_difficulty`. In your clone, choose an existing reserve group and add requirements under that group:

```yaml
when:
- {event: nato_difficulty, choice: 0}
- {event: pact_difficulty, choice: 1}
```

This card becomes eligible only when the first decision's **first** option and the second decision's **second** option have been selected. Every requirement must match. Preserve the group's own turn, battalions, division and AI plan.

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/condition-check-01
```

Use a new campaign to try each intended decision outcome. Text labels do not define the result: the position in `choices` defines index 0 or 1.

## Define a new difficulty decision

For another design, declare a normal dated two-choice event:

```yaml
- id: operation_difficulty
  side: nato
  trigger: {turn: 1}
  title: {ru: Сложность операции, en: Operation Difficulty}
  text: {ru: Выберите уровень сложности., en: Choose the difficulty level.}
  image: difficulty_cards
  layout: text
  ai_choice: 0
  effects: []
  choices:
  - label: {ru: Обычная, en: Normal}
    effects: []
  - label: {ru: Сложная, en: Hard}
    effects: []
```

Register `difficulty_cards` as explained in [artwork](11-artwork.md), then attach at least one actual production `when` consumer to this event. Empty immediate effects are allowed for a production-consuming decision. An otherwise consequence-free choice is not a useful accepted event.

The event's side chooses. The consumer's battalion side determines which forces are affected: a NATO decision can restrict PACT reserves through `when`, or vice versa. This does not change the country of those units.

`ai_choice: 0` makes the AI select the first option. This is a campaign author's chosen policy, not a hidden difficulty multiplier. For a different two-option gameplay choice the valid default is also 1, if intended.

## Replace one force variant with another

Create two independent battalion definitions and two cards:

```yaml
- id: armor_normal_card
  division: your_existing_division
  name: {ru: Бронегруппа, en: Armor Group}
  turn: 6
  battalions: [armor_normal]
  ai: {type: attack, target: your_existing_objective}
  when: [{event: operation_difficulty, choice: 0}]
- id: armor_hard_card
  division: your_existing_division
  name: {ru: Усиленная бронегруппа, en: Reinforced Armor Group}
  turn: 6
  battalions: [armor_hard]
  ai: {type: attack, target: your_existing_objective}
  when: [{event: operation_difficulty, choice: 1}]
```

Replace the division and target placeholders with declared IDs. `armor_normal` and `armor_hard` must be separate, same-side roster definitions. Edit their actual packs/counts to change forces. The names “Normal” and “Reinforced” have no mechanical effect.

You can also select fewer battalions, a later arrival, different equipment, or different member AI plans. Keep each possible battalion instance unique, including unchanged support members copied into alternative cards.

## Compose two decisions deliberately

When decisions A and B both matter, write the intended truth table first:

| A | B | Example group requirement |
| --- | --- | --- |
| 0 | 0 | A=0 AND B=0 |
| 0 | 1 | A=0 AND B=1 |
| 1 | 0 | A=1 AND B=0 |
| 1 | 1 | A=1 AND B=1, if this combination is part of the design |

Declare one or more independent groups for the cases you intend. A case with no matching group produces no reserve; there is no automatic fallback to the ordinary card. A case with several matching groups can provide all of them. Group conditions should be exclusive when the goal is replacement rather than addition.

There is no OR operator in `when`. To accept A=0 OR B=0, represent the intended nonoverlapping cases with independent groups and battalion definitions. The same event cannot appear twice in one requirement list, including contradictory requests for both of its options.

## Conditional notices and other consumers

A dated notice may add `when` inside its trigger:

```yaml
trigger:
  turn: 6
  when: [{event: operation_difficulty, choice: 1}]
```

This can explain the force variant without creating it a second time. The full notice still requires title, text, image, choices and effects. A choice-bound aircraft instead uses `available: {event: ..., choice: ...}` in aviation; it is a different availability form, not a `when` list.

## Parameters and restrictions

| Setting | Constraint |
| --- | --- |
| Decision `choices` | Exactly two ordered options; each needs localized label and effects list |
| Decision `ai_choice` | Integer 0/1; default 0 |
| Production group `when` | Nonempty list of exact `{event,choice}` mappings |
| Dated event `trigger.when` | Same requirement format, allowed only with `trigger.turn` |
| Requirement `event` | Existing two-choice event with a dated trigger |
| Requirement `choice` | Integer 0/1 |
| Requirement event IDs | Distinct within one list |
| Timing | Each source decision no later than its dated consumer |
| Dependencies | No cycles or self-dependencies |
| Battalions | Unique per appearance, even for mutually exclusive variants |

The current requirement validator specifies no separate numeric maximum list length; the meaningful limits are known dated decisions, distinct IDs and acyclic references. Do not treat an arbitrary large list as a recommendation: a small clear condition set is easier to review and play.

## How the mechanism works

When production or a later dated event consumes a decision, the compiler creates shared persistent decision state. A consumer first waits for its requirements to be resolved, then selects its matching branch. The branch that does not match performs no force effect. This distinguishes “not selected yet” from an actual first-option choice.

You do not edit native variables, sentinels, comparison enums or exported object IDs. The public settings are event IDs and choice indices. The ordinary public compiler supplies AI defaults and human presentation. Cooperative presentation remains experimental; an accepted single-player branch is not proof of network synchronization.

## Troubleshooting

If all reserve alternatives disappear, inspect both decisions and every requirement, then each group's eligibility turn. If both variants appear, inspect overlapping predicates. If a renamed option changes behavior, its order may have changed: preserve intended indices or update every consumer. If checking reports a preceding-decision error, date the source decision at/before the consumer. If copies share a battalion, clone the definitions rather than only renaming groups.
