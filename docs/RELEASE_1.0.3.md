# Release 1.0.3

Strategic mission radii can be expressed in native action-point cells. The
compiler reads the installed LBU/GRU conversion and stores its provenance.
It writes map-scale-aware integers to AttackEnemyInRadius/WaypointReachedRadius.
Unchanged campaigns retain their legacy GRU values.

Four fields define attack, quiet-transit, support and waypoint radii;
`transit_waypoints` limits quiet transit to explicitly designated intermediate
positions. Frontline defenders still use the attack radius. Native contracts
reject radii inconsistent with the compiled conversion and task role.

This corrects a confirmed Kacha V12 error: 2120/707 GRU produced approximately
156,000/52,000 GU, or 12/4 native AP cells. A copied player save contained
intact inland/Bakhchysarai routes with current destinations diverted to the
Sevastopol area. Kacha V13 uses 1.5-cell attack, 0.5-cell quiet transit/support,
and 0.8-cell waypoint tolerance, retaining its NATO opening aggression window.
Fresh campaigns are required: saved games serialize their own mission data.
