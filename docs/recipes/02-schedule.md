# 2. Duration, dates and schedules

[Recipe index](../RECIPES.md) · [Русская версия](02-schedule.ru.md)

## Basic procedure: extend the campaign

1. In `campaign.yaml`, change `turns`, for example from `20` to `24`.
2. Retain existing arrival turns if their original timing is still intended.
3. Review the deadline result in `victory.time_limit` and text describing the operation's time window.
4. Check the source with a new output directory, then build a complete mod and start a fresh campaign.

```yaml
turns: 24
```

```powershell
./.venv/Scripts/python.exe -B scripts/campaign.py check campaigns/my-campaign --game $game --output artifacts/schedule-check-01
```

Extending the limit does not move reserves, aircraft, decisions or AI phase changes. Shortening it may put existing schedules outside the permitted range and cause validation to fail.

## Basic procedure: move one reserve arrival

Find its group in `production.yaml.groups` and edit the actual `turn`:

```yaml
turn: 6
```

The digits in its `id` are only part of an identifier. Renaming a group to `turn_6` without changing `turn` does not change the schedule.

If an event announces that arrival, change `events.yaml.trigger.turn` and its wording too. If the group depends on `when`, its decisions must occur no later than its arrival. An early-capture rule may impose a later minimum turn.

## Build a coordinated timetable

Before a large timing change, write a small table listing decisions, arrivals, withdrawals and changes of orders. For each row record its source file and dependencies. A useful order is: initial forces → decision → conditional reserve → new AI phase → withdrawal → final deadline.

You can schedule several independent reserve cards on one turn, put several battalions in one arrival card, delay an automatic ground arrival, change aviation timing, or redirect a formation on a later turn. Each uses a separate field; none is inferred from narrative text.

## All timing controls

| File and path | Accepted value | Meaning |
| --- | --- | --- |
| `campaign.yaml.turns` | Integer ≥2 | Campaign turn limit |
| `campaign.yaml.date` | Four integers `[year,month,day,period]` | Starting native calendar/time-period value |
| `campaign.yaml.victory.time_limit` | `draw`, `nato`, `pact` | Deadline outcome when this victory policy is declared |
| `campaign.yaml.capture_deadline.before_turn` | Integer 2…`turns` | Early capture cutoff for a specified reserve division |
| `production.yaml.groups[].turn` | Integer 1…`turns` | Turn when a reserve card becomes eligible |
| `reinforcements.yaml.reinforcements[].turn` | Integer 1…`turns` | Automatic ground appearance |
| `events.yaml.events[].trigger.turn` | Integer 1…`turns` | Recipient-side turn for a dated event |
| Event spawn `at_turn` | Integer later than its dated trigger, ≤`turns` | Deferred ground effect selected by the event |
| `aviation.yaml.wings[].available.turn` | Integer 1…`turns` | Dated aircraft arrival |
| Wing `available: {event,choice}` | Decision reference and index 0/1 | Arrival after that decision; not a separate turn field |
| Wing `withdraw_turn` | Integer within duration and after dated arrival | Remove this aircraft formation |
| `ai.yaml.orders[].start_turn` | Integer ≥1 | Starting deployment's mission start; use an in-campaign turn |
| `campaign.yaml.ai_policy.phase_orders.<battalion>[].from_turn` | Strictly increasing integers 1…`turns` | Changes to that battalion's mission plan |
| `campaign.yaml.ai_policy.aggressive_until.<side>` | Integer 1…`turns`, with refreshed missions | End of a mission-level aggressive battle profile window |
| `deployments.yaml.deployments[].frozen_turns` | Nonnegative integer | Locked owner turns; [state guide](08-readiness.md) |

The `date` field's fourth number is a native period, not an hour such as `16`. The supplied example uses period `2` for noon. The authoring format does not provide a separate hours-per-turn or custom daily-period table. Date shape checking accepts four integers; choose a real calendar date and retain a known period from the template. Do not assume a calendar validation error will catch an impossible date.

## Dependencies that restrict timing

**Previous decisions.** A `when` consumer needs dated, two-option decision events at or before its own turn. It waits for resolved decisions; conditions do not provide an independent timer. See [conditional variants](07-conditions.md).

**Early capture.** A division named in `capture_deadline` cannot have arrival groups before `before_turn`. The rule permanently latches early prevention. Moving the group earlier without moving the cutoff and relevant notices violates this relationship. A `not_blocked` notice must occur at or after the cutoff.

**Withdrawal.** `withdraw_turn` needs a known earlier arrival. For a choice-bound wing, the choice itself must have a dated trigger. An undated capture decision cannot define a valid fixed withdrawal schedule.

**Deferred ground effects.** `at_turn` is supported only on spawn effects of dated events and must be later than the trigger. It is not a universal delay key for score, losses, AP or aircraft.

**AI phases.** Entries are ordered by increasing `from_turn`; their targets and routes still need declared flags/waypoints. Date changes do not create routes. [Objective and AI guide](10-objectives.md) explains phase behavior.

## How the mechanism works

The compiler creates native turn conditions, decision-state conditions and one-shot action chains. An arrival group, notice and aircraft wing are separate native actions even if you give them similar names or text. Their triggers run according to their own fields. A notice saying “tomorrow” does not schedule a reserve.

Turn numbers identify the native strategic turn state. A side-specific event also checks whose turn it is. Treat `frozen_turns` as owner-turn locking rather than elapsed wall-clock time. Use the example's dates/periods as a starting point and inspect the built game's calendar before writing exact hour promises.

## Common problems

| Problem | Correction |
| --- | --- |
| Shorter campaign fails checking | Review every dated arrival, effect, phase and withdrawal against `turns` |
| Arrival changed but notice stayed old | Edit the notice separately, including translations |
| Reserve unavailable on its planned turn | Check preceding decisions, flag restrictions and legal deployment points |
| Aircraft survives a withdrawal notice | Set `withdraw_turn` on every intended wing; text does not remove aircraft |
| An ID includes the desired turn but nothing moved | Edit the numeric `turn` field |
| Changed timing is absent in an old save | Use a new campaign; saves preserve existing native actions |

Before release, play through decision and arrival boundaries and the campaign deadline. Source validity alone does not demonstrate that the timetable produces the desired game balance.
