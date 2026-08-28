<!-- GENERATED FILE — do not edit by hand.
     Source of truth: backend/app/data/changelog.json
     Regenerate with: python scripts/generate_changelog.py -->

# Backend Server Changelog

All notable changes to the **Backend Server** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This file is generated from `backend/app/data/changelog.json`.

## [1.10.0] - 2026-08-28

_Game Data On Demand, And Quieter Notifications_

> **Discord Copy-Paste:**
> ```markdown
> **Server v1.10.0 is live.**
>
> 🔕 **Snooze now silences finish announcements** — last release made the “Player(s) Finished!” notification independent of your finished-slot setting, which accidentally left no way to quiet it at all. Snooze applies to it now, the same as items, hints and milestones.
>
> ✅ **Rooms that could never finish, can** — if a room’s host never reported how many locations a slot has in total, that room stayed on the polling schedule forever no matter how obviously done it was. Those now fall back to goals alone.
>
> ⚡ **Faster name loading for the app** — each game’s item and location names can now be fetched on their own and kept by the app permanently, instead of re-sending the whole room’s data every time you open a slot.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - `GET /datapackage/checksum/<checksum>` — one game's item and location ID → name tables, served with an ETag and `Cache-Control: private, max-age=31536000, immutable`. Checksums are content hashes, so clients cache the response indefinitely. Only `item` and `location` rows are served; group rows carry synthetic negative IDs from `generate_negative_id()` that share an ID space with real negative IDs (the generic world uses location -1 and -2) and are never referenced by ID in `PrintJSON`.
> - A checksum with only a `_metadata` completion marker returns 200 with empty tables rather than 404, so clients can cache the empty result.
>
> ### Changed
> - `_room_is_complete` takes `totals_known` and falls back to goal-only when a slot's `total_locations` is 0, matching the existing `checks_known` escape hatch. Previously such rooms were permanently ineligible for completion and polled until `db_check_stale_rooms` suspended them.
> - `_check_player_completion` honours snooze. `notify_finished` is deliberately not a gate on the finish announcement, so snooze was the only remaining way to quiet it and was not being checked.
> - `alembic b2e75c4a19d8` sets `needs_backfill` on revived rooms' tracked slots so the catch-up poll is silent. This was amended after 1.9.1 had already applied the migration in production, so it affects environments that had not yet run it; the rooms revived by the 1.9.1 deploy did not get it.
>
> ### Fixed
> - `playerHasAllChecks` is emitted as `null` rather than `false` in `GET /history/<room_db_id>` and `POST /history/sync` when a room's check counts were never fetched. `false` reported goaled slots as still sending.
>
> ### Notes
> - `alembic upgrade heads` required for a fresh environment. No new revision in this release; `b2e75c4a19d8` is unchanged for anyone who has already applied it.
> - Deploy before or alongside app 1.9.1. An app build hitting an older backend gets 404s per checksum, retries with backoff, then falls back to `GET /rooms/<id>/datapackage`; degraded, not broken.
> ```

### Added
- **Per-Checksum Datapackage Endpoint**: `GET /datapackage/checksum/<checksum>` returns one game's item and location ID-to-name tables, with an ETag and a long-lived immutable Cache-Control. A checksum is a content hash, so the response can be cached by the client indefinitely without revalidation. Group rows are excluded: their synthetic negative IDs share an ID space with real negative IDs, and they are never referenced by ID in room messages.

### Changed
- **Empty Datapackages Answer 200, Not 404**: A game whose datapackage is genuinely empty returns empty tables with a 200 rather than a 404, so the client can record “nothing to resolve here” permanently instead of asking again on every connect.
- **Snooze Honoured On Finish Notifications**: `_check_player_completion` now checks snooze before announcing a finish. The finished-slot preference is intentionally not an escape hatch for this notification, so without a snooze check there was no way for a user to quiet it.
- **Silent Backfill For Rooms Revived From Here On**: The room revival migration sets `needs_backfill` on the tracked slots it revives, so the first poll after revival ingests the backlog instead of notifying on every item sent while the room was dark. This was added after the migration had already run in production, so it applies to environments that had not yet applied it, not to the rooms revived by the 1.9.1 deploy.

### Fixed
- **Rooms With Unknown Location Totals Never Completed**: `has_all_checks` is `checks_done >= total_locations`, so a slot whose `total_locations` is 0 -- the sentinel for a static-tracker fetch that returned no `player_locations_total` -- could never satisfy it, and the re-setup guard only tested that the key was present. `_room_is_complete` now takes `totals_known` and falls back to goal-only, matching the existing `checks_known` behaviour.
- **History Reported Unknown Check State As False**: `playerHasAllChecks` was emitted as `false` for rooms whose check counts had never been fetched, which is categorically different from a slot that genuinely still has checks out and made goaled slots look like they were still sending. It is now `null` in that case, which every finished definition already handles by falling back to goal-only.

---

## [1.9.1] - 2026-08-20

_Release-Off Rooms Keep Polling_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Server v1.9.1**
>
> **Fixed**
> • **Release-off rooms keep updating**: a room where everyone has goaled but items are still being sent no longer stops polling. Previously the last goal marked the room complete and notifications went silent for a room people were still playing. Rooms already stuck this way have been revived.
> • **You always hear about a finish**: the "Player(s) Finished!" notification now arrives even with "Keep notifying finished slots" turned off. That setting only controls the items and hints that come *after* a slot finishes.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Changed
> - The "Player(s) Finished!" notification is no longer gated on `notify_finished`. That preference now governs only the item and hint stream for a slot that has already finished, which is what the in-app copy already described. Users with the preference off will begin receiving finish notifications.
>
> ### Fixed
> - `is_complete` now requires all-goaled **and** all-drained (#263). With release disabled, goaling leaves a player's locations unchecked while they keep playing so others still receive items; marking the room complete dropped it from every poll query permanently, and the column is never reset. Falls back to goal-only when check counts are unknown, so hosts that do not serve `player_checks_done` are unaffected.
> - Migration `b2e75c4a19d8` performs a one-off revival of rooms already stuck in that state, scoped to unsuspended rooms with remote activity inside the 30-day stale window. Nothing would ever have polled them again otherwise.
> ```

### Changed
- **Finish Notifications Are No Longer Optional**: The finish announcement is no longer gated on the finished-slot notification preference. That preference governs the item and hint stream for a slot that has already finished, which is what the in-app description always said it did. Anyone with it switched off will start seeing finish notifications they were not getting before.

### Fixed
- **Completion Requires An Empty Slot, Not Just A Goal**: A room is marked complete only when every slot has both reached its goal and run out of checks to send. Completion permanently removes a room from every polling query and is never undone, so firing it early took the room offline for everyone tracking it. Rooms on hosts that do not report check counts keep the previous goal-only behavior rather than polling indefinitely.
- **One-Time Repair For Rooms Marked Complete Too Early**: A migration revives rooms that were marked complete while still holding items, limited to rooms that are not suspended and had activity within the last thirty days. Rooms that really were finished are re-marked complete on their next poll, and genuinely abandoned ones are caught by the existing thirty-day inactivity check.

---

## [1.9.0] - 2026-08-18

_Groundwork for User-Defined “Finished”_

> **GitHub Release Copy-Paste:**
> ```markdown
> Server-side groundwork for user-configurable "finished" semantics. **No user-visible behavior change**: every account defaults to `goal`, which is what the app has always done. The setting UI ships separately with the Android client (Phase 2).
>
> ### Added
> - **Two independent completion facts per slot.** `is_finished` continues to mean ClientStatus 30 (goal) and is unchanged on the wire, so older app builds behave identically. A new `has_all_checks` is derived from `player_checks_done` in `/api/tracker/<id>` compared against `player_locations_total` from `/api/static_tracker/<id>` — both already fetched and parsed each poll, so no additional Archipelago requests. These diverge only when a room has release disabled, which is the case this exists for.
> - **`finished_definition` preference.** `users.finished_definition_default` (default `goal`) with a nullable `user_tracked_slots.finished_definition` override. Accepted values: `goal`, `all_checks`, `both`, `either`. Validated separately from the boolean preference loops in `slots_routes` and `user_routes`, which coerce with `bool()` and would otherwise mangle an enum string. Unrecognized values fall back to `goal` rather than raising.
> - **Per-slot check counts.** `tracked_rooms.cached_checks_json` holds `{slot_id: checks_done}`. Deliberately a separate column from `cached_players_json`, which is TOASTed past roughly 15 slots and is only rewritten when a flag flips — folding a per-poll counter into it would rewrite the whole TOAST value every poll. Written only when a count actually changes.
> - **Additive API fields**: `has_all_checks`, `checks_done` and `total_locations` on the players and tracked-slot payloads, `playerHasAllChecks` on history items, and `finished_definition` / `finished_definition_default` on the slot and profile payloads. `has_all_checks` and `checks_done` serialize as `null` when a room's counts have never been fetched, which is distinct from `false`.
> - Migration `c4d21a7f9b83`.
>
> ### Changed
> - **Finish-notification transitions are now evaluated per user.** Because the definition is per-account, "just became finished" differs between two users tracking the same slot and can no longer come from one shared flag flipping. Both facts are cached per slot and each user's false→true edge is computed from their own previous-versus-current evaluation.
> - **Notification suppression** for finished slots evaluates the effective definition (slot override, then account default) instead of a single shared set.
> - **`TrackedRoom.is_complete` remains goal-only** and is explicitly not affected by any user preference. It gates whether a room is polled at all, it is a single global column with no user to attribute it to, and a stricter definition would keep release-off rooms polling indefinitely.
> - **Gatekeeper forced poll** when a room has tracked slots but no cached completion facts, so rooms too idle for the activity gate to open still populate their counts once. Self-clearing after a single poll, including on hosts that never serve `player_checks_done`.
>
> ### Notes
> - `player_checks_done` entries carry a `team`; filtered to team 0, consistent with the existing `player_status` parsing. Multi-team rooms remain unsupported, as before.
> - `total_locations` of 0 is the failed-static-fetch sentinel and never counts as all-checks.
> - Validated against a live release-off room with staggered goals: see #260.
> - Adds 39 tests in `backend/tests/test_finished_definition.py`.
> ```

### Added
- **Separate Goal and Check-Completion Tracking**: Completion is now two independent facts per slot rather than one. Goal status still comes from the Archipelago client status; “no items left to send” is derived by comparing each slot's completed locations against its total. Both come from tracker data the poller already downloads, so this costs no extra requests to Archipelago.
- **Configurable Finished Definition (Not Yet Exposed)**: Accounts and individual tracked slots can now carry a preference for what counts as finished — goal, all checks sent, both, or either — with a per-slot value overriding the account default. Every existing and new account is set to goal, which is the behavior the app has always had. No interface reads or writes this yet.

### Changed
- **One-Time Catch-Up for Existing Rooms**: Rooms tracked before this release have no check counts recorded. Each one fetches them once shortly after the update so the data is ready when the setting ships. Rooms that never get the chance — finished asyncs that are no longer polled — are treated as unknown rather than incomplete, so their slots keep reading as finished exactly as they do today.

---

## [1.8.2] - 2026-08-18

_Milestone Group Edits & Migration Hardening_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Backend v1.8.2 Released!**
>
> **Fixes**
> • **Milestone Group Edits Now Save**: Editing a milestone group reported success and then showed the old items again — the change was never written. Your edits now stick.
> • **Steadier Startup Migrations**: Migration cleanup on startup is stricter about which records it prunes, and now reports problems instead of quietly skipping them.
>
> Server-side only — no app update needed.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Fixed
> - **Milestone group edits were silently discarded**: `PUT /rooms/<id>/slots/<slot_id>/threshold-groups/<group_id>` returned `200 {'message': 'Threshold group updated'}` without committing. The route relied on the implicit `session.commit()` in `handle_db_errors`, which cannot fire for it: `token_required` calls `Session.remove()` before the route body runs, so the decorator holds a different session than the one the route mutates, and its closing `Session.remove()` rolled the real transaction back. The route now commits explicitly, and flushes the `delete-orphan` cascade between `items.clear()` and the re-append so an item removed and re-added in one edit does not collide with its own outgoing row. Adds 9 regression tests in `backend/tests/test_threshold_group_crud.py` that re-read over HTTP rather than through the ORM session. See #258.
> - **Alembic head reconciliation hardening**: `_reconcile_overlapping_heads` no longer wraps the whole routine in one broad `except`. A missing `alembic_version` table (fresh database) is now distinguished from a real failure; revisions with no file left in the tree are left in place with a warning instead of being swallowed; ancestor walking passes `include_dependencies=False` so cross-branch dependency edges are not mistaken for ancestry and wrongly pruned; and each `DELETE` is isolated so one failure cannot abort the rest.
> ```

### Fixed
- **Milestone Group Edits Discarded**: Saving an edited milestone group returned success without writing the change, so the app re-read the old items. The update route relied on an implicit commit that could never fire for it, because the session it mutated was not the session being committed. It now commits explicitly, and removing and re-adding the same item in one edit no longer collides with its own outgoing row.
- **Migration Reconciliation Hardening**: Startup reconciliation of overlapping `alembic_version` entries no longer hides every failure behind one broad `except`. A missing version table on a fresh database is distinguished from a real error, revisions with no file left in the tree are kept in place with a warning rather than swallowed, ancestor walking ignores cross-branch dependency edges so unrelated revisions are not wrongly pruned, and each delete is isolated so one failure cannot abort the rest.

---

## [1.8.1] - 2026-08-17

_Automatic Alembic Head Reconciliation_

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Fixed
> - **Self-healing Alembic startup migration**: `db_migrations.py` now detects and reconciles overlapping version entries in `alembic_version` prior to calling `alembic upgrade heads`. If historical branch heads were linearized or re-parented after being applied, redundant ancestor records are pruned automatically under the migration advisory lock.
> ```

### Fixed
- **Self-Healing Migration Startup**: Automatic migration on startup now reconciles overlapping version entries in `alembic_version` under the advisory lock. If branch heads were previously applied and then linearized or re-parented, redundant ancestor records are pruned before running `alembic upgrade heads`.

---

## [1.8.0] - 2026-08-17

_Milestone Progress API & Startup Migrations_

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - **Per-requirement milestone progress**: `GET /rooms/<id>/slots/<slot_id>/threshold-groups` now returns an `acquired` count per requirement. Item groups are expanded against `item_name_groups_json` and summed over `SlotItemCount` — the same data the milestone trigger reads, so displayed progress matches what fires the notification. A requirement whose name or datapackage cannot be resolved is omitted rather than reported as `0`, and any failure yields `acquired: null` without breaking the definitions fetch.
>
> ### Changed
> - **Schema migrations run on startup**: `create_app` runs `alembic upgrade heads` for Postgres under a session-scoped advisory lock, so the API and poller cannot race. This replaces the manual `docker exec ... alembic upgrade heads` step — a container restart can now migrate.
> - **Dev containers mount the running package**: `docker-compose.dev.yml` mounts `./backend/app` at `/app/app` instead of `./backend` at `/app/backend` (an unused second copy), so backend edits no longer require an image rebuild.
> ```

### Added
- **Milestone Progress in the Threshold Groups API**: GET /rooms/<id>/slots/<slot_id>/threshold-groups returns an `acquired` count per requirement. Item groups are expanded against `item_name_groups_json` and summed over `SlotItemCount`, the same data the milestone trigger reads, so reported progress matches what fires the notification. A requirement whose name or datapackage cannot be resolved is omitted rather than reported as 0, and any failure yields a null count without breaking the definitions fetch.

### Changed
- **Automatic Schema Migration on Startup**: create_app runs `alembic upgrade heads` for Postgres under a session-scoped advisory lock, so the API and poller cannot race each other. This replaces the manual `docker exec ... alembic upgrade heads` step; a container restart can now migrate the database.
- **Dev Containers Mount the Running Package**: docker-compose.dev.yml mounts ./backend/app at /app/app instead of ./backend at /app/backend, which was an unused second copy that left the real code baked into the image. Backend edits no longer require an image rebuild.

---

## [1.7.1] - 2026-08-14

_FCM Android Channel Payload Metadata_

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - **Backend FCM Channel Metadata**: The backend notification service now attaches `AndroidConfig.AndroidNotification.channel_id` and payload metadata to route notifications to the correct channel (`channel_progression`, `channel_non_progression`, `channel_hints`, `channel_general`) for both foreground and background delivery.
> ```

### Added
- **FCM Notification Channel Mapping**: Mapped event types (progression, non-progression, hints, milestones, player finishes) to Android Notification Channel IDs with AndroidConfig support.

---

## [1.7.0] - 2026-08-13

_Milestone Templates API & Database Migration_

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - **Milestone Templates API**: New user-scoped CRUD endpoints (`GET /milestone-templates`, `POST /milestone-templates`, `PUT /milestone-templates/<id>`, `DELETE /milestone-templates/<id>`) for saving and managing milestone threshold group templates.
> - **Database Migration**: Added Alembic migration `a3f8c91d2e47_add_milestone_templates.py` introducing `milestone_templates` and `milestone_template_items` tables with cascade deletion and game/user indexes.
>
> ### Fixed
> - **What's New Route Alignment**: Explicitly registered `/api/whats_new` and `/api/whats_new/latest` routes and aligned highlight data models with client expectations.
> ```

### Added
- **Milestone Templates CRUD Endpoints**: New user-scoped routes (GET, POST, PUT, DELETE /milestone-templates) supporting game-specific templates with duplicate name validation and cascade deletion.
- **Milestone Template Database Models**: Added MilestoneTemplate and MilestoneTemplateItem models backed by Alembic migration a3f8c91d2e47.

### Fixed
- **What's New Endpoint Route Alignment**: Fixed /api/whats_new route prefixing and aligned release highlights data structures with the Android client.

---

## [1.6.23] - 2026-08-03

_Server-Side Ignore/Whitelist Filtering_

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Fixed
> - **Server-Side Ignore/Whitelist Computation**: Extracted ignore/whitelist matching (including checksum-scoped item-group resolution) into a shared `backend/app/services/filtering_service.py`, used by both the poller and the history/hint endpoints. History and hint endpoints now return `isIgnored`/`isWhitelisted` per item and hint, fixing item-group rules having no client-visible effect and hint filtering ignoring the game-specific scope of rules.
> ```

### Fixed
- **Item Group Filtering Computed Server-Side**: Item-group ignore/whitelist rules are now evaluated on the server and sent to the app directly, fixing group rules that previously had no effect in History.
- **Per-Game Hint Filtering Fix**: Hint filtering now correctly respects each rule's game scope instead of applying it across all your games.

---

## [1.6.22] - 2026-08-03

_Cheese Tracker Notes & Statuses API_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Backend v1.6.22 Released!**
>
> **New: Cheese Tracker Notes & Statuses**
> • **Per-Slot State API**: `GET /api/user/tracked_slots` now includes a `cheese` object per slot (notes, progression/completion status, ping, last checked, ownership).
> • **Slot Editing**: New `PUT /rooms/<room_db_id>/slots/<slot_id>/cheese` to edit notes/status/ping and refresh "Last Checked" ("Still BK"), with ownership checks and optimistic-conflict handling.
> • **Default Ping Preference**: `cheese_default_ping` is now applied at claim time, fixing the ping preference always defaulting to "Never".
> ```

### Added
- **Cheese Slot State (read)**: get_user_tracked_slots parses the room's cached Cheese Tracker data and attaches a per-slot cheese object (game_id, notes, progression_status, completion_status, discord_ping, last_checked, is_mine, global_ping_policy) for Cheese-connected users.
- **Cheese Slot State (write)**: New synchronous PUT /rooms/<room_db_id>/slots/<slot_id>/cheese endpoint. Validates enum values, re-fetches the tracker, enforces ownership, applies partial updates, stamps last_checked for BK/Soft BK and Still BK, sends x-if-owner-is as a conflict guard, and splices the authoritative response back into the room cache.
- **User.cheese_default_ping**: New nullable column (Alembic a1c7e9f4b2d0) exposed on the user profile and settable via PUT /users/me/preferences.

### Changed
- **Claim-Time Ping Default**: send_state in api_cheese.py now applies the user's cheese_default_ping when claiming a slot, and aligns unclaim behavior with Cheese Tracker's web UI (availability to open, ping to never).

### Fixed
- **Ping Preference Stuck on Never**: Newly claimed slots now honor the user's chosen default ping preference instead of always defaulting to Never.

---

## [1.6.21] - 2026-08-03

_Tracked Slot Item Count Aggregation_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Backend v1.6.21 Released!**
>
> **Improvements & Fixes**
> • **Tracked Slot Item Count Payload**: Surfaced total item counts per slot in `GET /api/user/tracked_slots` to drive client-side progress calculation.
> • **Landing Page Version Syncing**: Fixed landing page version badges to resolve from `changelog.json` in production containers.
> ```

### Changed
- **Tracked Slot Item Count Aggregation**: Updated get_user_tracked_slots query in slots_routes.py to aggregate item_count per slot in the JSON response payload.
- **Website Version Display Alignment**: Updated get_android_version() in utils.py to check changelog.json so the landing page version badges stay aligned with release notes across all environments.

---

## [1.6.19] - 2026-07-31

_Poller CPU & Resource Throttling_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Backend v1.6.19 Released!**
>
> **Improvements & Fixes**
> • **Poller CPU & Resource Throttling**: Throttled concurrent room processing cycles to smooth CPU spikes.
> • **Cycle Jitter & Staggering**: Added random jitter to poller sleep intervals to prevent wave synchronization.
> • **SQLAlchemy Pool Tuning**: Optimized PostgreSQL connection pool size and recycling for high concurrency.
> • **Datapackage Cache Locking**: Prevented concurrent autocomplete requests from redundant datapackage fetches.
> ```

### Changed
- **Poller CPU & Resource Throttling**: Introduced db_process_semaphore (limit=3) to throttle concurrent synchronous database processing during room poll cycles, smoothing CPU usage and eliminating high-load CPU spikes.
- **Cycle Jitter & Staggering**: Added per-cycle ±30s random jitter to the 5-minute poller sleep interval and expanded initial room stagger (1–60s) to prevent room polling tasks from re-synchronizing into waves over time.
- **SQLAlchemy Connection Pool Tuning**: Configured pool settings (pool_size=10, max_overflow=5, pool_recycle=1800, pool_pre_ping=True) for PostgreSQL in production to avoid connection pool exhaustion under load.
- **Docker Compose CPU & Memory Limits**: Defined resource limits and reservations for api and poller containers to guarantee API CPU availability (0.4 vCPU reserved for API, poller capped at 1.0 vCPU) on 2 vCPU VMs.
- **Per-Game Datapackage Cache Lock**: Added an in-memory per-game asyncio lock in game_routes.py to prevent concurrent autocomplete queries from redundantly fetching game datapackages.

### Fixed
- **Database Healthcheck Environment Escaping**: Escaped PostgreSQL env vars ($$POSTGRES_USER and $$POSTGRES_DB) in docker-compose.yml healthcheck so credentials resolve from the container's environment dynamically across dev, UAT, and prod.

---

## [1.6.18] - 2026-07-30

_GET /api/whats_new Endpoint & System Improvements_

### Added
- **GET /api/whats_new Endpoint**: Backend API to dynamically fetch release notes and patch highlights with target filtering (app, server, all).
- **Item & Group Whitelist Schema**: Introduced UserWhitelistItem backend model and database migrations.

### Changed
- **Native item_index Preservation**: Backend poller now logs and orders received items using Archipelago's native item_index sequence.
- **Database Performance**: Added composite performance indexes for history queries and room subscription polling.

---

## [1.6.14] - 2026-06-24

_Server Release v1.6.14_

### Fixed
- **Milestone Groups Optimizations**: Improved the backend process that supplies items and item_groups for the Milestone Group builder.
