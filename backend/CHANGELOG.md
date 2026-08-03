# Backend Server Changelog

All notable changes to the **Archipelago Alerts Backend Server & API** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
