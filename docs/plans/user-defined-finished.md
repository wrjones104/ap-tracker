# User-Defined "Finished" — Phase 2

**Tracking issue:** [#249](https://github.com/wrjones104/ap-tracker/issues/249)
**Phase 1:** shipped as **server v1.9.0** ([#260](https://github.com/wrjones104/ap-tracker/pull/260), [#264](https://github.com/wrjones104/ap-tracker/pull/264))
**Phase 2:** **built** in [#272](https://github.com/wrjones104/ap-tracker/pull/272) — app **v1.9.0**, server **v1.9.1**

This was written as a forward-looking plan and is kept as the record of the work. Sections
that shipped as specified are marked **Done**; the two that shipped differently are §6 and
§4's copy, both called out inline. §11 covers what implementation turned up that the plan
did not anticipate.

**Origin:** Discord request (ChromaNyan, 2026-08-16). Slots that have goaled but not sent all
their locations are treated as "finished" and hidden, which is wrong for release-off worlds.

> This document is written to be executed from a cold start. It assumes no knowledge of the
> conversation that produced it. Where it names a file, verify the anchor with the `grep` given
> rather than trusting a line number — Phase 1 moved `poller.py` by ~260 lines and line numbers in
> older notes are unreliable.

---

## 1. What Phase 1 already did (context, not work)

The server now tracks **two independent completion facts per slot** and lets each user choose which
combination counts as "finished". Every account defaults to `goal`, which is the behavior the app
has always had, so Phase 1 is invisible in production today.

| Fact | Meaning | Source |
|---|---|---|
| `is_finished` | ClientStatus 30 (goal). **Unchanged on the wire** — older app builds still read it and behave identically. | `player_status` in `/api/tracker/<id>` |
| `has_all_checks` | Nothing left to send from this world. | `player_checks_done` vs `player_locations_total`, both already fetched each poll |

**Why they diverge:** `MultiServer.on_goal_achieved` auto-releases only when release mode contains
`auto`. With release **off**, goaling leaves remaining locations unchecked, so a slot can be goaled
and still actively sending items for a long time. That window is the entire reason this feature
exists. Validated live: a bot goaled at 40/300 and climbed to 300/300 over ~35 minutes.

**Semantics caveat that affects UI copy:** `collect_player` registers checks against the *source*
player, so another player collecting raises your slot's count. `has_all_checks` therefore means
**"no items remain to be sent from this world"**, not "this player personally checked everything".
Label it accordingly.

**Not implementable:** a separate "Released" criterion. Archipelago funnels release and normal
checks into the same `location_checks` set; they are indistinguishable downstream.

### Server pieces already in place

- `users.finished_definition_default` — `goal` | `all_checks` | `both` | `either`, default `goal`
- `user_tracked_slots.finished_definition` — nullable per-slot override
- `tracked_rooms.cached_checks_json` — `{slot_id: checks_done}`, written only on change
- Migration `c4d21a7f9b83`
- `evaluate_finished()` and `resolve_finished_definition()` in `backend/app/utils.py`
- 39 tests in `backend/tests/test_finished_definition.py`

---

## 2. The API contract Phase 2 codes against

Verify before coding:
```bash
grep -n "has_all_checks\|checks_done\|total_locations\|finished_definition" backend/app/routes/rooms_routes.py backend/app/routes/slots_routes.py backend/app/routes/user_routes.py
```

**`GET /rooms/<id>/players`** — each player object:

| Field | Type | Notes |
|---|---|---|
| `is_finished` | bool | Goal only. Never null. Do not repurpose — old clients depend on it. |
| `has_all_checks` | bool \| **null** | `null` = counts never fetched for this room |
| `checks_done` | int \| **null** | `null` under the same condition |
| `total_locations` | int | 0 means the static-tracker fetch failed; never treat as complete |

**`GET /rooms/tracked-slots`** — each tracked slot: the same four fields, plus
`finished_definition` (string | null — the per-slot override).

**`GET /users/me`** — `finished_definition_default` (string).

**History items** — `playerHasAllChecks` (bool). **See §3.1: this one is wrong and must be fixed
before it is consumed.**

**Writes:**
- `PUT /users/me/preferences` accepts `finished_definition` (validated against
  `goal`/`all_checks`/`both`/`either`; 400 otherwise)
- `PUT /rooms/<id>/slots/<slot>/preferences` accepts `finished_definition` (same values, or `null`
  to clear the override)

### `null` is the whole ballgame

`has_all_checks == null` means **unknown**, and is categorically different from `false`.

A room whose counts were never fetched — a finished async that no longer polls, or a host that does
not serve `player_checks_done` — must fall back to **goal-only** for every definition. Treating
`null` as `false` would report every goaled slot in those rooms as *unfinished*, flooding filtered
views with slots that finished weeks ago. That is the original complaint, inverted.

The Kotlin evaluator must mirror `evaluate_finished` in `backend/app/utils.py` exactly, including
this rule. Read that function before writing the Kotlin twin.

---

## 3. Server prerequisites (small, do first)

### 3.1 History payload must emit `null` for unknown — **Done**

`playerHasAllChecks` was always a bool. The players and tracked-slot endpoints already
return `null` when a room's counts are unknown; the history path does not, so history rows from
those rooms would evaluate as "still sending" and reappear under `both`.

Not a live bug at the time — nothing read the field yet — but it had to be fixed before
Phase 2 consumed it. It was very nearly missed: Phase 2 was built against the old plan and
began consuming the field before this was done, and the gap only surfaced when this document
was merged back in. `TestHistoryUnknownChecksContract` now pins all three derivation sites
and both passthroughs, so a fourth site added without the guard fails a test.

```bash
grep -n "playerHasAllChecks\|has_all_checks = receiver_obj" backend/app/routes/history_routes.py
```

Three derivation sites and two passthroughs. Each needs the same `checks_known` treatment the other
routes use:

```python
checks_map = parse_cached_checks(room.cached_checks_json)
checks_known = bool(checks_map)
```

Match the existing pattern in `rooms_routes.py` (search `checks_known`).

### 3.2 The finish-event split (see §6)

New column + poller change. Do it with 3.1 in one server PR before starting Android work.

---

## 4. Decisions locked

| Decision | Outcome |
|---|---|
| Criteria | `goal`, `all_checks`, `both`, `either` — all four |
| Default | `goal` — zero behavior change |
| Granularity | User default + nullable per-slot override, matching every other notification pref |
| Governs | Slot list visibility, history/hints visibility, notification suppression |
| Does **not** govern | `TrackedRoom.is_complete` — hard-coded goal-only, globally. See [#263](https://github.com/wrjones104/ap-tracker/issues/263). |
| Source of truth | Archipelago WebHost API only. **Not** Cheese — it is an optional third-party tool and its logic must not become load-bearing here. |
| Local history cache | Room migration adding raw facts. Not an overlay — the widget has no overlay path. |
| Visual indicator | Material vector icons, never emoji |

### Copy — **shipped differently**

Use Archipelago-native vocabulary. The plan proposed spelling the second fact out in full;
what shipped uses **"all checks"**, the term the community actually says:

- **Goaled**
- **All checks**
- **Goaled + all checks**
- **Goaled or all checks**

Each option's description unpacks the jargon for anyone who has not met it, since "all
checks" is not literally "this player did all their own checks" — another player collecting
raises the count too.

The setting is labelled **"Finished means"**, which reads as a sentence with its value
("Finished means: goaled or all checks") and is short enough not to crowd the row.

"This is what Cheese calls done" belongs in the Discord release post — ephemeral, buys recognition
— not in durable in-app strings.

---

## 5. Android work

### 5.1 Evaluator twin

New file, e.g. `android/app/src/main/java/com/jones/aptracker/data/FinishedDefinition.kt`.

An enum plus one `evaluate(isGoaled: Boolean, hasAllChecks: Boolean?, definition: String?)`
function mirroring `evaluate_finished`. Two rules that are easy to miss:

1. `hasAllChecks == null` → return `isGoaled`, for **every** definition
2. Unrecognized definition string → treat as `goal`, do not throw (forward compatibility with a
   newer server)

Every filter site calls this. No inlined comparisons.

### 5.2 Room migration 23 → 24

```bash
grep -n "version = " android/app/src/main/java/com/jones/aptracker/database/AppDatabase.kt
grep -n "^val MIGRATION_" android/app/src/main/java/com/jones/aptracker/database/Migrations.kt | tail -2
```

Current `version = 23`, latest is `MIGRATION_22_23`. Add `MIGRATION_23_24`:

```sql
ALTER TABLE history_items ADD COLUMN playerHasAllChecks INTEGER DEFAULT NULL
```

**Nullable, not `NOT NULL DEFAULT 0`** — the tri-state has to survive into local storage or §2's
`null` rule is defeated at the cache layer. `Boolean?` in the entity.

Keep `isPlayerFinished` as-is; it already means goaled, so no rename and no churn across its many
call sites.

Then:
- add the field to `HistoryItemEntity`
- map it in `HistoryRepository` (three mapping sites — `grep -n "isPlayerFinished" HistoryRepository.kt`)
- **register `MIGRATION_23_24` in the array in `AppDatabase.kt`** — easy to forget, crashes on upgrade

### 5.3 Filter call sites

```bash
grep -rn "matchesFinished" android/app/src/main/java/com/jones/aptracker/
```

Four sites, all routed through the evaluator:

| File | Anchor |
|---|---|
| `ui/SlotsScreen.kt` | `showFinished \|\| !slot.is_finished` |
| `ui/HistoryScreen.kt` | `showFinished \|\| !isFinished` |
| `ui/HistoryScreen.kt` | `showFinished \|\| !isItemOwnerFinished` |
| `widget/RecentItemsWidget.kt` | `showFinished \|\| !item.isPlayerFinished` |

The widget reads stored values directly with no overlay — there is an architectural note in the
file saying so. That is exactly why §5.2 is a migration rather than a ViewModel overlay.

Also update `HistoryViewModel`: the `finishedPlayerKeys` overlay and the `isActuallyFinished`
computation both need to carry both facts instead of one boolean
(`grep -n "finishedPlayerKeys\|isActuallyFinished" HistoryViewModel.kt`).

### 5.4 Unify the two visibility toggles

`ui_show_finished` is server-synced; `slots_show_finished` is local-only
(`grep -n "SLOTS_SHOW_FINISHED_KEY" data/SettingsManager.kt`). They are independent today, which
will read as a bug once a shared definition sits on top of them.

Consolidate onto the server-synced one. Migrate the existing local value on first run so nobody's
toggle silently flips.

### 5.5 Settings UI

- **Global:** `ui/SettingsScreen.kt`, near the existing finished toggle
  (`grep -n "Finished slots" SettingsScreen.kt`)
- **Per-slot:** `ui/SlotOverridesScreen.kt`, following the `currentValue` / `defaultValue` pattern
  used by the other overrides — but a 4-way selector, not a tri-state boolean

### 5.6 Visual states

`Icons.Filled.Flag` = goaled, still has items to send. `Icons.Filled.CheckCircle` = fully done.
Both need `contentDescription`; do not rely on color alone.

Surfacing `checks_done / total_locations` ("412/500") next to a slot makes the setting
self-explanatory — it shows *why* something is still visible.

Related: [#262](https://github.com/wrjones104/ap-tracker/issues/262) covers four hardcoded 🏁
literals. Two are in `SlotsScreen.kt` and are replaced by this work; `PlayersScreen.kt` and
`HistoryScreen.kt` are residual and worth doing in the same pass.

---

## 6. Finish-event split — **shipped differently, read this**

### The problem

`notify_finished` currently does two unrelated jobs:

1. Whether you are told **that a slot finished** (the one-time event)
2. Whether you keep getting **item/hint notifications for a slot after it finishes** (ongoing)

The UI labels it *"Finished slots — Notify for events after a slot has goaled."* That describes
only job 2. The finish event is not an event *after* goaling; it *is* the goaling. Combined with
`notify_finished_default = False`, the majority of users have never received a finish notification
and were never told why.

**This is a label/behavior mismatch, not a design decision.**

### What was planned

| Pref | Job | Default |
|---|---|---|
| `notify_finished` (existing) | Suppress ongoing item/hint notifications for finished slots | stays `False` |
| `notify_finish_event` (new) | The "X has finished!" notification | **`True`**, backfilled for everyone |

### What shipped

**No new preference.** The finish announcement is simply unconditional — the gate inside
`_check_player_completion` was removed rather than repointed, and `notify_finished` now
governs only the ongoing item/hint stream. The existing toggle was relabelled **"Keep
notifying finished slots"**, with a description saying outright that the finish notification
always arrives.

This was a direct product call during implementation, and it reaches the same place the plan
was aiming for — everyone gets the event — by a shorter route: no column, no migration, no
API plumbing, no second toggle in two settings screens.

**The tradeoff, stated plainly: there is now no way to turn the finish notification off.**
The planned design kept that escape hatch. Nobody has asked for one, and it is one
notification per slot for the life of that slot, but if a user does ask, restoring it means
building `notify_finish_event` as originally specified — this section is the spec.

Still **must be called out in the release notes**: users with the preference off begin
receiving finish notifications they were not getting before. That is unchanged from the plan.

### Why now

Under `both`, "X has finished" fires when a slot is genuinely done rather than at a goal that may
mean nothing in a release-off room. The event becomes more trustworthy exactly as it is turned on.

### Implementation as built

The two jobs already read the same variable at **separate call sites**, so this needed no
restructuring — just removing one gate and leaving the other two alone.

```bash
grep -n "notify_finished" backend/app/poller.py
```

- Inside `_check_player_completion` (`notify_override` / `should_notify`) → **the event**.
  Gate removed entirely; fires on the false → true edge of the user's own evaluation.
- In `_resolve_names_and_notify`, the item-suppression site (`wants_finished_notifs` next to
  `_slot_is_finished_for_user(rid, ...)`) → **stays** `notify_finished`.
- The hint-suppression site (`wants_finished_notifs` next to
  `_slot_is_finished_for_user(relevant_slot, ...)`) → **stays** `notify_finished`.

The new columns, Alembic revision, API plumbing, `api_cheese.py` slot creation, and the
second pair of Android toggles were all **not** built, since there is no new preference.

`test_finish_announcement_still_fires_once_only` guards the one real hazard here: removing a
gate from inside a loop is an easy way to turn a one-off into a repeat.

---

## 7. Traps — every one of these has already bitten or nearly bitten

1. **`bool()` coercion in both preference endpoints.** `slots_routes.py` and `user_routes.py`
   iterate field lists and coerce with `bool(val)`. Any enum string through those loops becomes
   `True`. `finished_definition` is already special-cased. Check before adding anything else.

2. **`applySlotSettingsToAll` enumerates fields explicitly.** Anything not listed is silently
   dropped — and because Retrofit is configured with `serializeNulls()`, the omitted field is sent
   as an explicit `null`, which the server writes, **clearing the target slot's override**. This is
   live bug [#261](https://github.com/wrjones104/ap-tracker/issues/261) (`suppress_connected` is
   already missing). **Fixed structurally** — both write paths now build from a single
   `TrackedSlotDetail.toPrefsRequest()`, so a preference cannot go missing from one of them
   again. See §11.
   ```bash
   grep -n "applySlotSettingsToAll" -A 20 android/app/src/main/java/com/jones/aptracker/ui/UserViewModel.kt
   ```

3. **`MIGRATION_23_24` must be registered** in the migrations array in `AppDatabase.kt`, not just
   defined in `Migrations.kt`.

4. **`total_locations == 0`** is the failed-static-fetch sentinel. Never treat as complete.

5. **`null` ≠ `false`** for `has_all_checks`, at every layer including local SQLite. See §2.

6. **Do not repurpose `is_finished` on the wire.** Old Play Store builds read it and must keep
   behaving identically.

---

## 8. Release — **Done**

Phase 2 is the user-facing release — Phase 1 shipped quiet on purpose. Shipped as app
**v1.9.0** (versionCode 72) and server **v1.9.1**.

- `android/app/build.gradle.kts`: `versionName` 1.8.2 → **1.9.0**, `versionCode` 71 → **72**
- Server gets its own bump if §3 lands as a separate PR (it should)
- Run `/version-manager`. Unlike Phase 1, this one gets **full** Discord and Play Store notes.
- Two things the notes must cover: the new setting, and **that finish notifications are now on by
  default** (§6)
- Consider a direct note to ChromaNyan, who requested this

---

## 9. Verification

```bash
# Backend
PYTHONPATH="backend;." venv/Scripts/python.exe -m unittest $(ls backend/tests/test_*.py | sed 's|/|.|g;s|\.py$||')

# Changelog / gradle agreement
venv/Scripts/python.exe scripts/generate_changelog.py --check
```

Android tests to add:

- Evaluator truth table: 4 definitions × 4 fact combinations, **plus the `null` column** — every
  definition must return `isGoaled` when `hasAllChecks` is null
- Unknown definition string falls back to `goal`
- Room migration 23 → 24 preserves existing rows and leaves `playerHasAllChecks` null
- Each filter site hides/shows correctly under all four definitions

The backend truth table in `backend/tests/test_finished_definition.py` is the reference — mirror it.

### Manual test fixtures

A **release-off** room is the only way to exercise the real case; with release on, goal and
all-checks converge and every definition agrees. During Phase 1 testing, 8 auto-running bots in a
release-off room produced the divergence for ~35 minutes.

What to verify by hand:

| Definition | Goaled slot that is still sending |
|---|---|
| `goal` | hidden |
| `all_checks` | visible |
| `both` | visible |
| `either` | hidden |

---

## 10. Open risks and related issues

- ~~**[#263](https://github.com/wrjones104/ap-tracker/issues/263)**~~ — **Fixed**, and it did
  ship before the setting as this section required. `is_complete` now requires all-goaled and
  all-drained, extracted as `_room_is_complete`, with migration `b2e75c4a19d8` reviving rooms
  already stuck. Falls back to goal-only when check counts are unknown, so hosts that never
  serve `player_checks_done` are unaffected.

- ~~**[#261](https://github.com/wrjones104/ap-tracker/issues/261)**~~ — **Fixed** structurally
  rather than patched. See §11.

- ~~**[#262](https://github.com/wrjones104/ap-tracker/issues/262)**~~ — **Fixed**, all four
  sites. `remove_emojis` keeps its notification-only meaning; vector icons are not emoji.

- ~~**[#268](https://github.com/wrjones104/ap-tracker/issues/268)**~~ — **Fixed**. The
  Milestones widget honors the show-finished toggle and the user's definition.

- **Suppression under `all_checks` / `either`.** A slot can qualify while its player is still
  active, because other players auto-collecting raises their count. Those users would stop getting
  notifications for a live slot. Accepted risk, mitigated by defaulting to `goal`. If complaints
  appear, AND the goal condition into the notification path only.

- **Multi-team rooms** are unsupported, consistent with pre-existing behavior. `player_checks_done`
  is filtered to team 0, matching the existing `player_status` parsing. Team is effectively unused
  in Archipelago in practice.

- **`player_status` arrives as a list** from both archipelago.gg and archipelago.today. The dict
  branch in the poller is legacy and unexercised in the wild. Both are handled.

---

## 11. As built — what the plan did not anticipate

### 11.1 #261 fixed structurally, not patched

Adding `finished_definition` to `UpdateSlotPrefsRequest` would have reproduced #261 on the
spot. Trap 2 describes the mechanism but frames the fix as "add the missing fields", which
leaves the shape that produces the bug intact.

Both write paths now build from one `TrackedSlotDetail.toPrefsRequest()` extension. Adding a
preference is a single edit, and "copy to all slots" cannot silently skip it. Verified by
diffing the server's accepted field list against what the client sends — 14/14, no drift in
either direction, which is a check worth repeating whenever a preference is added.

### 11.2 A finished room vanished from the slots list

Not in the plan, and the more serious of the two bugs found during implementation.

`SlotsScreen` dropped a room entirely once every one of its slots was filtered out. With
finished slots hidden, a room disappeared the moment its last slot completed — the Rooms tab
still listed it, so it looked like the app had half-lost the room.

Pre-existing, but this work made it far easier to reach: more slots correctly read as
finished, and rooms now survive to a fully-complete state instead of being archived first.

Two filters ran through that path and they are not equivalent:

- **Search** emptying a room still removes it. That is what searching means.
- **The finished filter** emptying a room never removes it.

A room leaving the list should only ever be a user action — archive or delete. Extracted as
`buildRoomSlotGroups` with `RoomSlotGroupTest` pinning the asymmetry, because collapsing the
two filters back together is an easy regression to reintroduce while tidying.

### 11.3 The legacy toggle migration could invent a `false`

§5.4 says to migrate the old slots-only value so nobody's toggle silently flips. The trap is
that `SettingsManager.slotsShowFinished` defaulted to `false` while the unified
`ui_show_finished` defaults to `true`, and the flow collapsed "never set" into that false —
so the migration would carry a phantom `false` across and hide finished slots for users who
had never touched the old toggle. Exactly the flip the migration exists to prevent.

The flow is `Flow<Boolean?>` and the migration no-ops on null.

### 11.4 Getting definitions to the widgets

The plan did not settle how per-slot definitions reach code with no ViewModel. They are
mirrored into the same SharedPreferences file the widgets already read for view toggles
(`FinishedDefinitionStore`) — the global default as a string, the overrides as a small JSON
map, rewritten wholesale after every tracked-slot fetch.

Mirrored rather than denormalized onto each row: changing the setting re-filters everything
already cached on the next read, with no table rewrite and no resync.

`FinishedDefinitionStore.resolverFlow` and `ShowFinishedPreference` are process-wide holders
rather than per-ViewModel state. Two independent flows over the same key drift the moment one
screen writes — changing the definition in Settings would leave an already-loaded History
screen filtering on the old one until it happened to refetch.

### 11.5 Filter sites: fewer than the plan expected

§5.3 lists four call sites. Both history filter sites and the hints filter already routed
through `finishedPlayerKeys`, so making that one flow definition-aware covered all three
without touching the screen. Only the slots list and the widget needed direct changes.

### 11.6 Room migration touches two tables

§5.2 specifies the `history_items` column. `cached_tracked_slots` needed the same two facts
so the Milestones widget could filter offline for #268, so `MIGRATION_23_24` alters both.

The history column is `INTEGER` **nullable**, not `NOT NULL DEFAULT 0` as drafted elsewhere.
Unknown is a real third state; collapsing it into false would make goaled slots reappear for
users on stricter definitions. Existing rows correctly read as unknown until the next sync.

### 11.7 Settings row layout

Both dropdown-backed settings share `SettingsDropdownRow`, with the selected value on its own
full-width line under the title. A trailing value works for short strings, but these are
phrases — "Counts as finished" was wrapping to two lines to make room for "Goaled or no items
left to send". `DateFormatPreset` gained a `sample` property so the row can show the name and
the live example separately; the picker still shows both together.

### 11.8 Room headers always show their makeup

Each room header carries a proportional bar and an active/finished count that is present
whatever the filter is doing. The old count badge could not do this job — it only ever
described what was on screen, so it could not indicate that hidden slots existed. Rooms with
hidden slots also get an inline "N finished slots hidden in this room / Show" row when
expanded; it is room-scoped and says so, since an unqualified count reads as a screen-wide
total and will not match one when several rooms each hide a slot.
