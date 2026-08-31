# Archipelago Alerts 🎮

[![Backend Tests](https://github.com/wrjones104/ap-tracker/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/wrjones104/ap-tracker/actions/workflows/backend-tests.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Archipelago Alerts** (formerly AP Tracker) is a tracking and notification service for [Archipelago Multiworld](https://archipelago.gg/) games. It polls the rooms you follow and pushes a notification to your phone the moment something you care about happens — so you can play an async multiworld without babysitting a tracker page.

The project is a monorepo containing a Python backend (Flask API + background poller) and a native Android app (Kotlin / Jetpack Compose).

📱 [Google Play](https://play.google.com/store/apps/details?id=com.jones.aptracker) · 📦 [APK downloads (GitHub Releases)](https://github.com/wrjones104/ap-tracker/releases) · 💬 [Discord thread](https://discord.com/channels/731205301247803413/1483881181933211838)

---

## Features ✨

**Tracking**
* **Room management** — add, rename, customize (icon and color), archive, and remove tracked rooms.
* **Player selection** — pick exactly which slots in a room you want to watch.
* **Per-slot preferences** — override your global notification defaults for any individual slot.
* **Snooze** — mute notifications globally or per slot for a set window.
* **Guest mode** — start tracking immediately without an account, then upgrade to Discord later without losing your data.

**Notifications**
* **Push via Firebase Cloud Messaging** for progression items, useful/filler items, and newly revealed hints.
* **Android notification channels** — progression, non-progression, hints, and general each map to their own OS channel, so you can set distinct sounds, vibration, priority, and Do Not Disturb bypass in Android settings.
* **Ignore list** — mute specific items or item groups, globally or per game.
* **Whitelist** — items that always notify, bypassing ignore rules and category mutes.

**Milestones**
* **Milestone groups** — define a named goal made of several items or item groups; the notification fires only when every requirement is satisfied (AND logic).
* **Progress tracking** — server-side counts keep progress accurate even for item-group requirements and for history older than the retention window.
* **Milestone templates** — save a milestone as a reusable template, start new ones from a template picker, and export/import templates to share them.

**History and widgets**
* **Activity feed and per-slot history** with filtering, backed by delta sync so only new events are downloaded.
* **Background sync** via WorkManager, with live progress reporting in the UI.
* **Home screen widgets** — a Recent Items widget and a Milestones widget, both configurable per room with layout and font-density options.

**Integrations and account**
* **Cheese Tracker sync** — import tracked rooms, sync slot claims bidirectionally, and read slot notes, statuses, and ping preferences. API keys are stored encrypted.
* **Discord OAuth 2.0** login (Authorization Code + PKCE).
* **In-app What's New** sheet driven by the server changelog.
* **Self-service account deletion** in the app and via a web flow at `/delete-account`.

---

## Repository Layout 🗂️

```
backend/            Python service
  app/
    routes/         Domain REST blueprints (auth, user, rooms, slots,
                    thresholds, templates, history, game, whats_new)
    services/       Poller engine and workers (poller, threshold, notification,
                    cheese, datapackage, filtering, retention, redis)
    data/           changelog.json — single source of truth for versions
    models.py       SQLAlchemy models and composite indexes
    poller.py       Poller supervisor / room setup engine
    db_migrations.py  Runs Alembic on startup for Postgres deployments
  tests/            unittest suite (run in CI)
  run.py            API + poller in one process (local dev)
  run_api_only.py   API container entrypoint
  run_poller_only.py  Poller container entrypoint
android/            Kotlin / Jetpack Compose app
  app/src/main/java/com/jones/aptracker/
    network/        Retrofit API, DTOs, DAOs, token/session management
    database/       Room database, migrations, milestone cache
    repository/     Data layer, history sync manager and worker
    ui/             Compose screens and ViewModels
    widget/         Glance home screen widgets
alembic/            Database migrations
scripts/            generate_changelog.py
```

Further reading: **[architecture.md](architecture.md)** for system design, Redis pub/sub events, composite indexes, and container topology; **[LLM.md](LLM.md)** for a component-by-component overview and the project's gotchas; **[backend/SECURITY.md](backend/SECURITY.md)** for the security model.

---

## Technology Stack 💻

**Backend (Python 3.11+)**
* **Flask** served by **Waitress**, split into an API process and a poller process.
* **SQLAlchemy 2** ORM over **PostgreSQL 15** (UAT/production) or **SQLite** (local dev only).
* **Redis 7** for the `immediate_poll` pub/sub bus and datapackage name caching.
* **Alembic** for migrations, applied automatically on startup against Postgres.
* **firebase-admin** for FCM push (separate Android and iOS credentials supported).
* **aiohttp** and **websockets** for Archipelago polling and datapackage fetches.
* **Docker Compose** for local dev and production deployment on a GCP VM.

**Android app (Kotlin)**
* **Jetpack Compose** + Material 3 for the UI, MVVM with a repository layer.
* **Glance** for home screen widgets.
* **Retrofit** / **OkHttp** for the API, with an auth interceptor and a 401 re-authenticator.
* **Room** for local caching of rooms, history, hints, datapackages, and milestones.
* **WorkManager** for background history sync.
* **AppAuth** for Discord OAuth 2.0, **EncryptedSharedPreferences** for token storage, **DataStore** for settings.
* **Firebase Cloud Messaging** for push delivery.

---

## Getting Started 🚀

### Backend

#### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r backend/requirements.txt
```

`backend/requirements.txt` is what the container installs (it adds `psycopg2-binary` and `redis`); the root file is the local and CI environment.

#### 2. Firebase credentials

Generate a service account private key in your Firebase project settings and save the JSON as `service-account-key.json` in `backend/`. Override the path with `FIREBASE_KEY_FILE_ANDROID` if you keep it elsewhere. An iOS key (`service-account-key-ios.json`, or `FIREBASE_KEY_FILE_IOS`) is optional — the backend initializes a second Firebase app only if the file exists.

#### 3. Configure environment variables

Create `backend/.env`:

```ini
# Database — omit entirely to fall back to a local SQLite file
DATABASE_URL=postgresql://ap_user:ap_password@localhost:5432/ap_tracker_dev
REDIS_URL=redis://localhost:6379/0

# Flask
FLASK_ENV=development          # development | uat | production
SECRET_KEY=change-me           # JWT signing key
LOG_LEVEL=DEBUG                # optional override

# Discord OAuth
DISCORD_CLIENT_ID=your-client-id
DISCORD_CLIENT_SECRET=your-client-secret
DISCORD_REDIRECT_URI=http://localhost:5000/web/callback

# Encryption key for stored Cheese Tracker API keys (Fernet key)
ENCRYPTION_KEY=your-fernet-key

# Optional
CHEESE_BASE_URL=https://cheesetrackers.theincrediblewheelofchee.se
```

#### 4. Start the datastores

The dev compose file brings up PostgreSQL 15 and Redis 7, plus API and poller containers with the app package bind-mounted so backend edits do not need a rebuild:

```bash
docker-compose -f docker-compose.dev.yml up -d
```

To run only the datastores and keep the Python process local, start just the `postgres` and `redis` services and point `DATABASE_URL` at `localhost:5432`.

#### 5. Migrations

* **PostgreSQL:** migrations run automatically on startup — every entrypoint goes through `create_app()`, which takes an advisory lock and upgrades to head. To apply them by hand instead:

  ```bash
  alembic upgrade heads
  ```

* **SQLite:** no migrations. Tables are created directly from the models on startup.

#### 6. Run the server

```bash
python backend/run.py
```

This serves the API on `http://0.0.0.0:5000` and runs the poller in the same process. The containers split these into `run_api_only.py` and `run_poller_only.py`.

#### 7. Tests

Each test module owns its own engine and database, so modules must run in separate processes:

```bash
PYTHONPATH=backend:. python -m unittest backend.tests.test_cheese_sync -v
```

```powershell
$env:PYTHONPATH="backend;."; python -m unittest backend.tests.test_cheese_sync -v
```

CI ([backend-tests.yml](.github/workflows/backend-tests.yml)) runs every module in `backend/tests/` this way on pushes to `main` and on PRs touching the backend, and also verifies the changelog is in sync.

### Android App

1. **Open the `android/` folder** in Android Studio.

2. **Add `google-services.json`** from your Firebase project's Android app settings to `android/app/`.

3. **Create `android/app/local.properties`.** Secrets are read from here by `build.gradle.kts` and are never committed:

   ```properties
   DISCORD_CLIENT_ID=your-discord-client-id

   # Your machine's LAN IP, so a physical device can reach your local backend.
   # Defaults to http://10.0.2.2:5000/ (the emulator's host loopback) if omitted.
   DEV_API_BASE_URL=http://192.168.1.100:5000/

   # Required only when building those flavors — the build fails without them.
   UAT_API_BASE_URL=https://uat.example.com/
   PROD_API_BASE_URL=https://prod.example.com/
   ```

4. **Pick a build variant and run.** Flavors are `dev`, `uat`, and `prod`; each installs under its own application id suffix, so they coexist on one device.

   | Build type | Purpose |
   | --- | --- |
   | `debug` | Everyday development. |
   | `release` | Minified and shrunk, signed for distribution. |
   | `minified` | The release R8 pipeline, but debuggable and debug-signed — use it to catch missing keep rules before they reach the Play Store. |

   Use **`devDebug`** for normal local work against your own backend.

---

## Versioning and Changelogs 📝

The app and the backend are versioned independently. **`backend/app/data/changelog.json` is the single source of truth** — it holds two newest-first arrays, `app_releases` and `server_releases`. The `CHANGELOG.md` files, the landing page version badges, and `GET /api/whats_new` are all derived from it.

To cut a release:

1. Prepend an entry to the relevant array in `changelog.json`.
2. For an Android release, bump `versionName` and `versionCode` in `android/app/build.gradle.kts` to match.
3. Regenerate the markdown:

   ```bash
   python scripts/generate_changelog.py
   ```

4. Commit. `scripts/generate_changelog.py --check` runs in CI and fails if the markdown is stale or if the gradle `versionName` disagrees with the newest `app_releases` entry.

Do **not** hand-edit [android/CHANGELOG.md](android/CHANGELOG.md) or [backend/CHANGELOG.md](backend/CHANGELOG.md) — they are generated.

---

## License

Licensed under the [Apache License 2.0](LICENSE).
