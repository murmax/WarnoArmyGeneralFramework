# Release 1.0.1

Dynamic deployments now use frozen lifecycle 4. The native pawn descriptor
keeps its full AP capacity and per-turn recovery. Startup clears current AP
before the strategic kernel; bounded gates clear only the locked owner turns.
Release restores AP and leaves normal recovery active. Existing saved 0/0
descriptors are not migrated: start a new campaign.

Optional `localization.yaml` catalogs cover French, German, Spanish, Polish
and Simplified Chinese, alongside existing Russian and English fields.
Declared languages require complete display-text coverage. Native placeholders
and coalition tags must survive translation. Runtime, bootstrap, map, battalion,
company and platoon dictionaries receive localized strings.

The owner can use the logged-in Steam client to update only content and preview.
The helper verifies ownership and compares title, description, visibility and
tags before/after. Credentials are not passed to the helper, and the game's SDK
DLL is not redistributed.

Kacha V11 demonstrates these changes. Automated source/binary checks are
distinct from player validation; no new interactive gameplay is claimed.
