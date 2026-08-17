# Archipelago Alerts - iOS Developer Backend Integration Guide

This guide describes how to connect your iOS client application to the Archipelago Alerts backend server for authentication, device registration, and push notification delivery.

---

## TL;DR - Quick Start (Minimal Steps to Push Notifications)

Follow these 4 steps to get notifications functioning on your app using standard server defaults:

### Step 1: Authenticate on App Launch
Request a persistent guest access token when the app first starts:
```bash
curl -X POST https://archipelagoalerts.com/auth/guest
```
**Action**: Save the returned JWT `"token"`. You must pass this token in the `Authorization: Bearer <JWT>` header on all subsequent calls. Note that guest tokens are exceptionally long-lived, lasting 730 days (2 years).

### Step 2: Register the Device Token
Get the **FCM token** from the Firebase SDK, retrieve the iOS **IDFV** (Identifier for Vendor) as a raw string, and register the device platform context:
```bash
curl -X POST https://archipelagoalerts.com/devices \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "fcm_token": "YOUR_FCM_TOKEN",
    "device_id": "YOUR_RAW_IOS_IDFV_STRING",
    "platform": "ios"
  }'
```

### Step 3: Subscribe to a Room
Subscribe to an active Archipelago room URL. Note that success yields a `201 Created` status code:
```bash
curl -X POST https://archipelagoalerts.com/rooms \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "room_url": "https://archipelago.gg/room/YOUR_ROOM_UUID",
    "alias": "My Co-Op Game"
  }'
```
*Guardrails*: `room_url` max length is 512 characters; `alias` max length is 128 characters. Hitting an existing subscription fires a `409 Conflict`.

### Step 4: Track Player Slots
Call `GET /rooms` to fetch your active user subscriptions. The returned `id` field is your unique database Room/Subscription ID (referred to in backend documentation as `room_db_id`), not the core server room entity UUID.

Update the list of player slot IDs you want to monitor:
```bash
curl -X PUT https://archipelagoalerts.com/rooms/<subscription_id>/slots \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "tracked_slot_ids": [1, 2]
  }'
```
*Polling Note*: Submitting slot changes triggers an immediate server poll rather than waiting for the next cycle. That first poll **backfills** the slot's existing history instead of notifying on it, so newly tracked slots populate your history views without firing a burst of push notifications for events that already happened.

---

## 1. Firebase Cloud Messaging (FCM) Setup

The backend utilizes Firebase Cloud Messaging (FCM) to deliver push notifications. To receive notifications on iOS:
1. **Firebase Project**: Set up a Firebase project for your iOS app.
2. **APNs Credentials**: Upload your Apple Developer APNs Auth Key (`.p8` file), Team ID, and App Bundle ID to your Firebase Console under **Project Settings > Cloud Messaging > Apple app sharing**.
3. **App Integration**: Integrate the `FirebaseMessaging` SDK into your Xcode project.
4. **Backend Setup**: Provide the backend administrator with your Firebase project's **Service Account Key JSON** file. They will save it on the server as `service-account-key-ios.json` (or map it via the `FIREBASE_KEY_FILE_IOS` environment variable) to authorize the backend to send pushes to your iOS app.

---

## 2. API Authentication Flow

All protected endpoints require an Authorization header containing a JSON Web Token (JWT) formatted as:
`Authorization: Bearer <JWT_ACCESS_TOKEN>`

### Endpoint: `POST /auth/guest`
Creates a guest user account and returns a long-lived JWT.
- **Headers**: `Content-Type: application/json`
- **Response (200 OK)**:
  ```json
  {
    "message": "Guest access granted!",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "is_unlimited_pin": false
  }
  ```
- **Action**: Store this token securely in the iOS **Keychain** for all future API calls.

---

## 3. App Configuration Check (Minimum App Version)

Before letting the user into the app, check whether the client build is new enough to talk to the backend.

- **Endpoint**: `GET /config`
- **Query Parameters**: None. (The endpoint takes no parameters — there is **no** `platform` argument. `min_app_version` is a single global value shared by every client, iOS and Android alike.)
- **Response (200 OK)**:
  ```json
  {
    "min_app_version": 9
  }
  ```

### What `min_app_version` actually means

This is the single most common point of confusion, so read this carefully:

- `min_app_version` is an **integer**, not a semantic version string. It is **not** `1.2.0` or `"9.0"` — it is a plain build number that only ever increments (currently `9`).
- You compare it against your app's own **integer build number** — the monotonically increasing value you bump on every release (the equivalent of Android's `versionCode`, or iOS's `CFBundleVersion` / build number). Do **not** compare it against your marketing/display version (`CFBundleShortVersionString`, e.g. `"2.3.1"`).
- The rule is simply: **if `yourBuildNumber < min_app_version`, the client is too old** and must show an "Update Required" prompt. If `yourBuildNumber >= min_app_version`, the client is fine.

  ```swift
  // Example
  let minVersion = config.minAppVersion            // e.g. 9  (from GET /config)
  let currentVersion = Int(Bundle.main.buildNumber) // your integer build number
  if currentVersion < minVersion {
      // Block the app and show "Update Required"
  }
  ```

> **Heads-up for third-party clients:** `min_app_version` is defined server-side against the *official* app's build numbering. If your client uses its own, unrelated build numbers, a low build number will trip this check and you will see the **"Update Required"** dialog even though nothing is wrong with your integration. Choose a build-number scheme at or above the current `min_app_version`, or gate the check on your own versioning, so you don't lock your users out unnecessarily.

### Recommended behavior: fail open

The version check should **never** hard-block a user because of a network hiccup. If the `GET /config` call fails (timeout, offline, 5xx), treat the client as up to date and let the user in rather than trapping them behind an update wall. Only show the "Update Required" prompt when you have a successful response **and** the comparison shows the build is too old.

---

## 4. Registering Device Push Tokens

Once your iOS app retrieves the FCM token and the IDFV, send them to the backend to link the device to the user account.

- **Endpoint**: `POST /devices`
- **Request Body**:
  ```json
  {
    "fcm_token": "YOUR_FCM_TOKEN_FROM_FIREBASE_SDK",
    "device_id": "YOUR_IOS_IDFV_UUID_STRING",
    "platform": "ios"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "message": "Device registered successfully"
  }
  ```

---

## 5. Archipelago Room Management

### Step 1: Add/Subscribe to a Room
- **Endpoint**: `POST /rooms`
- **Request Body**:
  ```json
  {
    "room_url": "https://archipelago.gg/room/YOUR_ROOM_UUID",
    "alias": "My AP Co-op Game",
    "icon_name": "person"
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "message": "Now tracking room 'My AP Co-op Game'."
  }
  ```

### Step 2: Get Subscribed Rooms
- **Endpoint**: `GET /rooms`
- **Query Parameters** (optional):
  - `archived`: `true` to return archived subscriptions instead of active ones (default `false`).
- **Response (200 OK)**:
  ```json
  [
    {
      "id": 14,
      "room_id": "YOUR_ROOM_UUID",
      "alias": "My AP Co-op Game",
      "icon_name": "person",
      "is_archived": false,
      "host": "archipelago.gg:38291",
      "status": "active",
      "is_complete": false,
      "is_suspended": false,
      "total_slots_count": 5,
      "tracked_slots_count": 0,
      "web_url": "https://archipelago.gg/room/YOUR_ROOM_UUID"
    }
  ]
  ```
  - **`id`**: the Room/Subscription ID (`room_db_id`) used in all `/rooms/<id>/...` paths.
  - **`status`**: one of `active`, `completed`, `suspended_error`, or `suspended_stale`.
  - **`web_url`**: a direct link to the room on the hosting site.

---

## 6. Slot / Player Tracking

### Step 1: Get Players in a Room
- **Endpoint**: `GET /rooms/<subscription_id>/players`
- **Response (200 OK)**:
  ```json
  [
    {
      "slot_id": 1,
      "name": "HeroLink",
      "alias": null,
      "game": "The Legend of Zelda",
      "is_finished": false,
      "is_tracked": false,
      "needs_backfill": false,
      "notify_progression": null,
      "notify_useful": null,
      "notify_filler": null,
      "notify_trap": null,
      "notify_hints": null
    },
    {
      "slot_id": 2,
      "name": "SamusAran",
      "alias": null,
      "game": "Super Metroid",
      "is_finished": false,
      "is_tracked": true,
      "needs_backfill": false,
      "notify_progression": true,
      "notify_useful": false,
      "notify_filler": null,
      "notify_trap": null,
      "notify_hints": true
    }
  ]
  ```
  The `notify_*` fields reflect the per-slot preference overrides. A value of `null` means "not overridden — inherit the user's account-level default" (see [Section 7](#7-configuring-notification-preferences)). They are `null` for slots you aren't tracking.

### Step 2: Update Tracked Slots
- **Endpoint**: `PUT /rooms/<subscription_id>/slots`
- **Request Body**:
  ```json
  {
    "tracked_slot_ids": [1, 2]
  }
  ```

---

## 7. Configuring Notification Preferences

Users can customize notification settings on a per-slot basis (e.g. disable useful items, suppress self-finds, etc.).

### Step 1: Update Slot Preferences
- **Endpoint**: `PUT /rooms/<subscription_id>/slots/<slot_id>/preferences`
- **Response (200 OK)**: `{ "message": "Slot preferences updated successfully" }`
- **Inheritance model**: Each per-slot preference is tri-state. Send `true`/`false` to override, or `null` to clear the override and fall back to the user's account-level default. The "default" values listed below are those account-level defaults, applied whenever a slot's value is `null`.
- **Request Body Options (Send only the fields you wish to change)**:
  ```json
  {
    "notify_progression": true,
    "notify_useful": false,
    "notify_filler": false,
    "notify_trap": false,
    "notify_hints": true,
    "notify_hints_remote_items": true,
    "notify_finished": true,
    "use_condensed_messages": false,
    "combine_notifications": false,
    "suppress_own_events": true,
    "remove_emojis": false,
    "suppress_self_found": true,
    "suppress_connected": false
  }
  ```

### Option Field Reference Guide
- **`notify_progression`** (Boolean, default `true`): Toggles notifications for progression-related items (critical path items like weapons, keys, progressive upgrades).
- **`notify_useful`** (Boolean, default `true`): Toggles notifications for useful but non-critical items (e.g., heart containers, capacity upgrades).
- **`notify_filler`** (Boolean, default `false`): Toggles notifications for filler items (minor/common items). Off by default to avoid notification spam.
- **`notify_trap`** (Boolean, default `false`): Toggles notifications for trap items.
- **`notify_hints`** (Boolean, default `true`): Toggles notifications when a slot is mentioned in an Archipelago server hint.
- **`notify_hints_remote_items`** (Boolean, default `true`): If `true`, you will be notified when a hint reveals an item on someone else's slot that belongs to you.
- **`notify_finished`** (Boolean, default `false`): If `true`, triggers a notification when a player completes their seed goal.
- **`use_condensed_messages`** (Boolean, default `false`): If `true`, condenses the notification string length (e.g., `"Sent to HeroLink by SamusAran"` instead of `"SamusAran sent Morph Ball to HeroLink (Brinstar)"`).
- **`combine_notifications`** (Boolean, default `false`): If `true`, notifications triggered during the same polling cycle are bundled together into a single message payload.
- **`suppress_own_events`** (Boolean, default `true`): If `true`, blocks notifications for items sent to you by *other* players. Useful if you are playing online and already seeing items appear in real-time.
- **`remove_emojis`** (Boolean, default `false`): If `true`, strips category prefix emojis (e.g., 🏆, ✅, 💡) from the push notification title.
- **`suppress_self_found`** (Boolean, default `true`): If `true`, blocks notifications for items you found for *yourself* in your own world.
- **`suppress_connected`** (Boolean, default `false`): If `true`, suppresses push notifications entirely if your slot's client is currently connected online to the Archipelago room.

### Step 2: Adding Item Count Thresholds (Threshold Groups)
You can register milestone rules to notify only when a certain quantity of one or more items is reached for a slot. Thresholds are organized into **groups** — a group fires once all of its item quantities are met.
- **Endpoint**: `POST /rooms/<subscription_id>/slots/<slot_id>/threshold-groups`
- **Request Body**:
  ```json
  {
    "name": "Rupee Milestone",
    "items": [
      { "item_name": "Rupee", "quantity": 10, "is_group": false }
    ]
  }
  ```
  - **`name`** (String, optional): A display label for the group. May be omitted or `null`.
  - **`items`** (Array, required): One or more item rules. Each requires `item_name` (String) and `quantity` (Integer ≥ 1). `is_group` (Boolean, default `false`) marks the rule as matching an Archipelago item *group* rather than a single item name.
- **Response (201 Created)**:
  ```json
  {
    "message": "Threshold group created",
    "id": 42
  }
  ```
- **Related endpoints**:
  - `GET /rooms/<subscription_id>/slots/<slot_id>/threshold-groups` — list existing groups.
  - `PUT /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/<group_id>` — update a group.
  - `DELETE /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/<group_id>` — remove a group.

#### Reading Milestone Progress (`acquired`)
The `GET` response returns the group definitions plus a server-computed progress count per requirement:
```json
[
  {
    "id": 42,
    "name": "Rupee Milestone",
    "is_triggered": false,
    "items": [
      { "id": 88, "item_name": "Rupee", "quantity": 10, "is_group": false, "acquired": 4 },
      { "id": 89, "item_name": "Swords", "quantity": 3, "is_group": true, "acquired": 1 }
    ]
  }
]
```
- **`acquired`** is the running count the server has credited to that slot for the requirement. It is authoritative in two cases the client cannot handle on its own: **item-group requirements** (`is_group: true`), which cannot be counted by item name locally, and items that have aged out of the 90-day history window or were hidden by an ignore rule.
- **`acquired` may be `null`.** Progress computation is advisory and is wrapped so a failure never takes down the definitions fetch. Render a `null` as "progress unavailable" rather than as zero.
- **Recommended display rule**: use `max(local history count, acquired)` for non-group requirements — local history is live but lossy, the server count is complete but lags by a poll cycle. For group requirements, use `acquired` alone.
- **`is_triggered`** indicates the group has already fired its notification.

---

## 8. Native API Notification Features

### Optimized Batch History Syncing
Instead of making repetitive requests to separate history pages, use the centralized sync framework to retrieve localized updates across all tracked slots simultaneously.
- **Endpoint**: `POST /history/sync`
- **Request Payload**:
  ```json
  {
    "items": [
      { "room_db_id": 14, "slot_id": 1, "last_timestamp": "2026-06-15T12:00:00Z" }
    ],
    "hints": [
      { "room_db_id": 14, "last_updated": "2026-06-15T12:00:00Z" }
    ]
  }
  ```
- **Response**: four keys — `new_items` and `updated_hints` carry the deltas, and `item_watermarks` / `hint_watermarks` carry the cursors to send back on the next call. An empty request returns all four as empty.

  ```json
  {
    "new_items": [],
    "updated_hints": [],
    "item_watermarks": {},
    "hint_watermarks": {}
  }
  ```
- **Persist the watermarks** and replay them on the next sync. Do not derive your cursor from the timestamps of the returned rows — the server re-indexes item ids, and the watermarks account for that.

### Filter Status on History Rows
Item rows returned by the history endpoints carry the user's filter state, evaluated server-side against the exact datapackage checksum the item arrived under:
- **`isIgnored`** (Boolean): an ignore rule matched this item.
- **`isWhitelisted`** (Boolean): a whitelist rule matched, which overrides ignore rules and category mutes.

Do not recompute these on the client. Item-group rules require datapackage group membership for the specific checksum, which is why the evaluation moved server-side.

### User Account & Slot Snoozing
Mute notifications globally or for a single tracked slot.
- **Global Snooze**: `POST /users/me/snooze`
- **Slot Snooze**: `POST /rooms/<subscription_id>/slots/<slot_id>/snooze`
- **Payload Format**:
  ```json
  {
    "duration_minutes": 60
  }
  ```
  *Note*: Pass `0` or a negative integer value to instantly lift an active snooze lock constraint.

### Ignore List and Whitelist
Two symmetric, account-level rule lists. **Ignore** suppresses notifications for matching items; **whitelist** forces them through, overriding both ignore rules and category preference mutes (so a whitelisted filler item still notifies with `notify_filler: false`).

- **Ignore**: `GET`, `POST` `/users/me/ignore-list` · `PUT`, `DELETE` `/users/me/ignore-list/<item_id>`
- **Whitelist**: `GET`, `POST` `/users/me/whitelist` · `PUT`, `DELETE` `/users/me/whitelist/<item_id>`

Both take the same body shape:
```json
{
  "item_name": "Heart",
  "game_name": "The Legend of Zelda",
  "is_group": false
}
```
- **`item_name`** (String, required): rejected with 400 if empty.
- **`game_name`** (String, optional): scopes the rule to one game. Omit or send `null` for a global rule matching that item name in every game.
- **`is_group`** (Boolean, default `false`): matches an Archipelago item *group* rather than a single item name. **`game_name` is required when `is_group` is `true`** (400 otherwise), because group membership is only meaningful within a game's datapackage.
- **`409 Conflict`** if a rule with the same `(item_name, game_name)` pair already exists for the user.
- `GET` returns `id`, `item_name`, `game_name`, `is_group`, and `created_at` per rule. Keep the `id` — it is what `PUT` and `DELETE` address.

---

## 9. Milestone Templates

Milestone templates let a user save a Milestone Group's item list (name + quantities) as a reusable, per-user, per-game preset, then start a new group from it later on any slot of the same game. They are keyed by **game name**, not datapackage checksum, so a template spans versions/seeds of a game.

### REST Endpoints
All endpoints require `Authorization: Bearer <JWT>` and are scoped to the calling user — you cannot read, edit, or delete another user's templates (404).

- **`GET /milestone-templates`** — list the user's templates. Optional `?game=<name>` query param filters case-insensitively.
  ```json
  [
    {
      "id": 7,
      "name": "Standard Start",
      "game_name": "Mega Man 2",
      "items": [
        { "id": 21, "item_name": "Items", "quantity": 3, "is_group": true },
        { "id": 22, "item_name": "Bubble Lead", "quantity": 1, "is_group": false }
      ]
    }
  ]
  ```
- **`POST /milestone-templates`** — create a template.
  ```json
  {
    "name": "Standard Start",
    "game_name": "Mega Man 2",
    "items": [
      { "item_name": "Items", "quantity": 3, "is_group": true },
      { "item_name": "Bubble Lead", "quantity": 1, "is_group": false }
    ]
  }
  ```
  - `name` and `game_name` are both required (unlike Milestone Group names, which are optional).
  - `items` requires at least one valid entry (`item_name` non-empty, `quantity` ≥ 1).
  - **`409 Conflict`** if a template with that exact `(game_name, name)` pair already exists for the user — prompt the user to overwrite (`PUT`) rather than silently failing.
- **`PUT /milestone-templates/<id>`** — same body as `POST`; replaces the name, game, and full item list (also used for the overwrite-on-conflict flow).
- **`DELETE /milestone-templates/<id>`** — deletes the template and its items.

There is **no** "apply to slot" or "create from group" endpoint — both are pure client-side orchestration over data the client already has (prefill the normal `POST /rooms/<id>/slots/<slot_id>/threshold-groups` create flow from a template's items, or `POST /milestone-templates` from an existing group's items).

### Export / Import (sharing) — client-side only
Templates are otherwise private, but a user can share one with another player as a plain-text string (e.g. pasted into Discord). This encoding is entirely client-side — the backend is not involved in export/import beyond the normal `POST /milestone-templates` call each imported template makes.

**Format**: a magic-prefixed, base64url-encoded JSON envelope:
```
APMT1:<base64url(json)>
```
`APMT1` = *Archipelago Alerts Milestone Template, format v1*. The decoded JSON:
```json
{
  "v": 1,
  "templates": [
    {
      "game": "Mega Man 2",
      "name": "Standard Start",
      "items": [
        { "item_name": "Items", "quantity": 3, "is_group": true },
        { "item_name": "Bubble Lead", "quantity": 1, "is_group": false }
      ]
    }
  ]
}
```
- `templates` is an array so the same envelope covers both a single-template export and a multi-template bundle — parse it the same way either way.
- No `id` or `user_id` is included — the payload is portable and user-agnostic.
- The base64url portion uses the standard `-`/`_` alphabet (RFC 4648 §5) rather than `+`/`/`, and is not line-wrapped. Padding (`=`) may or may not be present — accept either.
- When **importing**, treat a bare (non-`APMT1:`-prefixed) JSON string that already matches this envelope shape as a lenient fallback input too.
- **Validate before creating**: non-empty `game`/`name`, at least one item, `item_name` non-empty, `quantity` ≥ 1. Reject anything else client-side rather than sending it to `POST /milestone-templates`.
- **No datapackage validation happens at import time** — the importing user may not even own a slot for that game yet. Item-existence validation (matching against the current datapackage) only happens later, client-side, when the user actually starts a Milestone Group from the template on a real slot.
- Each parsed template is created via a normal `POST /milestone-templates` call. A `409` on any one of them means that user already has a template with that exact name for that game — same overwrite-or-skip decision as the single-create flow, just repeated per template in the batch.

---

## 10. Push Notification Format

The backend sends a single FCM message per notification, built from a common `notification` block (`title`, `body`), a `data` dictionary, and an `android` block. **There is currently no `APNSConfig` on the message** — the server sets no `sound`, `badge`, or `content-available`. Whatever `aps` your app receives is what FCM synthesizes from the `notification` block alone, so if you want a sound or a badge count, set it client-side or request that the backend add an APNs config.

### The `data` dictionary

All values arrive as strings, per FCM's data-payload contract.

| Key | Always present | Meaning |
| --- | --- | --- |
| `notification_type` | Yes | The event type: `item_progression`, `item_useful`, `item_filler`, `item_trap`, `item_milestone`, `hint`, or `player_finish`. |
| `channel_id` | Yes | The Android notification channel. Android-specific, but a **useful categorization signal on iOS** — see below. |
| `bundled_items` | No | JSON-encoded **string** of the events in this push, e.g. `"[{\"item_id\": 12345, \"loc_id\": 67890}]"`. Present when the notification represents one or more item events. Parse it as JSON after reading it as a string. |
| `bundle_type` | No | The type of the bundled batch, mirroring `notification_type` for the batch as a whole. |

### Mapping `channel_id` to iOS

`channel_id` is derived server-side from `notification_type` and is the same categorization the Android app uses. It maps cleanly onto **iOS notification categories / interruption levels**:

| `channel_id` | Source event types | FCM priority | Suggested iOS treatment |
| --- | --- | --- | --- |
| `channel_progression` | `item_progression`, `item_milestone` | `high` | `.timeSensitive` interruption level |
| `channel_non_progression` | `item_useful`, `item_trap`, `item_filler` | `normal` | `.active` |
| `channel_hints` | `hint` | `normal` | `.active` |
| `channel_general` | `player_finish`, plus system, test, and any unmapped type | `normal` | `.passive` |

Only `channel_progression` is sent at FCM `high` priority; everything else is `normal`. Registering matching `UNNotificationCategory` values lets users tune each class of alert separately, which is the iOS equivalent of the per-channel controls Android users get in system settings.

Use `bundle_type` and `bundled_items` to load the relevant detail context when the user taps the notification.

---

## 11. Release Notes (`GET /api/whats_new`)

Unauthenticated. Serves the same release-notes data that drives the in-app "What's New" sheet, from the backend's single source of truth.

- **Query Parameters**:
  - `target`: `app`, `server`, or `all` (default `all`). Use `server` for backend releases; `app` returns the *official Android app's* notes, which will not match a third-party iOS client's versioning.
  - `limit`: caps the number of releases returned, newest first. Omitted or non-positive returns the full list.
- Each release carries a `version`, `release_date`, `title`, a `highlights` array for user-facing display, and a `categories` object splitting entries into `features` / `improvements` / `fixes`.
