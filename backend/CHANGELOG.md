# Backend Server Changelog

All notable changes to the **Archipelago Alerts Backend Server & API** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.22] - 2026-08-03

> **Discord Copy-Paste Format:**
> ```markdown
> **Archipelago Alerts Backend v1.6.22 Released!**
> 
> **New: Cheese Tracker Notes & Statuses**
> • **Per-Slot State API**: `GET /api/user/tracked_slots` now includes a `cheese` object per slot (notes, progression/completion status, ping, last checked, ownership).
> • **Slot Editing**: New `PUT /rooms/<room_db_id>/slots/<slot_id>/cheese` to edit notes/status/ping and refresh "Last Checked" ("Still BK"), with ownership checks and optimistic-conflict handling.
> • **Default Ping Preference**: `cheese_default_ping` is now applied at claim time, fixing the ping preference always defaulting to "Never".
> ```

### Added
- **Cheese Slot State (read)**: `get_user_tracked_slots` in `slots_routes.py` parses the room's cached Cheese Tracker data and attaches a per-slot `cheese` object (`game_id`, `notes`, `progression_status`, `completion_status`, `discord_ping`, `last_checked`, `is_mine`, `global_ping_policy`) for Cheese-connected users.
- **Cheese Slot State (write)**: New synchronous `PUT /rooms/<room_db_id>/slots/<slot_id>/cheese` endpoint. Validates enum values, re-fetches the tracker, enforces ownership, applies partial updates, stamps `last_checked` for BK/Soft BK and "Still BK", sends `x-if-owner-is` as a conflict guard, and splices the authoritative response back into the room cache.
- **`User.cheese_default_ping`**: New nullable column (Alembic `a1c7e9f4b2d0`) exposed on the user profile and settable via `PUT /users/me/preferences`.

### Changed
- **Claim-Time Ping Default**: `send_state` in `api_cheese.py` now applies the user's `cheese_default_ping` when claiming a slot, and aligns unclaim behavior with Cheese Tracker's web UI (availability → `open`, ping → `never`).

### Fixed
- **Ping Preference Stuck on "Never"**: Newly claimed slots now honor the user's chosen default ping preference instead of always defaulting to "Never".

---

## [1.6.21] - 2026-08-03

> **Discord Copy-Paste Format:**
> ```markdown
> **Archipelago Alerts Backend v1.6.21 Released!**
> 
> **Improvements & Fixes**
> • **Tracked Slot Item Count Payload**: Surfaced total item counts per slot in `GET /api/user/tracked_slots` to drive client-side progress calculation.
> • **Landing Page Version Syncing**: Fixed landing page version badges to resolve from `changelog.json` in production containers.
> ```

### Changed
- **Tracked Slot Item Count Aggregation**: Updated `get_user_tracked_slots` query in `slots_routes.py` to aggregate `item_count` per slot in the JSON response payload.
- **Website Version Display Alignment**: Updated `get_android_version()` in `utils.py` to check `changelog.json` so the landing page version badges stay aligned with release notes across all environments.

---

## [1.6.19] - 2026-07-31

> **Discord Copy-Paste Format:**
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
- **Poller CPU & Resource Throttling**: Introduced `db_process_semaphore` (limit=3) to throttle concurrent synchronous database processing during room poll cycles, smoothing CPU usage and eliminating high-load CPU spikes.
- **Cycle Jitter & Staggering**: Added per-cycle ±30s random jitter to the 5-minute poller sleep interval and expanded initial room stagger (1–60s) to prevent room polling tasks from re-synchronizing into waves over time.
- **SQLAlchemy Connection Pool Tuning**: Configured pool settings (`pool_size=10`, `max_overflow=5`, `pool_recycle=1800`, `pool_pre_ping=True`) for PostgreSQL in production to avoid connection pool exhaustion under load.
- **Docker Compose CPU & Memory Limits**: Defined resource limits and reservations for `api` and `poller` containers to guarantee API CPU availability (0.4 vCPU reserved for API, poller capped at 1.0 vCPU) on 2 vCPU VMs.
- **Per-Game Datapackage Cache Lock**: Added an in-memory per-game asyncio lock in `game_routes.py` to prevent concurrent autocomplete queries from redundantly fetching game datapackages.

### Fixed
- **Database Healthcheck Environment Escaping**: Escaped PostgreSQL env vars (`$$POSTGRES_USER` and `$$POSTGRES_DB`) in `docker-compose.yml` healthcheck so credentials resolve from the container's environment dynamically across dev, UAT, and prod.

---

## [1.6.18] - 2026-07-30

### Added
- **`GET /api/whats_new` Endpoint**: Backend API to dynamically fetch release notes and patch highlights with target filtering (`app`, `server`, `all`).
- **Item & Group Whitelist Schema**: Introduced `UserWhitelistItem` backend model and database migrations.

### Changed
- **Native `item_index` Preservation**: Backend poller now logs and orders received items using Archipelago's native `item_index` sequence.
- **Database Performance**: Added composite performance indexes for history queries and room subscription polling.

---

## [1.6.14] - 2026-06-24

### Fixed
- **Milestone Groups Optimizations**: Improved the backend process that supplies items and item_groups for the Milestone Group builder.
