# Release 1.0.4

Campaigns can explicitly assign the stock attacker/defender roles per side,
and select stock strategic control with a small list of scripted exceptions.
Binary validation checks controller roles and rejects private missions for
formations assigned to stock control.

The Kacha investigation found that the inherited Bruderkrieg controller still
treated PACT as attacker and NATO as defender. Kacha V14 explicitly reverses
these roles, hands NATO to the stock attacker, and keeps one Bakhchysarai–
Sevastopol battalion route. Scripted mission radii are five AP cells for combat
and three for waypoint tolerance; no separate quiet-transit/support limits.
The stock army planner retains its internal rules, unlike private script orders.

Roster, map and translated text are unchanged. Gameplay validation remains
separate from source and binary checks. Begin a fresh campaign after updating.
