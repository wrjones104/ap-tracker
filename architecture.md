# Archipelago Alerts — System Architecture Document

## 1. System Overview

**Archipelago Alerts** (AP Tracker) is a multi-user tracking and notification system designed for [Archipelago Multiworld](https://archipelago.gg/) async games. It enables 3,300+ active players to track room states, monitor items received by specific player slots, receive instant FCM push notifications for milestone threshold groups, and sync seamlessly with external tools like Cheese Tracker.

```mermaid
flowchart TD
    subgraph Client Layer
        MobileApp[Android Native App]
        WebUI[Web Browser / Dashboard]
        ExecutedApps[FCM Push Service]
    end

    subgraph Containerized Application Layer (Docker Compose)
        subgraph Flask API Server
            AuthBP[auth_routes]
            UserBP[user_routes]
            RoomBP[rooms_routes]
            SlotBP[slots_routes]
            ThreshBP[thresholds_routes]
            HistBP[history_routes]
            GameBP[game_routes]
        end

        subgraph Background Poller Engine
            PollerSupervisor[poller_supervisor]
            PollerWorker[poller_service]
            DatapackageSvc[datapackage_service]
            ThresholdSvc[threshold_service]
            NotificationSvc[notification_service]
            CheeseSvc[cheese_service]
            RetentionSvc[retention_service]
        end

        subgraph In-Memory Cache & Pub/Sub
            Redis[(Redis 7)]
        end

        subgraph Primary Database
            Postgres[(PostgreSQL 15)]
        end
    end

    MobileApp <--> Flask API Server
    WebUI <--> Flask API Server

    Flask API Server -->|Publish immediate_poll| Redis
    PollerSupervisor -->|Subscribe immediate_poll| Redis
    PollerWorker <-->|Datapackage Cache| Redis

    Flask API Server <--> Postgres
    PollerWorker <--> Postgres
    RetentionSvc -->|90-Day Purge| Postgres

    NotificationSvc -->|Push Payloads| ExecutedApps
```

---

## 2. Component Architecture

### A. Modular API Server (`backend/app/routes/`)
The REST API is decomposed into 7 domain-driven Flask blueprints:
* **[auth_routes.py](backend/app/routes/auth_routes.py):** Authentication, session invalidation, JWT token blocklisting, public server config (`/logout`, `/config`).
* **[user_routes.py](backend/app/routes/user_routes.py):** User profiles, FCM device registration, global notification preferences, account deletion.
* **[rooms_routes.py](backend/app/routes/rooms_routes.py):** Room tracking CRUD, room revival, player list resolution, datapackage endpoints.
* **[slots_routes.py](backend/app/routes/slots_routes.py):** Tracked slot preferences, ignore lists, snooze timers.
* **[thresholds_routes.py](backend/app/routes/thresholds_routes.py):** Milestone threshold group CRUD.
* **[history_routes.py](backend/app/routes/history_routes.py):** Item and hint feeds, delta history synchronization (`/history/sync`).
* **[game_routes.py](backend/app/routes/game_routes.py):** Game item & location datapackage inspection.

### B. Redis Event Queue & Cache Layer (`backend/app/services/redis_service.py`)
* **Pub/Sub Event Bus (`immediate_poll` channel):** Eliminates database polling loops for instant room setup & re-poll triggers.
* **Entity Name Caching:** Resolves item and location names in-memory (`dp:<checksum>:<entity_type>:<id>`), bypassing repetitive SQL joins.
* **Protocol Compatibility:** Includes dual-handshake support (RESP3 with automatic RESP2 fallback for older Redis/Windows builds).

### C. Modular Poller Engine (`backend/app/services/`)
The poller handles background polling and event detection across active Archipelago multiworld rooms:
* **[poller_service.py](backend/app/services/poller_service.py):** Stateless HTTP GET polling using `/api/room_status` gatekeepers to skip redundant tracker downloads.
* **[threshold_service.py](backend/app/services/threshold_service.py):** Evaluates AND-logic milestone threshold groups for tracked slots.
* **[notification_service.py](backend/app/services/notification_service.py):** Aggregates and dispatches FCM push notification payloads.
* **[cheese_service.py](backend/app/services/cheese_service.py):** Handles Cheese Tracker background sync and grace-period unclaim logic.
* **[datapackage_service.py](backend/app/services/datapackage_service.py):** Datapackage caching, healing, and group name expansion.
* **[retention_service.py](backend/app/services/retention_service.py):** Runs automated 90-day retention purges for event logs and inactive guest accounts.

---

## 3. Database & Optimization Strategy

### Primary Storage: PostgreSQL 15
* **Composite Indexes:**
  - `ix_usertrackedslot_user_room`: `(user_id, room_id)`
  - `ix_notifieditem_room_receiving_time`: `(room_id, receiving_slot_id, timestamp)`
  - `ix_notifiedhint_room_owner_time`: `(room_id, item_owner_id, timestamp)`
* **90-Day Retention Window:**
  - `NotifiedItem` and `NotifiedHint` records older than 90 days are purged automatically to maintain small database size and sub-millisecond query performance.
  - Inactive guest accounts with no activity for >90 days are cleaned up.

---

## 4. Containerization & Deployment

### Production Deployment (`docker-compose.yml`)
Deployed on Google Cloud VM via Docker Compose:
* **`postgres`**: PostgreSQL 15 container with persistent volume `pgdata`.
* **`redis`**: Redis 7 container with persistent volume `redisdata`.
* **`api`**: Flask API container running Waitress WSGI server.
* **`poller`**: Worker container executing `run_poller_only.py`.

### Local Development (`docker-compose.dev.yml`)
Runs PostgreSQL 15 & Redis 7 containers locally:
```bash
docker-compose -f docker-compose.dev.yml up -d
python backend/run.py
```
