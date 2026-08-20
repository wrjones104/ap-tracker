# User-Defined "Finished" — Implementation Plan

**Status:** Phase 1 (server) complete, tested, and validated against a live release-off room
(PR #260). Phase 2 (Android) implemented, along with issues #261, #262, #263, and #268 --
see §10 for what changed relative to this plan.
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

Use AP-native vocabulary, not Cheese's. The community says "all checks" for a world with
nothing left to send, so the options use that term directly:

- **Goaled**
- **All checks**
- **Goaled + all checks**
- **Goaled or all checks**

Each option's description unpacks the jargon for anyone who has not met it yet -- "all
checks" is not literally "this player did all their own checks", since another player
collecting raises the count too.

The setting is labelled **"Finished means"**, which reads as a sentence with its value
("Finished means: goaled or all checks") and is short enough not to crowd the row.

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
- ~~**Release-off rooms stop polling once everyone goals** (issue #263).~~ Fixed before Phase 2
  shipped the setting, as this section recommended. See §10.1.

---

## 10. Phase 2 as built

Phase 2 shipped together with the four issues that turned out to touch the same code.

### 10.1 Issue #263 -- release-off rooms stopping polling (server)

`is_complete` now requires all-goaled **and** all-drained, extracted into
`_room_is_complete` (`poller.py:657`) so the condition is testable rather than inline.

When `checks_known` is false -- a host that never serves `player_checks_done` -- it falls
back to goal-only. Requiring a fact the host cannot supply would keep those rooms polling
until `db_check_stale_rooms` suspends them, for no correctness gain.

Rooms already stuck are unreachable by any code path, since nothing will ever poll them
again, so migration `b2e75c4a19d8` revives them once. Scope is deliberately narrow: not
suspended, and remote activity inside the 30-day stale window. Rooms cached before the
completion facts existed carry no `has_all_checks` key and are revived too -- one poll
recomputes the facts and immediately re-completes the room if it really was drained.

This had to land before the setting ships: a user picking "Both" specifically to keep
release-off slots visible would otherwise find the room stopped polling entirely.

### 10.2 Getting definitions to the widgets

The plan did not settle how per-slot definitions reach code with no ViewModel. They are
mirrored into the same SharedPreferences file the widgets already read for view toggles
(`FinishedDefinitionStore`) -- the global default as a string, the overrides as a small
JSON map, rewritten wholesale after every tracked-slot fetch.

Mirrored rather than denormalized onto each history row: changing the setting re-filters
everything already cached on the next read, with no table rewrite and no resync.

`FinishedDefinitionStore.resolverFlow` and `ShowFinishedPreference` are process-wide
holders rather than per-ViewModel state. Two independent flows over the same key drift the
moment one screen writes -- changing the definition in Settings would leave an already
loaded History screen filtering on the old one until it happened to refetch.

### 10.3 Issue #261 -- fixed structurally, not just patched

Adding `finished_definition` to `UpdateSlotPrefsRequest` would have reproduced #261
immediately: Retrofit uses `serializeNulls()` and the server keys off field *presence*, so
any field a caller omits arrives as an explicit null and clears that override.

Both write paths now build the request from one `TrackedSlotDetail.toPrefsRequest()`
extension instead of enumerating fields separately. Adding a preference is one edit, and
"copy to all slots" cannot silently skip it again.

### 10.4 Issue #262 -- vector icons

All four hardcoded 🏁 literals are gone. `remove_emojis` keeps its notification-only
meaning -- vector icons are not emoji, they render consistently, and they carry a
`contentDescription`, so nothing depends on color alone.

The history row uses `InlineTextContent` rather than a leading icon in a Row, which keeps
the existing inline text flow exactly. `MilestonesWidget`'s 🚩 was left alone: it has its
own per-widget config toggle and is outside #262's scope.

### 10.5 Issue #268 -- milestone widget

`cached_tracked_slots` gained `isFinished` and `hasAllChecks`, so
`MilestonesRepository.loadSnapshot` can filter offline against the user's own definition.
This is why the Room migration adds columns to two tables rather than one.

### 10.6 Toggle unification (§6.4)

`slots_show_finished` is retired. `SettingsManager` still exposes the flow, read once so
`ShowFinishedPreference.migrateLegacyValue` can carry the user's choice onto the unified
key; the setter is gone so the two cannot diverge again.

### 10.7 Deviations from §6.2

The history column is `INTEGER` **nullable**, not `INTEGER NOT NULL DEFAULT 0` as drafted.
Unknown is a real third state (§8a) and collapsing it into false would make goaled slots
reappear for users on stricter definitions. Existing rows correctly read as unknown until
the next sync.

### 10.8 Testing

`FinishedDefinitionTest` mirrors the Python truth table in
`backend/tests/test_finished_definition.py`. The two evaluators disagreeing is not
cosmetic: the server suppresses notifications for slots it considers finished while the
client decides what to show, so drift means either a hidden slot that still notifies or a
visible slot that has gone silent.

Server side, `TestRoomIsComplete` covers the #263 condition and `TestUndrainedRoomRevival`
covers the migration's revival predicate.

### 10.9 Settings row layout

Both dropdown-backed settings share `SettingsDropdownRow`. The selected value gets its own
full-width line under the title instead of sitting beside it in a button.

Trailing-value layouts are fine for short values, but these are phrases, and a long one
crushes the label into a narrow ragged block -- "Counts as finished" was wrapping to two
lines to make room for "Goaled or no items left to send". Giving the value a line costs no
vertical space (the wrapped version was taller) and stops the layout depending on which
option happens to be selected.

`DateFormatPreset` gained a `sample` property so the same row can show the preset name as
the value and the live example as the description. `label` still carries both, and the
picker keeps using it -- seeing the format is the whole point when choosing.

### 10.10 notify_finished no longer silences the finish itself

The "Player(s) Finished!" announcement now fires regardless of `notify_finished`
(`poller.py:424`). The preference governs only the item and hint stream for a slot that has
already finished -- the two suppression checks in `_resolve_names_and_notify`.

The old behavior silenced both, which meant a user who turned the preference off to stop
the ongoing noise after a slot goaled also never learned that it had. The one-off event and
the ongoing stream are different things, and only the second is what anyone is trying to
turn off.

Worth noting the in-app copy already described the new behavior -- "Notify for events
*after* a slot has finished" -- so this brought the code in line with what the setting
claimed, rather than changing the contract. The label is now "Keep notifying finished
slots", with the description saying outright that the finish notification always arrives.

The transition edge is untouched: the announcement still fires exactly once, on the
false -> true edge of the user's own evaluation. `test_finish_announcement_still_fires_once_only`
pins that, since removing a gate from inside a loop is an easy way to turn a one-off into a
repeat.

### 10.11 A finished room must not vanish from the slots list

The slots list dropped a room entirely once every one of its slots was filtered out
(`mapNotNull` in `SlotsScreen.kt`). With finished slots hidden, a room disappeared the
moment its last slot completed. The Rooms tab still listed it, so it looked like the app
had half-lost the room.

Pre-existing, but this work made it far easier to reach: more slots now correctly read as
finished, and rooms actually survive to a fully-complete state instead of being archived
first.

The fix splits the two filters, which were never equivalent:

- **Search** emptying a room still removes it. That is what searching means.
- **The finished filter** emptying a room never removes it. The room keeps its header and
  gains an inline "N finished slots hidden in this room / Show" row.

That row appears for any expanded room with hidden slots, not only rooms with nothing left
to show. Restricting it to the all-hidden case made the count read as a screen-wide total --
there was no visible slot list to read it against, and with two rooms each hiding a slot
the one row shown said "1" when two were hidden. It is worded "in this room" for the same
reason.

A room leaving the list should only ever be a user action -- archive or delete.

Each room header now also carries a permanent `RoomSlotProgress` line -- a proportional bar
plus "5 active - 3 finished" -- under the alias and host. The old count badge could not do
this job: it only ever described what was on screen, so it could not tell the user that
hidden slots existed. Laid out under the name rather than beside it, because a trailing
indicator competes with the alias for width and truncates long room names.

`buildRoomSlotGroups` is extracted from the composable specifically so the search/finished
asymmetry is covered by tests (`RoomSlotGroupTest`). Collapsing the two filters back into
one is the regression that caused this bug, and it is an easy one to reintroduce while
tidying.

### 10.12 Legacy toggle migration must not invent a false

`SettingsManager.slotsShowFinished` defaulted to `false` while the unified `ui_show_finished`
defaults to `true`, and the flow collapsed "never set" into that false. The migration would
then carry a phantom `false` onto the unified key and silently hide finished slots for users
who had never touched the old toggle -- exactly the flip the migration exists to prevent.

The flow is now `Flow<Boolean?>` and the migration no-ops on null.
