# Archipelago Alerts - Project Summary for LLMs

This document is intended to help an LLM or AI assistant understand the structure, purpose, and key components of the **Archipelago Alerts** project.

## Project Overview

**Archipelago Alerts** (formerly AP Tracker) is a tool for tracking Archipelago multiworld games. It allows users to subscribe to rooms, track specific players, and receive push notifications for in-game events (items received, hints found, etc.).

The system consists of two main parts:
1.  **Backend:** A Python Flask application that handles API requests, authenticates users (Discord), manages the database, and polls Archipelago servers for game updates.
2.  **Android App:** A native Android application (Kotlin/Jetpack Compose) that serves as the frontend client.

## Directory Structure

*   `backend/app/data/changelog.json`: **Single source of truth** for all release notes and versions (hand-edited). Two newest-first arrays: `app_releases` (Android) and `server_releases` (Backend). Everything else — the two `CHANGELOG.md` files, the landing-page version badges, and `/api/whats_new` — is derived from it.
*   `android/CHANGELOG.md` / `backend/CHANGELOG.md`: **Generated** (do not hand-edit) from `changelog.json` by `scripts/generate_changelog.py`.
*   `architecture.md`: **[Detailed Architecture Document](architecture.md)** — Explains system design, Mermaid diagrams, Redis event queues, service engines, PostgreSQL composite indexes, and Docker container topology.
*   `scripts/`: Contains developer helper scripts including `generate_changelog.py`.
*   `backend/`: Contains the Python backend code.
    *   `app/`: Main application package.
        *   `routes/`: Domain-driven REST API blueprint modules (`auth_routes.py`, `user_routes.py`, `rooms_routes.py`, `slots_routes.py`, `thresholds_routes.py`, `history_routes.py`, `game_routes.py`, `whats_new_routes.py`).
        *   `data/`: Static app resources including `changelog.json` for serving `GET /api/whats_new`.
        *   `services/`: Background service modules (`poller_service.py`, `redis_service.py`, `datapackage_service.py`, `threshold_service.py`, `notification_service.py`, `cheese_service.py`, `retention_service.py`).
        *   `api.py`: Composite entry router maintaining 100% backward compatibility.
        *   `auth.py`: Authentication logic (Discord OAuth2, JWT).
        *   `poller.py`: Background poller supervisor and room setup engine.
        *   `models.py`: SQLAlchemy database models & composite performance indexes.
        *   `api_cheese.py`: Integration logic for "Cheese Tracker".
        *   `templates/`: HTML templates for simple web pages (Privacy Policy, Delete Account).
    *   `alembic/`: Database migration scripts.
    *   `run.py`: Entry point for the Flask app.
    *   `requirements.txt`: Python dependencies.
*   `android/`: Contains the Android application code.
    *   `app/src/main/java/com/jones/aptracker/`: Root package for Kotlin source code.
        *   `network/`: API communication, Data Transfer Objects (DTOs), and session management. Contains `ApiService.kt` (Retrofit endpoints), `TokenManager.kt` (secure token storage), DAOs (Data Access Objects), and entity models.
        *   `database/`: Local data persistence. Contains `AppDatabase.kt` (Room Database setup).
        *   `repository/`: Centralized data fetching strategy mediating between local `database` and remote `network`.
        *   `ui/`: The UI layer organized into features.
            *   Key Screens: `RoomsScreen.kt` (tracked rooms list), `ActivityFeedScreen.kt` (recent notifications/events), `ProfileScreen.kt` (user info & login state), `SettingsScreen.kt` (app preferences).
            *   State management is handled by corresponding ViewModels (e.g., `RoomsViewModel.kt`, `MainViewModel.kt`).
    *   `app/src/main/res/`: Android resources (layouts, strings, etc.).

## Key Components & Technologies

### Android App

*   **Architecture:** Follows the MVVM (Model-View-ViewModel) architectural pattern combined with the Repository pattern to ensure clean separation of concerns between UI, business logic, and data layers.
*   **UI Framework:** Developed entirely using Jetpack Compose for declarative UI.
*   **Networking:** Retrofit for REST API requests with OkHttp interceptors (`AuthInterceptor.kt`) for handling JWT authentication headers.
*   **Local Storage:**
    *   Room Database (`androidx.room`) for caching application data locally.
    *   `EncryptedSharedPreferences` for securely storing JWT authentication tokens (`TokenManager.kt`).
*   **Authentication:** Integrates with Discord OAuth2 using the `net.openid.appauth` library via deep-linking schemes.

### Backend & Production Infrastructure

*   **Hosting & Topology:** Deployed on a Google Cloud Platform (GCP) Virtual Machine using PostgreSQL for UAT and Production environments (SQLite is strictly for local dev). Redis is deployed alongside PostgreSQL for caching and background task queue management.
*   **Framework:** Flask WSGI / ASGI app managed by Gunicorn.
*   **Database:** SQLAlchemy ORM over PostgreSQL in Production (MVCC concurrent writes enabled).
*   **Polling & Networking Architecture:**
    *   **Stateless HTTP Polling:** Room tracking uses HTTP GET requests to `/api/room_status/<room_uuid>` and `/api/tracker/<tracker_id>`. This stateless design accommodates Archipelago server timeouts (rooms sleep/close after 2 hours of inactivity) without maintaining fragile persistent WebSocket streams.
    *   **Adaptive Polling:** Active rooms are polled at normal intervals, while idle or stale rooms back off to save bandwidth and CPU.
    *   **WebSocket DataPackage Caching:** WebSockets are used *exclusively* during room setup to fetch `DataStorage` group keys (`_read_item_name_groups_{game}`). Once fetched, group mapping data is cached in Redis / DB.
*   **Authentication:**
    *   **Discord OAuth2:** Users log in via Discord.
    *   **JWT:** The backend issues JWTs for API access after Discord auth.
    *   **Guest Mode:** Supports anonymous guest accounts.
*   **Push Notifications:** Firebase Cloud Messaging (FCM) via `firebase-admin` SDK.
*   **Data Retention:** Historical events (`notified_items` and `notified_hints`) are maintained with a default 90-day retention policy to support long-running async multiworlds.
*   **Integrations:** "Cheese Tracker" integration allows users to sync their tracked rooms from an external service. API keys are stored encrypted. Slot claims and unclaims are synced bidirectionally; ownership conflicts (both authenticated and unauthenticated) are strictly validated to prevent claim clobbering, and slot collisions immediately trigger local untracking and FCM push notifications.

## Database Schema (Key Models)

*   `User`: Stores Discord ID, preferences, and encryption keys.
*   `TrackedRoom`: Represents a single Archipelago game room (URL, tracker ID).
*   `UserRoomSubscription`: Links a User to a TrackedRoom with an alias.
*   `UserTrackedSlot`: Represents a specific player slot a User wants to watch within a Room.
*   `Device`: Stores FCM tokens for push notifications.
*   `ThresholdGroup` / `ThresholdGroupItem`: Replaced the old single-item `SlotItemThreshold`. Allows users to define named milestone groups of multiple items (or item groups), triggering a notification only when all conditions are satisfied (AND logic).
*   `UserIgnoreItem`: Muted items/groups (global or per-game) suppressed during polling and feed display.
*   `UserWhitelistItem`: Whitelisted items/groups (global or per-game) that always trigger push notifications and bypass ignore rules and category preference mutes (e.g., filler item mutes).
*   `NotifiedItem` / `NotifiedHint`: Logs of events sent to users (for history).
*   `DatapackageCache`: Caches game data (Item/Location names, group memberships) to reduce API calls.

## Development Notes

1.  **Environment Variables:** The backend relies on environment variables (often in `backend/.env`). Key vars include `DATABASE_URL`, `DISCORD_CLIENT_ID`, `SECRET_KEY`, and `ENCRYPTION_KEY`.
2.  **Polling Logic:** The `poller.py` is complex. It manages concurrent setups, regular polling, and "Cheese" polling. It handles "backfilling" history for new subscriptions to avoid notification spam.
3.  **Threshold Groups Evaluation:** The poller evaluates milestone groups when a slot receives new items. It expands `item_group` conditions (e.g. "Swords") using the cached datapackage item group members in `DatapackageCache` to check sum total counts.
4.  **Testing:** The project has unit tests for the Cheese Tracker claim/sync integration in `backend/tests/test_cheese_sync.py`. These can be run in the virtualenv using `python -m unittest backend/tests/test_cheese_sync.py`. Other parts of the project lack a formal test suite; verify those changes carefully by running the backend locally.
5.  **Frontend/Backend Sync:** Changes to API response formats in `backend/app/api.py` usually require corresponding updates in the Android app (specifically the Retrofit interfaces).

## "Gotchas"

*   **Datapackage Cache:** Game datapackages (items, locations, item groups, and location groups) **must only** be retrieved and cached via the Archipelago server WebSocket connection. Crucially, group lists are not stored within the standard `DataPackage` network payload. Instead, they reside in the server's global `DataStorage` keys (`_read_item_name_groups_{game}` and `_read_location_name_groups_{game}`). To query these keys using the `Get` command, the client **must first authenticate** as a player slot (using a `Connect` packet, even as a read-only `Tracker`). An unauthenticated connection can fetch the basic items/locations list via the `GetDataPackage` command but will receive empty/missing group mappings. Do **not** fetch datapackages from the Archipelago HTTP API (e.g., `/api/datapackage/<checksum>`), as the HTTP API only supports officially supported games (~10% of the ecosystem) and will fail (404) for all custom (`.apworld`) games, breaking those games' tracking in the app.
*   **Database:** SQLite uses WAL mode. To prevent thread blocking and write-lock contention (especially when running long background sync workflows), active session connections must be closed (`Session.remove()`) before executing slow network calls or thread delays. All database writes should be aggregated in memory and executed in a short-lived transaction at the end.
*   **Polling:** The poller uses a "Supervisor" pattern to manage tasks. It has self-healing logic for "Pending" rooms that turn into real rooms.
*   **Privacy:** We strictly avoid storing sensitive Discord info (email/pass). We only store ID, username, and avatar hash.
*   **Cheese Tracker Claim Checking:** Unauthenticated claims on Cheese Tracker leave `claimed_by_ct_user_id` as `None` but populate `discord_username` (which shows as `effective_discord_username` on GET requests). Checking for claim conflicts requires checking both for authenticated ID mismatches and unauthenticated Discord username mismatches.
*   **Changelog & Versioning (single source of truth):** All release notes and versions live in `backend/app/data/changelog.json` — a hand-edited file with two newest-first arrays, `app_releases` (Android) and `server_releases` (Backend), which are versioned independently. To cut a release: (1) prepend an entry to the relevant array; (2) for an Android release, bump `versionName`/`versionCode` in `android/app/build.gradle.kts` to match the new `app_releases` version; (3) run `python scripts/generate_changelog.py` to regenerate `android/CHANGELOG.md` and `backend/CHANGELOG.md`; (4) commit. The landing-page version badges, `/api/whats_new`, and `get_server_version()`/`get_android_version()` all read `changelog.json` directly. `scripts/generate_changelog.py --check` (run in CI) fails if the markdown is stale or if the gradle `versionName` disagrees with the newest `app_releases` entry. Do **not** hand-edit the `CHANGELOG.md` files — they are generated.
*   **APK Distribution:** APK files are not hosted directly on the web app/backend. APK downloads are provided exclusively via **GitHub Releases** (alongside Google Play Store).

## LLM Maintenance Directive

1. **Keep LLM.md Updated:** Any material change to the codebase must be reflected in this file. If you add, remove, or significantly modify models, API endpoints, notification logic, architectural patterns, or "gotchas," update the relevant section(s) of `LLM.md` accordingly. This file is the primary onboarding context for all future LLM sessions and must stay accurate.
2. **Backwards Compatibility Warnings:** Always verify and explicitly notify the user whenever any proposed backend, API schema, or database change is NOT 100% backwards-compatible with previous Android app versions.

