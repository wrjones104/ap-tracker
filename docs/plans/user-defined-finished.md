# User-Defined "Finished" — Phase 2 Plan

**Tracking issue:** [#249](https://github.com/wrjones104/ap-tracker/issues/249)
**Phase 1:** shipped and running in production as **server v1.9.0** ([#260](https://github.com/wrjones104/ap-tracker/pull/260), [#264](https://github.com/wrjones104/ap-tracker/pull/264))
**Phase 2:** not started. Android only — no further server work except the two prerequisites in §3.

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

### 3.1 History payload must emit `null` for unknown

`playerHasAllChecks` is currently always a bool. The players and tracked-slot endpoints already
return `null` when a room's counts are unknown; the history path does not, so history rows from
those rooms would evaluate as "still sending" and reappear under `both`.

Not a live bug — nothing reads the field yet — but it must be fixed before Phase 2 consumes it.

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

### Copy

Use Archipelago-native vocabulary:

- **Goaled**
- **No items left to send**
- **Goaled + no items left to send**
- **Goaled or no items left to send**

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

## 6. Finish-event split (decided, not yet built)

### The problem

`notify_finished` currently does two unrelated jobs:

1. Whether you are told **that a slot finished** (the one-time event)
2. Whether you keep getting **item/hint notifications for a slot after it finishes** (ongoing)

The UI labels it *"Finished slots — Notify for events after a slot has goaled."* That describes
only job 2. The finish event is not an event *after* goaling; it *is* the goaling. Combined with
`notify_finished_default = False`, the majority of users have never received a finish notification
and were never told why.

**This is a label/behavior mismatch, not a design decision.**

### The fix

| Pref | Job | Default | Effect on existing users |
|---|---|---|---|
| `notify_finished` (existing) | Suppress ongoing item/hint notifications for finished slots | stays `False` | **none** |
| `notify_finish_event` (new) | The "X has finished!" notification | **`True`**, backfilled `True` for everyone | starts arriving |

Backfilling everyone to `True` is a deliberate product call, confirmed: most users' "off" was never
a decision, just an unseen default behind a label that did not describe this behavior. It is one
notification per slot for the entire life of that slot — not spam. **Must be called out in the
release notes.**

Relabel the existing toggle to say what it actually does, e.g. *"Keep notifying after a slot
finishes"*, so it stops implying it controls the event.

### Why now

Under `both`, "X has finished" fires when a slot is genuinely done rather than at a goal that may
mean nothing in a release-off room. The event becomes more trustworthy exactly as it is turned on.

### Implementation

The two jobs already read the same variable at **separate call sites**, so this is a matter of
changing which pref each one reads — no restructuring.

```bash
grep -n "notify_finished" backend/app/poller.py
```

- Inside `_check_player_completion` (`notify_override` / `should_notify`) → **the event**. Switch to
  `notify_finish_event`.
- In `_resolve_names_and_notify`, the item-suppression site (`wants_finished_notifs` next to
  `_slot_is_finished_for_user(rid, ...)`) → **stays** `notify_finished`.
- The hint-suppression site (`wants_finished_notifs` next to
  `_slot_is_finished_for_user(relevant_slot, ...)`) → **stays** `notify_finished`.

Plus: new columns `users.notify_finish_event_default` (server_default true) and
`user_tracked_slots.notify_finish_event` (nullable), one Alembic revision, the API plumbing in
§7, and Android toggles in both settings screens.

Also update `api_cheese.py` where slot rows are created with `notify_finished=...` — the new field
needs the same treatment (`grep -n "notify_finished=user" backend/app/api_cheese.py`).

---

## 7. Traps — every one of these has already bitten or nearly bitten

1. **`bool()` coercion in both preference endpoints.** `slots_routes.py` and `user_routes.py`
   iterate field lists and coerce with `bool(val)`. Any enum string through those loops becomes
   `True`. `finished_definition` is already special-cased; **`notify_finish_event` is a boolean and
   can go in the loop**, but check before adding anything else.

2. **`applySlotSettingsToAll` enumerates fields explicitly.** Anything not listed is silently
   dropped — and because Retrofit is configured with `serializeNulls()`, the omitted field is sent
   as an explicit `null`, which the server writes, **clearing the target slot's override**. This is
   live bug [#261](https://github.com/wrjones104/ap-tracker/issues/261) (`suppress_connected` is
   already missing). Add `finished_definition` and `notify_finish_event` here, and fix
   `suppress_connected` in the same pass.
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

## 8. Release

Phase 2 is the user-facing release — Phase 1 shipped quiet on purpose.

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

- **[#263](https://github.com/wrjones104/ap-tracker/issues/263) — fix before shipping the setting.**
  `is_complete` fires on all-goaled and is never reset, so release-off rooms stop polling while
  still being played. A user who picks `both` specifically to keep seeing release-off slots may
  find the room stops polling entirely, which partly defeats the setting. Measure current impact:
  ```sql
  SELECT COUNT(*) FROM tracked_rooms
  WHERE is_complete = true AND cached_players_json LIKE '%"has_all_checks": false%';
  ```
  Only counts rooms completed after the v1.9.0 deploy, which is the right window.

- **[#261](https://github.com/wrjones104/ap-tracker/issues/261)** — copy-to-all-slots clears
  `suppress_connected`. Trap 2 above; fix in the same pass.

- **[#262](https://github.com/wrjones104/ap-tracker/issues/262)** — hardcoded 🏁 in four in-app
  sites. Two are covered by §5.6.

- **Suppression under `all_checks` / `either`.** A slot can qualify while its player is still
  active, because other players auto-collecting raises their count. Those users would stop getting
  notifications for a live slot. Accepted risk, mitigated by defaulting to `goal`. If complaints
  appear, AND the goal condition into the notification path only.

- **Multi-team rooms** are unsupported, consistent with pre-existing behavior. `player_checks_done`
  is filtered to team 0, matching the existing `player_status` parsing. Team is effectively unused
  in Archipelago in practice.

- **`player_status` arrives as a list** from both archipelago.gg and archipelago.today. The dict
  branch in the poller is legacy and unexercised in the wild. Both are handled.
