# Release 1.0.2

Refreshed strategic attack missions can select the stock Agressif battle-start
profile per coalition and turn. `aggressive_until: {nato: 9}` restores Default
from turn 10 and preserves Default for defensive/support missions and the
other coalition. This uses the native `StartBattleDescriptorType` field already
present in stock Fulda missions; global AI constants and the game executable
are not changed.

`retain_route_progress: true` remembers secured intermediate route positions
with private one-shot capture latches. Later recapture behind the front does
not reset an advancing group's route. Final objectives remain live. This is
ownership-based operational progress, not a record of each pawn's arrival.

Binary contracts verify every profile's side/turn scope, route suffixes and
monotonic capture state. Kacha V12 demonstrates an inland northern flanking
column and phased city approaches. Runtime gameplay remains a separate check:
an aggressive profile allows worse forecasts but cannot guarantee every attack.
