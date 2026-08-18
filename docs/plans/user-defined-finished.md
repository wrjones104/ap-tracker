# User-Defined "Finished" — Implementation Plan

**Status:** Phase 1 (server) complete, tested, and validated against a live release-off room
(PR #260). Phase 2 (Android) not started.
**Origin:** Discord request (ChromaNyan, 2026-08-16) — slots that have goaled but not sent all
their locations are treated as "finished" and hidden, which is wrong for release-off worlds.

---

## 1. Decisions locked

| Decision | Outcome |
|---|---|
| Criteria offered | `goal`, `all_checks`, `both`, `either` — all four |
| Default | `goal` (zero behavior change for existing users) |
| Granularity | User-level default + nullable per-slot override |
| Governs | Slot list visibility, history/hints visibility, notification suppression |
| Does **not** govern | `TrackedRoom.is_complete` — hard-coded to goal-only, globally |
| Source of truth | Archipelago WebHost API only. No Cheese-derived logic. |
| Local history cache | Room migration adding raw facts (not an overlay) |
| Visual indicator | Material vector icons, not emoji |

### Why "all checks" is derivable for free

`/api/tracker/<id>` — already fetched and fully parsed every poll at `poller.py:1723` — returns
`player_checks_done`: a list of `{team, player, locations: [ids...]}`.

`total_locations` per slot is already cached in `cached_players_json`, sourced from
`/api/static_tracker/<id>`'s `player_locations_total` at `poller.py:1945`.

So `has_all_checks(slot) = len(checks_done[slot]) >= total_locations[slot]`, with **no new HTTP
calls**.

### Semantics note (affects UI copy)

`MultiServer.collect_player()` calls `register_location_checks` against the **source** players.
So another player collecting raises *your* slot's checks-done count. The metric is therefore
**"no items remain to be sent from this world"** — not literally "this player did all their
checks." Label it accordingly.

`release_player()` also routes through `register_location_checks`, which is why goal and
all-checks converge automatically when `release_mode` contains `auto`, and diverge when it
doesn't. That divergence is exactly the reported bug.

**Not implementable:** a distinct "Released" criterion. AP funnels release and normal checks into
the same `location_checks` set; they are indistinguishable downstream.

---

## 2. Server: data model

### 2.1 New columns

`users`:
```python
finished_definition_default = Column(String(16), default='goal', nullable=False)
```

`user_tracked_slots`:
```python
finished_definition = Column(String(16), nullable=True, default=None)
```

`tracked_rooms`:
```python
cached_checks_json = Column(String, default='{}')   # {slot_id: checks_done_count}
```

### 2.2 Why `cached_checks_json` is separate — do not merge into `cached_players_json`

`db_process_poll_data` already issues one `UPDATE tracked_rooms` + commit per room per poll
unconditionally (`failed_poll_count`, `last_successful_poll`, `last_remote_activity` at
`poller.py:1126-1130`, commit at `poller.py:1424`). Adding a column to that UPDATE is not a new
statement.

The trap: `cached_players_json` is `Column(String)` → TEXT → **TOASTed** past ~2KB (any room
past ~15 slots). Today it is only rewritten when a finished flag flips (`poller.py:1288`), so
most polls reuse the TOAST pointer for free. Writing a per-poll changing count into that blob
would rewrite the entire TOAST value every poll — full WAL volume plus dead tuples for
autovacuum, on the order of ~100 MB/day at 100 active rooms and materially worse for large
asyncs. On an e2-medium that is real pressure.

A `{slot_id: count}` map is ~10 bytes/slot — ~350 bytes for a 30-slot room, inline, no TOAST.

**Additional guard:** only assign `room.cached_checks_json` when a count actually changed. Idle
rooms then contribute nothing beyond the UPDATE that already happens.

### 2.3 Alembic

Single current head, verified: **`a3f8c91d2e47`** (`add_milestone_templates`). New revision sets
`down_revision = 'a3f8c91d2e47'`.

Use `batch_alter_table` to match the existing convention in this repo (see
`0c101b9d386d_add_fields_for_finished_slot_.py`). Backfill is trivial — server defaults cover it.

---

## 3. Server: the evaluator

Single function, `backend/app/utils.py`:

```python
VALID_FINISHED_DEFINITIONS = {'goal', 'all_checks', 'both', 'either'}

def evaluate_finished(is_goaled, has_all_checks, definition):
    if definition == 'all_checks':
        return has_all_checks
    if definition == 'both':
        return is_goaled and has_all_checks
    if definition == 'either':
        return is_goaled or has_all_checks
    return is_goaled          # 'goal', None, or anything unrecognized
```

Unknown values fall back to `goal` rather than raising — a bad row must never break a poll.

Every consumer calls this. No inlined comparisons at call sites. When the next criterion is
requested (manual "mark done", "goaled + inactive N days"), it is one branch here and one in the
Kotlin twin.

---

## 4. Server: poller changes

### 4.1 `_check_player_completion` (`poller.py:245`) — the highest-risk edit

Today it derives one room-global `is_finished` boolean per slot, detects the false→true
transition, and fires the "Player(s) Finished!" notification from that transition.

With per-user definitions, "just became finished" differs per user. The fix is to **cache both
facts room-globally and let each user derive their own transition**:

1. Parse `player_checks_done` from `tracker_data`, build `{slot_id: count}`.
   - **Filter to `team == 0`.** The poller has no team handling anywhere today (`player_status`
     parsing at `poller.py:255` ignores team entirely). Stay consistent; do not half-introduce
     multi-team support here.
2. Compute `has_all_checks = total > 0 and count >= total`.
   - **`total == 0` must never mean "done."** Zero is the sentinel for a failed static-tracker
     fetch — there is already a `has_total_locations` re-setup guard at `poller.py:2605`.
3. Persist `has_all_checks` per slot into `cached_players_json` alongside `is_finished`, and the
   raw count into `cached_checks_json`.
4. Return **both** transition sets: `just_goaled` and `just_all_checks`, plus the current
   `goaled_ids` and `all_checks_ids`.
5. For each user tracking the slot, compute `prev = evaluate_finished(prev_goaled,
   prev_all_checks, defn)` and `now = evaluate_finished(now_goaled, now_all_checks, defn)`.
   Fire the finish notification on `not prev and now`.

Keep the existing Case-B revert (`poller.py:281`) for goal. Checks-done is monotonic in practice,
so it needs no revert path — but `total_locations` can change after a re-setup, so recompute
rather than caching the boolean alone.

### 4.2 `is_complete` (`poller.py:1292`)

```python
if total_players > 0 and len(goaled_ids) >= total_players:
```

Explicitly `goaled_ids`, never the per-user evaluation. Add a comment saying why: this column is
global with no user to attribute it to, and a strict definition on a release-off room would keep
it polling at 288 req/day forever. `db_check_stale_rooms` (`poller.py:2890`) remains the backstop.

### 4.3 Notification suppression (`poller.py:693` and `poller.py:823`)

Currently `if rid in finished_player_ids and not wants_finished_notifs`. Becomes a per-user
evaluation using the slot's effective definition (slot override → user default).

`_resolve_names_and_notify` (`poller.py:551`, called at `poller.py:1362`) takes
`finished_player_ids` — widen to take both fact sets.

**Known accepted risk:** under `all_checks` or `either`, a slot can qualify while the player is
still actively playing (other players auto-collecting inflates their count). Those users would
stop receiving notifications for a live slot. Mitigated by defaulting to `goal`; if complaints
surface, the fix is to AND the goal condition into the notification path only.

---

## 5. Server: API surface

### 5.1 Backward compatibility — non-negotiable

`is_finished` on the wire keeps meaning **goaled**, forever. Old Play Store clients must see
identical behavior. New facts are additive fields.

### 5.2 Payload additions

- `Player` (`rooms_routes.py:374`): add `has_all_checks`, `checks_done`, `total_locations`
- `TrackedSlotDetail` (`slots_routes.py:408`): same three
- History items (`history_routes.py:352`, `:766`, `:1088`, and the passthroughs at `:415`,
  `:1149`): add `playerHasAllChecks`

### 5.3 Preference endpoints — both need special-casing

**`slots_routes.py:154`** iterates a field list and coerces with `bool(val)`. A string enum
cannot go through that loop. Add a separate branch validating against
`VALID_FINISHED_DEFINITIONS`, allowing `None` to clear the override.

**`user_routes.py:212/218`** likewise uses `bool(data[...])`. Add a validated branch — the
existing `VALID_CHEESE_PING_PREFERENCES` handling at `user_routes.py:244` is the pattern to copy.

Also expose the new fields in the two profile responses (`user_routes.py:127` and `:168`).

---

## 6. Android

### 6.1 Evaluator twin

`android/.../data/FinishedDefinition.kt` — enum + one `evaluate()` function mirroring the Python
exactly, including the unknown→`goal` fallback for forward compatibility with server values a
given build doesn't know yet.

### 6.2 Room migration: version 23 → 24

Current `@Database version = 23` (`AppDatabase.kt:23`), migrations registered manually in the
array at `AppDatabase.kt:45-48`. Add `MIGRATION_23_24` to `Migrations.kt` following the existing
style:

```sql
ALTER TABLE history_items ADD COLUMN playerHasAllChecks INTEGER NOT NULL DEFAULT 0
```

Keep `isPlayerFinished` as-is — it already means goaled, so no rename, no churn across the many
call sites. Add the field to `HistoryItemEntity` (`HistoryItemEntity.kt:24` area) and to the
mapping sites in `HistoryRepository.kt:161`, `:256`, `:306`.

Register `MIGRATION_23_24` in the `AppDatabase.kt` array — easy to forget, crashes on upgrade.

### 6.3 Filter call sites

All four route through the evaluator:

| Site | Current |
|---|---|
| `SlotsScreen.kt:98` | `showFinished \|\| !slot.is_finished` |
| `HistoryScreen.kt:995` | `showFinished \|\| !isFinished` |
| `HistoryScreen.kt:1735` | `showFinished \|\| !isItemOwnerFinished` |
| `RecentItemsWidget.kt:259` | `showFinished \|\| !item.isPlayerFinished` |

The widget reads the stored boolean directly with no overlay (see the architectural note at
`RecentItemsWidget.kt:257`) — the migration is what makes it work, which is why the overlay
approach was rejected.

`HistoryViewModel.kt:626` (`isActuallyFinished`) and the `finishedPlayerKeys` overlay at
`HistoryViewModel.kt:126` need the same treatment, carrying both facts through instead of one
boolean.

### 6.4 Unify the two visibility toggles

`ui_show_finished` is server-synced; `slots_show_finished` (`SettingsManager.kt:23`) is local-only
and independent. Consolidate onto the server-synced one to match every other preference. Migrate
the existing local value on first run so nobody's toggle silently flips.

### 6.5 Settings UI

- Global: `SettingsScreen.kt` near the existing finished-notification toggle (~`:211`)
- Per-slot override: `SlotOverridesScreen.kt`, following the `currentValue`/`defaultValue`
  pattern at `:387-389` — but as a 4-way selector rather than a tri-state boolean
- **`applySlotSettingsToAll` (`UserViewModel.kt:924`) enumerates fields explicitly** — add
  `finished_definition` there or "copy to all slots" will silently skip it. Note that
  `suppress_connected` is already missing from that list; worth fixing in the same pass.

### 6.6 Visual states — vector icons, not emoji

`Icons.Filled.Flag` = goaled, still has items to send. `Icons.Filled.CheckCircle` = fully done.
Both take a `contentDescription`, so screen readers work and nothing depends on color alone
(`SlotsScreen.kt:338` currently uses `finishedColor`).

**Related pre-existing bug:** `remove_emojis` is notification-text-only, applied server-side at
`poller.py:3166`. The 🏁 at `SlotsScreen.kt:335` is a hardcoded client literal that ignores the
preference entirely — users who disabled emoji see it today. Moving to vector icons fixes that
here; worth sweeping the UI layer for other hardcoded emoji in the same pass.

### 6.7 Copy

Use AP-native vocabulary, not Cheese's:

- **Goaled**
- **No items left to send**
- **Goaled + no items left to send**
- **Goaled or no items left to send**

Mentioning "this is what Cheese calls done" belongs in the Discord release post — ephemeral, buys
recognition — not in durable in-app strings.

Surfacing `checks_done / total_locations` ("412/500") next to a slot makes the setting
self-explanatory: it shows *why* something is still visible.

---

## 7. Test plan

New `backend/tests/test_finished_definition.py`:

1. `evaluate_finished` truth table — 4 definitions × 4 fact combinations
2. `total_locations == 0` never yields all-checks, under every definition
3. Unknown/None definition falls back to `goal`
4. Transition detection: user A (`goal`) notified on goal; user B (`both`) not notified until
   checks complete; neither notified twice
5. `is_complete` fires on all-goaled even when no slot has all checks
6. `cached_checks_json` not written when counts are unchanged
7. `player_checks_done` entries with `team != 0` are ignored

Extend `test_db_migrations.py` for the new columns. Existing `test_notification_channels.py`
covers the suppression paths that are being restructured — run it before and after.

---

## 8. Rollout

**Phase 1 — server only, no user-visible change.** Migration, fact computation, additive API
fields, evaluator wired with everyone defaulting to `goal`. Ships independently of Play Store
review; old clients ignore the new fields. Let it run a week and sanity-check counts against a
few known rooms — particularly a release-off async and a large one, to confirm
`cached_checks_json` write volume behaves.

**Phase 2 — Android.** Room migration, evaluator, filter sites, toggle unification, settings UI,
icons.

Phase 1 is where the risk lives (poller restructuring, write volume). Phase 2 is mostly
mechanical once the facts are on the wire.

---

## 8a. Completion-fact catch-up (added after dev testing)

`has_all_checks = False` originally did double duty for "fetched, still has locations out" and
"never fetched counts for this room". Two fixes, and it is worth being precise about which covers
what -- an earlier draft of this doc got it wrong.

**Unknown is its own state.** `has_all_checks` may be `None`, and every definition degrades to
goal-only when it is. On the wire it serializes as JSON `null`, so clients get the same tri-state.
**This is what covers a completed room being un-archived**: `is_complete` is set in exactly one
place (`poller.py:1414`) and is never reset, and every room-selection query filters
`is_complete == False`, so such a room is never polled again and stays permanently unknown --
correctly falling back to goal-only.

**Gatekeeper Reason 4** covers a narrower case: a room that is still active (`is_complete` false,
not suspended) but too idle for the activity gate to open, which would otherwise sit at unknown
indefinitely. It forces one poll when the room has tracked slots and `cached_players_json` lacks
the `has_all_checks` key.

The `has_tracked_slots` guard is load-bearing: `db_process_poll_data` returns before computing
facts when a room has no active tracked slots (`poller.py:1324`), so without it those rooms would
force a fetch every cycle forever and never persist anything. The trigger self-clears after one
poll because `has_all_checks` is written unconditionally once processing reaches that point, even
on hosts that never serve `player_checks_done`. A test pins the string marker so a rename cannot
silently disable it.

## 9. Open risks

- **Transition detection is the subtle part.** Firing a finish notification twice, or never, for
  users on non-default definitions is the most likely bug. Test 4 above is the one that matters.
- **Suppression semantics under `all_checks`/`either`** — accepted, documented in §4.3.
- **Large asyncs.** `player_checks_done` carries every location ID for every player. Already
  downloaded and parsed, so no new network cost, but confirm parse time on a 200-slot room is not
  meaningfully worse than today.
- **Multi-team rooms** are out of scope and consistent with existing behavior. If anyone is
  running multi-team, finished detection is already wrong for them today.
- **Release-off rooms stop polling once everyone goals** (issue #263). Pre-existing and untouched
  here, but it interacts badly with this feature: a user who picks "Both" specifically to keep
  seeing release-off slots may find the room stops polling entirely. Worth fixing before Phase 2
  ships the setting.
