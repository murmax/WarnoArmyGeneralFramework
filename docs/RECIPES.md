# Practical changes using Kacha

[Build/install guide](GETTING_STARTED.md) · [All fields](YAML_REFERENCE.md) · [Русская версия](RECIPES_RU.md).

Work in your cloned campaigns/my-campaign. Check after each coordinated edit, using a new output directory. When changing English source strings, update every enabled language table in localization.yaml.

## 1. Rename the campaign and armies

Change campaign.title/summary and all menu RU/EN text. The clone command already changed technical identity; displayed names do not change IDs. For different army captions, add **inside menu**:

```yaml
side_titles:
  nato: {ru: Экспедиционный корпус, en: Expeditionary Corps}
  pact: {ru: Прибрежная армия, en: Coastal Army}
```

Change playable countries and actual roster/visual resources consistently. Menu.attacker controls captions; ai_policy.native_strategies controls native AI roles. You can keep a technical flag ID such as sevastopol while renaming its human text. If changing the ID, also update victory, routes, events, camera, reserve requirements and ending_flags.

## 2. Duration and reinforcement timing

Changing turns 20→24 extends the deadline; it does not reschedule arrivals. Change production groups' turn, automatic reinforcement turn, event trigger, aircraft availability/withdrawal and phase_orders together.

Do not move a blocked division before capture_deadline.before_turn. IDs are labels: current `sov_turn11` actually has turn 10. Edit **turn**, not the digits in its ID. Update narrative promises about hours and arrival dates too.

## 3. Modify a roster

Find sov_880 in battalions/forces.yaml, then its company/platoon/units. Changing count 3→4 adds one roster element of that pack, not another company. Quantity also depends on pack.number.

For a transport/experience change affecting only that platoon:

1. Find the referenced type in packs.yaml.
2. Copy the entire pack with a new ID, such as my_880_rifle_btr80.
3. Set the actual unit/transport/experience/number from the catalogs.
4. Change type only in the intended platoons.

Editing a shared original pack changes every consumer. To replace tanks, choose the real tactical ID/pack; changing a displayed company name does not replace its vehicles.

## 4. Command, supply and support

Copy the headquarters structure of sov_810_hq or us_2md_hq, then select real packs. HQ flags describe structure, not command ability: add actual commanders/command vehicles.

A FOB and ten supply vehicles are normal roster entries: FOB pack count 1, vehicle pack number 1/count 10. There is no special supply:10 key. Use suitable helicopter command/transport/supply units for an all-helicopter formation.

Artillery example:

```yaml
strategic:
  type: mechanized
  battle_role: ground_support
  visual: {unit: 2S1_Gvozdika_Naval_SOV}
  icon: howitzer
  support: {kind: artillery, radius_ap: 12}
initial_state: {fatigue: 0, action_points: 5}
```

AA uses auxiliary_support, AA icon, air_defence kind and an actual AA appearance. Keep deployment current AP consistent. Definition AP sets normal recovery, not only the first displayed number. Radius is strategic AP scale. Native AI deployment/use is not guaranteed by the declaration.

## 5. Add a reserve battalion

Copy the **whole** sov_885 battalion object, including definition/companies, into the battalions list or another schema-1 battalion file. Give it ID my_reserve and your names/roster. Company/platoon IDs may repeat in different battalions. Do not deploy it initially or add a starting AI order.

Add under production.groups:

```yaml
- id: my_reserve_card
  division: sov_810
  name: {ru: Резервная группа, en: Reserve Group}
  turn: 6
  battalions: [my_reserve]
  ai: {type: defend, target: sevastopol}
```

Translate the new text. For several arriving battalions in one card, copy separate definitions and list their unique IDs together. Existing division provides its points; a new placement point needs a same-side declaration and reference from the division. Do not leave unused points/divisions. Humans receive a reserve card; AI receives the declared plan.

## 6. Automatic or choice-triggered arrivals

Automatic ground arrival belongs in reinforcements.yaml with id/battalion/side/turn/position/ai. For arrival after pressing a decision button, put in that choice's effects:

```yaml
effects:
- spawn: my_event_reserve
  position: [851500, 331500]
  ai: {type: defend, target: sevastopol}
```

Use a separate definition from the production reserve. For delayed arrival, add at_turn:6 to a dated event with trigger earlier than 6. Aircraft use aviation availability instead.

For two alternative landing places, create two different battalion definitions like Kacha's SEAL variants. A mutable Pawn cannot appear through two alternative branches of the same descriptor.

## 7. Difficulty without unintended missing tanks

In nato_difficulty/pact_difficulty, first option is index 0 Normal, second index 1 Harsh; keep ai_choice 0. Production defines separate exclusive groups:

- us_turn5: both choices 0;
- us_turn5_hard_pact: NATO 0, PACT 1;
- us_turn5_hard_nato: NATO 1, PACT 0;
- corresponding independent groups at turn 7.

Edit the intended group's unique battalions and its entire when list. Conditions are AND. For another force variant, copy definitions before attaching a separate card. Story text explains the situation but does not configure which forces exist.

## 8. Lock a garrison for two turns

Set deployment.frozen_turns to 2 while retaining positive normal AP/recovery in definition.initial_state, e.g. 10. After release it behaves normally. Do not zero permanent capacity or simulate a lock with indefinite supply malus. Existing saves retaining 0/0 state need a fresh campaign.

## 9. Aircraft decisions and withdrawal

Change actual aircraft packs and aircraft_role, then bind the wing to available `{event:sov_air_choice,choice:0}` or 1. Update name, parent/insignia, picture and text separately. A SEAD wing needs a SEAD-tagged aircraft and role sead; ground strike accepts bomber/AT aircraft. Supporting marines does not require aviation to share their brigade parent.

If changing withdrawal turn, update the carrier notice too. Every withdrawing wing needs withdraw_turn. A text notice alone does not remove the surviving SEAD formation.

## 10. Move an objective, city and route

Objective position is map.flags; geographic caption map.labels; initial formations deployments; reserve points production.deployment_points; route positions map.waypoints. Renaming a caption does not move all these together.

Check nearest influence and ownership. AI targets are IDs, not displayed strings. A Bakhchysarai route can be `[bakhchysarai,inkerman,sevastopol]`, with all positions declared. For different main IDs, set cinematics.ending_flags/encirclement_flags, victory and camera explicitly. Ending-axis key names remain technical categories.

## 11. Replace artwork/insignia

Replace the source file at event-images.images, or add a logical ID plus PNG. A new ID needs matching profile token `AGF_EVT_<namespace>_<id>` and event/slide references. For paired decisions, update composites.cards and choices[].card.image.

Menu artwork is campaign.menu.image. Custom insignia is emblems token/image plus formation.emblem, separate from native national flags. Keep real original provenance/attribution; a Wikimedia URL does not replace the local PNG required for compilation.

## 12. Maintain translations

After changing an English name/text, update its exact source-string key and corresponding meaning in all enabled localization tables. Short OOB translations need natural abbreviations within 30 UTF-16 units. Do not truncate entire introduction prose to that short-name limit.

If intentionally authoring only RU/EN, omit localization.yaml from your copy; other languages use English fallback. Do not describe that mod as fully translated. Published Kacha supplies all seven languages.

## 13. New terrain and geography

For existing geography, replace height/surface rasters and scenery placements with consistent orientation. Forest/urban strategic cells do not automatically create scenery; each placed instance needs its own ID and position.

For geographic inputs:

```powershell
./.venv/Scripts/python.exe -B -m warno_ag geodata-import 32.45 44.28 34.15 45.55 artifacts/my-geodata-01 --cache artifacts/geodata-cache --resolution 2048 --surface-size 4096 --elevation-ceiling-m 1200
```

These are geographic west/south/east/north, not battalion game coordinates. Copy the prepared height/surface assets into artwork, update file links and provenance from the generated report. Inspect actual output filenames in that report.

Reposition cities, flags, frontline, routes, deployments and reserve locations for your new geography: old Kacha positions are not automatically geocoded. Rebuild the entire cells list, or omit it for an initial uniform grid. Align world/profile geometry; native world starts at [0,0] with 655360 units per render case. Keep height below the 5000-unit overlay and use a new matching map_name for changed baked source.

## 14. Final source and build

Save all YAML, referenced artwork and attribution. Check in a new output folder; correct every reported reference/translation issue. Build the complete bundle, install using the guide and start fresh. Editing NDF, binary archives, GUIDs or Python is unnecessary for documented changes. A behavior absent from the reference first needs an actual framework mechanism.
