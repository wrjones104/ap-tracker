# Archipelago Alerts - Project Summary for LLMs

This document is intended to help an LLM or AI assistant understand the structure, purpose, and key components of the **Archipelago Alerts** project.

## Project Overview

**Archipelago Alerts** (formerly AP Tracker) is a tool for tracking Archipelago multiworld games. It allows users to subscribe to rooms, track specific players, and receive push notifications for in-game events (items received, hints found, etc.).

The system consists of two main parts:
1.  **Backend:** A Python Flask application that handles API requests, authenticates users (Discord), manages the database, and polls Archipelago servers for game updates.
2.  **Android App:** A native Android application (Kotlin/Jetpack Compose) that serves as the frontend client.

## Directory Structure

*   `backend/`: Contains the Python backend code.
    *   `app/`: Main application package.
        *   `api.py`: Core REST API endpoints (Rooms, Slots, History).
        *   `auth.py`: Authentication logic (Discord OAuth2, JWT).
        *   `poller.py`: The background worker that polls Archipelago servers and Cheese Tracker.
        *   `models.py`: SQLAlchemy database models.
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

### Backend

*   **Framework:** Flask with Gunicorn/Waitress.
*   **Database:** SQLAlchemy ORM. Supports SQLite (local) and PostgreSQL (production).
*   **Asynchronous Processing:** The `poller.py` script uses `asyncio` and `aiohttp` for high-concurrency polling of multiple Archipelago rooms.
*   **Authentication:**
    *   **Discord OAuth2:** Users log in via Discord.
    *   **JWT:** The backend issues JWTs for API access after Discord auth.
    *   **Guest Mode:** Supports anonymous guest accounts.
*   **Push Notifications:** Firebase Cloud Messaging (FCM) via `firebase-admin` SDK.
*   **Integrations:** "Cheese Tracker" integration allows users to sync their tracked rooms from an external service. API keys are stored encrypted.

### Database Schema (Key Models)

*   `User`: Stores Discord ID, preferences, and encryption keys.
*   `TrackedRoom`: Represents a single Archipelago game room (URL, tracker ID).
*   `UserRoomSubscription`: Links a User to a TrackedRoom with an alias.
*   `UserTrackedSlot`: Represents a specific player slot a User wants to watch within a Room.
*   `Device`: Stores FCM tokens for push notifications.
*   `ThresholdGroup` / `ThresholdGroupItem`: Replaced the old single-item `SlotItemThreshold`. Allows users to define named milestone groups of multiple items (or item groups), triggering a notification only when all conditions are satisfied (AND logic).
*   `NotifiedItem` / `NotifiedHint`: Logs of events sent to users (for history).
*   `DatapackageCache`: Caches game data (Item/Location names, group memberships) to reduce API calls.

## Development Notes

1.  **Environment Variables:** The backend relies on environment variables (often in `backend/.env`). Key vars include `DATABASE_URL`, `DISCORD_CLIENT_ID`, `SECRET_KEY`, and `ENCRYPTION_KEY`.
2.  **Polling Logic:** The `poller.py` is complex. It manages concurrent setups, regular polling, and "Cheese" polling. It handles "backfilling" history for new subscriptions to avoid notification spam.
3.  **Threshold Groups Evaluation:** The poller evaluates milestone groups when a slot receives new items. It expands `item_group` conditions (e.g. "Swords") using the cached datapackage item group members in `DatapackageCache` to check sum total counts.
4.  **No Tests:** The project currently lacks a formal test suite. Changes should be verified carefully, preferably by running the backend locally.
5.  **Frontend/Backend Sync:** Changes to API response formats in `backend/app/api.py` usually require corresponding updates in the Android app (specifically the Retrofit interfaces).

## "Gotchas"

*   **Datapackage Cache:** Game datapackages (items, locations, item groups, and location groups) **must only** be retrieved and cached via the Archipelago server WebSocket connection (using the `GetDataPackage` command). Do **not** fetch them from the Archipelago HTTP API (e.g., `/api/datapackage/<checksum>`), as the HTTP API only supports officially supported games (~10% of the ecosystem) and will fail (404) for all custom (`.apworld`) games, breaking those games' tracking in the app.
*   **Database:** SQLite uses WAL mode.
*   **Polling:** The poller uses a "Supervisor" pattern to manage tasks. It has self-healing logic for "Pending" rooms that turn into real rooms.
*   **Privacy:** We strictly avoid storing sensitive Discord info (email/pass). We only store ID, username, and avatar hash.

## LLM Maintenance Directive

**Any material change to the codebase must be reflected in this file.** If you add, remove, or significantly modify models, API endpoints, notification logic, architectural patterns, or "gotchas," update the relevant section(s) of `LLM.md` accordingly. This file is the primary onboarding context for all future LLM sessions and must stay accurate.
