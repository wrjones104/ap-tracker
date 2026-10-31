# Archipelago Alerts - iOS Developer Backend Integration Guide

This guide describes how to connect your iOS client application to the Archipelago Alerts backend server for authentication, device registration, and push notification delivery.

*Last checked against the backend at server 1.18.0 (2026-10-31).*

---

## TL;DR - Quick Start (Minimal Steps to Push Notifications)

Follow these 5 steps to get notifications functioning on your app using standard server defaults:

### Step 1: Authenticate on App Launch
Request a guest access token when the app first starts (or sign in with Discord, see [Section 2](#2-api-authentication-flow)):
```bash
curl -X POST https://archipelagoalerts.com/auth/guest
```
**Action**: Save the returned JWT `"token"`. You must pass this token in the `Authorization: Bearer <JWT>` header on all subsequent calls. Guest tokens last 730 days (2 years), but a guest account that makes no authenticated request for 90 days is deleted by the server's cleanup.

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
A `410` with `"error": "fcm_token_unregistered"` means the token is dead: delete it, fetch a new one, and register once more (see [Section 4](#4-registering-device-push-tokens)).

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

### Step 5: Send a Test Push
```bash
curl -X POST https://archipelagoalerts.com/users/me/test-notification \
  -H "Authorization: Bearer <JWT>"
```
The response reports `sent`, `failed` and `removed` counts. `failed: 0` plus an alert on the iPhone means the whole chain works. (On an account that also has an Android device, `sent: 1` can mean only the Android one got it.)

---

## 1. Firebase Cloud Messaging (FCM) Setup

The backend utilizes Firebase Cloud Messaging (FCM) to deliver push notifications. Android and iOS use **separate Firebase projects**: the server holds one service account key per platform and sends each device's pushes through the project matching the `platform` it registered with. To receive notifications on iOS:
1. **Firebase Project**: Set up a Firebase project for your iOS app and register the app's bundle ID in it.
2. **APNs Credentials**: Upload your Apple Developer APNs Auth Key (`.p8` file), Key ID, and Team ID to your Firebase Console under **Project Settings > Cloud Messaging > Apple app configuration**. Without this, FCM accepts the server's sends but cannot deliver them.
3. **App Integration**: Integrate the `FirebaseMessaging` SDK into your Xcode project and enable the Push Notifications capability.
4. **Backend Setup**: Provide the backend administrator with your Firebase project's **Service Account Key JSON** file (Project settings > Service accounts > Generate new private key). They install it on the server via the `FIREBASE_KEY_FILE_IOS` environment variable (default filename `service-account-key-ios.json`). If no iOS key is installed, iOS pushes are skipped and the server logs a warning; Android is unaffected.

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
- **Retention**: a guest account is deleted after 90 days with no authenticated request. Any call that carries the token counts as activity.

### Endpoint: `POST /auth/callback` (Sign in with Discord)
Discord sign-in uses OAuth 2 with PKCE. Your app gets the authorization code from Discord, and the backend exchanges it.
- **Authorize URL**: `https://discord.com/api/oauth2/authorize`
- **Client ID**: ask the backend administrator. It is not a secret.
- **Scope**: `identify`
- **PKCE**: `S256`
- **Redirect URI**: `com.jones.aptracker:/oauth2redirect`, exactly. The backend accepts only one value, its `DISCORD_REDIRECT_URI` setting (confirm it with the administrator), and answers `400 Redirect URI mismatch.` for anything else. Register the URL scheme `com.jones.aptracker` in your app (`ASWebAuthenticationSession` with `callbackURLScheme: "com.jones.aptracker"` works).
- **Request Body**:
  ```json
  {
    "code": "CODE_FROM_DISCORD",
    "redirect_uri": "com.jones.aptracker:/oauth2redirect",
    "code_verifier": "YOUR_PKCE_VERIFIER"
  }
  ```
- **Response (200 OK)**: `{ "message": "Login successful!", "token": "<JWT>", "is_unlimited_pin": false }`
- **Token lifetime**: a Discord JWT lasts **90 days** (guest tokens last 730) and cannot be refreshed. On a `401` from a protected call, send the user through Discord sign-in again.
- **Guest upgrade**: to turn a guest account into a Discord account and keep its rooms, send the guest's JWT as the `Authorization: Bearer` header on this call. Keep the guest token in the Keychain until a `200` replaces it. Without the header, the server creates or signs in to a separate Discord account and the guest's rooms stay behind. A guest token that has been logged out (revoked) is ignored, and the call becomes an ordinary sign-in.
- **Response (409 Conflict)**: `{ "error": "account_conflict", "message": "..." }` when a guest upgrade targets a Discord account that already belongs to another user. The guest account is not changed. This is the usual case for someone who reinstalls, starts as a guest, then signs in. The server has already spent Discord's single-use `code` by then, so **do not retry with the same `code`**. To sign in to the existing account instead, log out of the guest (`POST /logout`) and start a fresh Discord flow with **no** `Authorization` header. The guest's rooms stay on the guest account.

### Endpoint: `POST /logout`
Revokes the JWT in the `Authorization` header (`200`, `{ "message": "Successfully logged out." }`). Note the path: unlike `/auth/guest` and `/auth/callback`, it has **no** `/auth` prefix, and `POST /auth/logout` answers `404`. It does not unregister the device; call `DELETE /devices` first, while the token is still valid, if the phone should stop getting pushes.

### Endpoint: `DELETE /users/me`
Deletes the account and everything it owns (devices, rooms, slots, milestones, templates) and revokes the JWT (`200`). The App Store requires in-app account deletion for apps that let users create an account (Guideline 5.1.1(v)).

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

- `min_app_version` is an **integer**, not a semantic version string. It is **not** `1.2.0` or `"9.0"` — it is a plain build number that only ever increments.
- The server operator sets it with the `MIN_APP_VERSION` environment variable; when unset it is `9`. It can change without a backend release, so always read it at runtime rather than hard-coding it.
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

Once your iOS app retrieves the FCM token and the IDFV, send them to the backend to link the device to the user account. Do this at every launch and whenever FCM hands you a new token (`messaging(_:didReceiveRegistrationToken:)`).

- **Endpoint**: `POST /devices`
- **Request Body**:
  ```json
  {
    "fcm_token": "YOUR_FCM_TOKEN_FROM_FIREBASE_SDK",
    "device_id": "YOUR_IOS_IDFV_UUID_STRING",
    "platform": "ios"
  }
  ```
  - **`fcm_token`**: the FCM registration token (`Messaging.messaging().token`), not the raw APNs device token.
  - **`platform`**: must be `"ios"`. A missing or unrecognized value is stored as `android`, and that device's pushes then go through the Android Firebase project and fail.
  - **`device_id`**: should stay the same for an install. The server keys the device row on `(user, device_id, platform)` and swaps in the new token when it changes.
  - `data_only_push` is accepted but applies to Android only; it is ignored for iOS devices.
- **Response (201 Created)**:
  ```json
  {
    "message": "Device registered successfully"
  }
  ```
- **Response (410 Gone)**: the server dry-runs the token against FCM, and answers this when FCM says the token is retired (for example, a token restored from a device backup):
  ```json
  {
    "error": "fcm_token_unregistered",
    "message": "This push token is no longer valid. Request a new one and register again."
  }
  ```
  Delete the token (`Messaging.messaging().deleteToken`), fetch a fresh one and register again. **Retry at most once per launch**, so a wrong 410 cannot turn into a loop. Any other outcome of the check (FCM slow, unreachable or misconfigured) stores the token as normal.
- **Tokens move**: a token can only belong to one device row. Registering a token another row holds (another account on the same phone, or an old `device_id` after a phone transfer) moves it to this one.

### Unregistering: `DELETE /devices`
Body `{ "fcm_token": "..." }`. Answers `200` when removed and `404` when no device on this account holds the token. Call it on sign-out if the phone should stop receiving pushes.

### Test push: `POST /users/me/test-notification`
Sends a test push to every device registered on the account, through each device's own Firebase project, and removes devices whose token FCM reports as unregistered.
- **Response (200 OK)**:
  ```json
  {
    "message": "Sent test notification to 1 devices.",
    "sent": 1,
    "failed": 0,
    "removed": 0
  }
  ```
- `failed` counts every device that did not get the push, including iOS devices skipped because the server has no iOS key installed. `removed` counts the dead tokens deleted.
- `404` when the account has no registered devices.

---

## 5. Archipelago Room Management

### Step 1: Add/Subscribe to a Room
- **Endpoint**: `POST /rooms`
- **Request Body**:
  ```json
  {
    "room_url": "https://archipelago.gg/room/YOUR_ROOM_UUID",
    "alias": "My AP Co-op Game",
    "icon_name": "person",
    "sync_to_cheese": false
  }
  ```
  - **`sync_to_cheese`** (Boolean, optional): whether to also create this room on Cheese Tracker. Omitted means the user's stored default (`cheese_publish_new_rooms` on `GET /users/me`). It has no effect for users without a Cheese Tracker connection. See [Section 9](#9-cheese-tracker-integration-optional).
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
      "web_url": "https://archipelago.gg/room/YOUR_ROOM_UUID",
      "cheese_link": "none",
      "cheese_tracker_id": null,
      "cheese_unlisted": false
    }
  ]
  ```
  - **`id`**: the Room/Subscription ID (`room_db_id`) used in all `/rooms/<id>/...` paths.
  - **`status`**: one of `active`, `completed`, `suspended_error`, or `suspended_stale`.
  - **`web_url`**: a direct link to the room on the hosting site.
  - **`cheese_*`**: Cheese Tracker state for this room; see [Section 9](#9-cheese-tracker-integration-optional).
- A room that every subscriber has archived is not polled. Unarchiving it resumes updates.

### Step 3: Update, Archive, Revive, or Unsubscribe
- **`PUT /rooms/<subscription_id>`**: send any of `{ "alias": "...", "icon_name": "...", "is_archived": true }`. Answers `200` with `{ "message": "Subscription updated.", "is_archived": true }`; `400` if none of the three is sent, `403` if not subscribed.
- **`POST /rooms/<subscription_id>/revive`**: wakes a `suspended_error` or `suspended_stale` room and queues an immediate poll (`200`). Answers `400` if the room is completed or not suspended, and `429` within 30 seconds of the last revive of that room.
- **`DELETE /rooms/<subscription_id>`**: unsubscribes the user (`200`; `404` if not subscribed). A room linked to Cheese Tracker is also hidden on the user's Cheese dashboard, and a room with a Cheese tracker is remembered as dismissed so the suggestions do not offer it back.

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
      "has_all_checks": false,
      "checks_done": 12,
      "total_locations": 140,
      "is_tracked": false,
      "track_mode": null,
      "cheese_claim": null,
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
      "has_all_checks": false,
      "checks_done": 40,
      "total_locations": 100,
      "is_tracked": true,
      "track_mode": "play",
      "cheese_claim": null,
      "needs_backfill": false,
      "notify_progression": true,
      "notify_useful": false,
      "notify_filler": null,
      "notify_trap": null,
      "notify_hints": true
    }
  ]
  ```
  - The `notify_*` fields reflect the per-slot preference overrides. A value of `null` means "not overridden — inherit the user's account-level default" (see [Section 7](#7-configuring-notification-preferences)). They are `null` for slots you aren't tracking.
  - **`is_finished`** means the slot reached its goal. **`has_all_checks`** means it has no locations left to check. They differ in rooms with release disabled. Both `has_all_checks` and `checks_done` are `null` when the server has never fetched the room's check counts, which is not the same as `false`. A `total_locations` of `0` means the total is unknown. Which of these counts as "finished" is the user's choice; see `finished_definition` in [Section 7](#7-configuring-notification-preferences).
  - **`track_mode`**: `play` or `watch` for tracked slots, `null` otherwise. Both send alerts; the difference only matters for Cheese Tracker claims ([Section 9](#9-cheese-tracker-integration-optional)).
  - **`cheese_claim`**: who holds the slot on Cheese Tracker, for users with a Cheese connection; `null` otherwise.
  - A tracked slot missing from the room's cached player list (empty or partial cache) is still listed, named `Player <slot_id>`, so saving the picker does not untrack it.

### Step 2: Update Tracked Slots
- **Endpoint**: `PUT /rooms/<subscription_id>/slots`
- **Request Body**:
  ```json
  {
    "tracked_slot_ids": [1, 2],
    "slot_modes": { "1": "play", "2": "watch" }
  }
  ```
  - `tracked_slot_ids` replaces the user's whole tracked set for the room.
  - **`slot_modes`** (Object, optional): `{slot_id: "play" | "watch"}`. Omit it and existing slots keep their mode while newly tracked ones get `play`. Any other value answers `400`.

### Step 3: All Tracked Slots in One Call
- **Endpoint**: `GET /users/me/tracked-slots`
- **Response (200 OK)**: one entry per subscribed room, with the room's `room_db_id`, `room_id`, `room_alias`, `icon_name`, `is_archived`, `host`, and a `tracked_slots` list. Each tracked slot carries `slot_id`, `player_name`, `player_alias`, `game`, `is_finished`, `has_all_checks`, `checks_done`, `total_locations`, `last_activity`, `item_count`, `needs_backfill`, `track_mode`, every per-slot preference (including `finished_definition`), `snooze_until`, and `cheese`.
- Unlike `GET /rooms`, this includes **archived** rooms. Filter on `is_archived` for screens that show active rooms only.
- It is the only route that returns every per-slot preference override; `GET /rooms/<id>/players` returns just the five `notify_*` category fields.
- The rooms carry no `players` list any more. Use `GET /rooms/<id>/players` for that.
- **Caching**: the response has an `ETag` and `Cache-Control: private, no-cache`. Send the ETag back as `If-None-Match` and the server answers `304 Not Modified` with no body when nothing changed. `URLSession` with its default `URLCache` usually revalidates this way on its own.

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
    "finished_definition": "goal",
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
- **`notify_hints`** (Boolean, default `true`): Toggles notifications for hints about items **located in this slot's world** (the slot is the hint's `location_owner`).
- **`notify_hints_remote_items`** (Boolean, default `true`): Toggles notifications for hints about **this slot's own items** located in someone else's world (the slot is the hint's `item_owner`). The two settings are independent; neither switches the other off.
  - A self-hint (the item is in the slot's own world) never notifies, and neither does a hint whose location was already checked when the server first saw it.
- **`notify_finished`** (Boolean, default `false`): If `true`, item and hint notifications **keep arriving after the slot is finished**. It does not control the "Player(s) Finished!" announcement itself, which always arrives (only snooze silences it).
- **`finished_definition`** (String, default `"goal"`): What counts as finished for this slot: `goal` (reached its goal), `all_checks` (no locations left), `both`, or `either`. Any other value answers `400`. It decides when the finish announcement fires and when `notify_finished` takes over.
- **`use_condensed_messages`** (Boolean, default `false`): If `true`, condenses the notification string length (e.g., `"Sent to HeroLink by SamusAran"` instead of `"SamusAran sent Morph Ball to HeroLink (Brinstar)"`).
- **`combine_notifications`** (Boolean, default `false`): If `true`, notifications triggered during the same polling cycle are bundled together into a single message payload. The server currently reads only the **account-level** value; a per-slot override is stored but has no effect. Regardless of the setting, a poll that produces 10 or more item notifications for a user is always bundled.
- **`suppress_own_events`** (Boolean, default `true`): If `true`, blocks notifications for items sent to you by *other* players. Useful if you are playing online and already seeing items appear in real-time.
- **`remove_emojis`** (Boolean, default `false`): If `true`, strips category prefix emojis (e.g., 🏆, ✅, 💡) from the push notification title.
- **`suppress_self_found`** (Boolean, default `true`): If `true`, blocks notifications for items you found for *yourself* in your own world.
- **`suppress_connected`** (Boolean, default `false`): If `true`, suppresses push notifications entirely if your slot's client is currently connected online to the Archipelago room.

### Account-level defaults
- `GET /users/me` returns each default as `<field>_default` (for example `notify_finished_default`, `finished_definition_default`), plus `is_guest`, `global_snooze_until` and the Cheese fields.
- `PUT /users/me/preferences` sets them, using the field names **without** the `_default` suffix (for example `{"notify_finished": true, "finished_definition": "either"}`). Here `finished_definition` cannot be `null`.

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
- **Limit**: a slot holds at most **50** groups. Creating one more answers `400` with `"reason": "slot_group_limit"`.
- **Initial state**: a group made here always starts with `is_triggered: false`, and item names are not checked against the game data. If the slot has already reached the quantities, the group fires a "milestone reached" push on the slot's next item ([#521](https://github.com/wrjones104/ap-tracker/issues/521)). Use the bulk endpoint below when that should not happen.
- **Related endpoints**:
  - `GET /rooms/<subscription_id>/slots/<slot_id>/threshold-groups` — list existing groups, ordered by `id`.
  - `PUT /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/<group_id>` — update a group (same body as create). A group that has already fired cannot be edited (`400`).
  - `DELETE /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/<group_id>` — remove a group.
  - `POST /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/bulk` — create several groups at once (see below).
  - `GET /users/me/threshold-groups` — every tracked slot's groups in one call (see below).

#### Creating several groups at once
- **Endpoint**: `POST /rooms/<subscription_id>/slots/<slot_id>/threshold-groups/bulk`
- **Request Body**: `{ "groups": [ { "name": "...", "items": [ ... ] }, ... ] }`, at most 50 groups.
- Item names are checked against the slot's game data on the server. A group is skipped rather than failing the request when none of its items exist in this seed (`no_valid_items`), its name matches a group already on the slot (`duplicate_name`), or the slot is full (`slot_group_limit`).
- **Already met**: a created group whose quantities the slot has already reached is marked met (`is_triggered: true`) on creation, silently. Only this endpoint and template auto-apply do this; the single `POST` and the `PUT` do not.
- **Response (201 Created)**: `{ "message": "...", "created": [{ "id": 43, "name": "..." }], "skipped": [{ "name": "...", "reason": "duplicate_name" }] }`. If nothing could be created it answers `400` with the same `skipped` list.

#### Every slot's groups in one call
- **Endpoint**: `GET /users/me/threshold-groups`
- **Response (200 OK)**: `[ { "room_db_id": 14, "slot_id": 1, "groups": [ ... ] } ]`, one entry per tracked slot, with `groups` in the same shape as the per-slot `GET`. Slots with no groups are listed with `[]`, so you can clear groups deleted elsewhere. One slot's progress failing does not blank the others.

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
      { "room_db_id": 14, "slot_id": 1, "last_id": 123456 }
    ],
    "hints": [
      { "room_db_id": 14, "last_updated": "2026-06-15T12:00:00Z" }
    ]
  }
  ```
  `last_id` is the item watermark the previous sync returned for that slot. `last_timestamp` is still accepted when you have no watermark yet.
- **Response**: four keys — `new_items` and `updated_hints` carry the deltas, and `item_watermarks` / `hint_watermarks` carry the cursors to send back on the next call. An empty request returns all four as empty.

  ```json
  {
    "new_items": [],
    "updated_hints": [],
    "item_watermarks": { "14_1": 123456 },
    "hint_watermarks": { "14": "2026-06-15T12:00:00Z" }
  }
  ```
- **Persist the watermarks** and replay them on the next sync. Do not derive your cursor from the timestamps of the returned rows — the server re-indexes item ids, and the watermarks account for that. Item watermarks are keyed `"<room_db_id>_<slot_id>"`, hint watermarks by `"<room_db_id>"`.
- **Stale cursor**: if a sent `last_id` is higher than the server's newest item id for that slot, the server resets the cursor and sends the slot's history again from the start. Upsert rows by `id`, and drop cached rows for that slot whose `id` is above the new watermark.
- **Scope**: only **non-archived** rooms are synced. `new_items` holds only items your tracked slots received, but **`updated_hints` holds every hint in each room, including hints between players you don't track**. Filter hints on the client against your tracked `(room_db_id, slot_id)` pairs, matching on `item_owner_id` or `location_owner_id`. Never match on `slot_id` alone: slot numbers restart at 1 in every room.
- One call returns at most 500 items and 100 hints. **A room missing from `hint_watermarks` means "keep the cursor you sent"**: its hints may still be queued behind other rooms' hints in a full batch. Sync again until the deltas are empty.
- History rows also carry `playerHasAllChecks`, which is `null` when the room's check counts were never fetched (see `has_all_checks` in [Section 6](#6-slot--player-tracking)).

### Filter Status on History Rows
Item rows returned by the history endpoints carry the user's filter state, evaluated server-side against the exact datapackage checksum the item arrived under:
- **`isIgnored`** (Boolean): an ignore rule matched this item.
- **`isWhitelisted`** (Boolean): a whitelist rule matched, which overrides ignore rules and category mutes.

Do not recompute these on the client. Item-group rules require datapackage group membership for the specific checksum, which is why the evaluation moved server-side.

The flags are set when a row is first sent, so a rule added or removed later does not change rows you already cached. After any ignore or whitelist change, call **`GET /history/filter-flags`**. It returns `{ "ignored_ids": [...], "whitelisted_ids": [...] }`: the history row `id`s the user's current rules match. Clear both flags on every cached row, then set them for the returned ids.

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
- Snooze also silences the "Player(s) Finished!" announcement, which no preference can turn off.

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

### Game Data (Item and Location Names)
Push and history payloads name items and locations already. These routes are for screens that need a game's full name tables, such as an item picker. All need the `Authorization` header.
- **`GET /datapackage/checksum/<checksum>`** — one game's tables, `{ "checksum", "game", "items": {"<id>": "<name>"}, "locations": {"<id>": "<name>"} }`. A checksum is a content hash, so the response never changes: it is served with an `ETag` and `Cache-Control: private, max-age=31536000, immutable`, and you can keep it forever. A game with an empty datapackage answers `200` with empty tables; `404` means the server has not cached that checksum.
- **`GET /rooms/<subscription_id>/datapackage`** — the whole room's tables in one response: `{ "players": {"<slot_id>": "<name>", "0": "Archipelago"}, "items": {"<checksum>_<id>": "<name>"}, "locations": {"<checksum>_<id>": "<name>"}, "slot_to_checksum": {"<slot_id>": "<checksum>"}, "generic_checksum": "<checksum or null>" }`.
  - Unlike the per-checksum route, `items` and `locations` are keyed **`"<checksum>_<id>"`**, not `"<id>"`, and group entries end in `" (Group)"`.
  - `generic_checksum` is the checksum for Archipelago's own locations (such as `-1` Cheat Console and `-2` Server): look those up under `"<generic_checksum>_<id>"`.
  - It no longer returns `item_flags`.
- **`GET /games`** — a JSON array of strings: every game name the server knows. Now requires sign-in.
- **`GET /games/<game>/items`** — a JSON array of **objects**, `[ { "name": "Hookshot", "is_group": false }, { "name": "Weapons", "is_group": true } ]`, items and item groups together, sorted by `name`. The game name must match exactly, case included (use the spelling `GET /games` returns), and must be percent-encoded as a path component.

---

## 9. Cheese Tracker Integration (Optional)

The official app can mirror rooms to Cheese Tracker for users who connect it. You can skip this section entirely; a user with no Cheese connection sees none of it.

- **Per-room link**: each subscription has `cheese_link` (`none` or `linked`), returned by `GET /rooms`. Set it with `PUT /rooms/<subscription_id>/cheese_link` and body `{ "linked": true }`. Linking a room with no tracker yet creates one, which takes a couple of minutes: `cheese_link` is `linked` while `cheese_tracker_id` is still `null`. Unlinking stops this app writing to the tracker; it does not delete the tracker or release claims.
- **`cheese_unlisted`**: the linked tracker has dropped off the user's Cheese dashboard. Show it to the user; the server never removes a room because of it.
- **Play vs. watch**: a slot in `play` mode is claimed on Cheese as the user's; `watch` alerts without claiming. When someone else claims a slot, or the tracker releases it, the server moves it to `watch` and sends a push of type `conflict`.
- **Known gap ([#520](https://github.com/wrjones104/ap-tracker/issues/520))**: when a slot is already claimed at the moment the user tracks it in `play` mode, that `conflict` push currently reaches Android devices only. The slot still moves to `watch`, so re-read `track_mode` after `PUT /rooms/<id>/slots` rather than waiting for the push.
- **Suggestions**: `GET /integrations/cheese/available` lists trackers on the user's Cheese dashboard that the app does not have yet.
  - `POST /integrations/cheese/available/dismiss` and `POST /integrations/cheese/available/import` both take `{ "cheese_tracker_ids": ["..."] }`, a non-empty list.
  - Import handles at most 25 trackers per call and returns the rest in `deferred`; send those in a follow-up call. It also reports `imported`, `relinked`, and `linked_elsewhere` (trackers refused because another tracker already owns their room).

---

## 10. Milestone Templates

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
      "auto_apply": false,
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
    "auto_apply": false,
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
- **`PUT /milestone-templates/<id>/auto-apply`** — body `{ "auto_apply": true }`; flips just that flag.
- **`DELETE /milestone-templates/<id>`** — deletes the template and its items.

### Applying templates
- **By hand**: send the chosen templates' items to `POST /rooms/<id>/slots/<slot_id>/threshold-groups/bulk` ([Section 7](#creating-several-groups-at-once)). It creates them all in one transaction and reports any it skipped. There is no "create template from group" endpoint; build the `POST /milestone-templates` body from the group's items on the client.
- **Automatically**: a template with `auto_apply: true` is applied by the server to slots the user newly starts tracking in `play` mode, once the slot's game is known. Turning it on never touches slots already tracked, and `watch` slots are skipped.

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
- **No datapackage validation happens at import time** — the importing user may not even own a slot for that game yet. Item-existence validation (matching against the current datapackage) only happens later, when the user actually starts a Milestone Group from the template on a real slot.
- Each parsed template is created via a normal `POST /milestone-templates` call. A `409` on any one of them means that user already has a template with that exact name for that game — same overwrite-or-skip decision as the single-create flow, just repeated per template in the batch.

---

## 11. Push Notification Format

The backend sends one FCM message per notification per device. For iOS devices the message has:
- a `notification` block (`title`, `body`);
- an **APNs block**: header `apns-priority: 10`, and `aps` with `alert` (the same title and body), `sound: "default"`, `badge: 1`, and `content-available: 1`;
- a `data` dictionary (below).

`badge` is always `1`, not a count, so clear the badge yourself when the app opens. Because `content-available` is set, iOS may also wake your app in the background when a push arrives.

Android-only features you will not see on iOS: data-only pushes (where the app draws the notification itself), and the `history` field that lets the Android app store a push's items without syncing. On iOS, fetch new items with `POST /history/sync` ([Section 8](#optimized-batch-history-syncing)).

### The `data` dictionary

All values arrive as strings, per FCM's data-payload contract.

| Key | Always present | Meaning |
| --- | --- | --- |
| `notification_type` | Yes | The event type: `item_progression`, `item_useful`, `item_filler`, `item_trap`, `item_milestone`, `hint`, `player_finish`, `conflict` (a Cheese Tracker slot moved to Watching), or `test`. A combined push takes the type of its first event, or `item_progression` if any event in it is progression or a milestone. |
| `channel_id` | Yes | The Android notification channel. Android-specific, but a **useful categorization signal on iOS** — see below. |
| `bundled_items` | No | Present on **combined** notifications and on the test push (three dummy entries). A JSON-encoded **string** holding a list of display strings, one per event, e.g. `"[\"Morph Ball [SamusAran]\", \"Boss Key [HeroLink]\"]"`; hint entries are the hint's body text. A very large bundle is trimmed to fit FCM's 4 KB limit and ends with an entry like `"…and 12 more"`. Parse it as JSON after reading it as a string. |
| `bundle_type` | No | Sent with `bundled_items`: the type of the bundled batch, mirroring `notification_type` for the batch as a whole. |

### Mapping `channel_id` to iOS

`channel_id` is derived server-side from `notification_type` and is the same categorization the Android app uses. It maps cleanly onto **iOS notification categories / interruption levels**:

| `channel_id` | Source event types | Suggested iOS treatment |
| --- | --- | --- |
| `channel_progression` | `item_progression`, `item_milestone` | `.timeSensitive` interruption level |
| `channel_non_progression` | `item_useful`, `item_trap`, `item_filler` | `.active` |
| `channel_hints` | `hint` | `.active` |
| `channel_general` | `player_finish`, `conflict`, `test`, and any unmapped type | `.passive` |

On iOS every push is sent with `apns-priority: 10`. Registering matching `UNNotificationCategory` values lets users tune each class of alert separately, which is the iOS equivalent of the per-channel controls Android users get in system settings.

Use `bundle_type` and `bundled_items` to show the list of events when the user taps a combined notification.

---

## 12. Release Notes (`GET /api/whats_new`)

Unauthenticated. Serves the same release-notes data that drives the in-app "What's New" sheet, from the backend's single source of truth.

- **Query Parameters**:
  - `target`: `app`, `server`, or `all` (default `all`). Use `server` for backend releases; `app` returns the *official Android app's* notes, which will not match a third-party iOS client's versioning.
  - `limit`: caps the number of releases returned, newest first. Omitted or non-positive returns the full list.
- Each release carries a `version`, `release_date`, `title`, a `highlights` array for user-facing display, and a `categories` object splitting entries into `features` / `improvements` / `fixes`.
