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
*Polling Note*: Submitting slot changes automatically forces an immediate background server check cycle to securely backfill past event records, ensuring historical sync metrics align cleanly on your client device dashboard without notification flood-spam.

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

## 3. App Configuration Check

Before loading the app, verify if the client needs to warn about a minimum app version.
- **Endpoint**: `GET /config`
- **Query Parameters**:
  - `platform`: `ios` (Required to check the iOS version constraints rather than Android defaults)
- **Response (200 OK)**:
  ```json
  {
    "min_app_version": 1
  }
  ```

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
- **Response (200 OK)**:
  ```json
  [
    {
      "id": 14,
      "room_id": "YOUR_ROOM_UUID",
      "alias": "My AP Co-op Game",
      "host": "archipelago.gg:38291",
      "status": "active",
      "is_complete": false,
      "is_suspended": false,
      "total_slots_count": 5,
      "tracked_slots_count": 0
    }
  ]
  ```

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
      "game": "The Legend of Zelda",
      "is_finished": false,
      "is_tracked": false
    },
    {
      "slot_id": 2,
      "name": "SamusAran",
      "game": "Super Metroid",
      "is_finished": false,
      "is_tracked": true
    }
  ]
  ```

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
- **Request Body Options (Send only the fields you wish to change)**:
  ```json
  {
    "notify_progression": true,
    "notify_useful": false,
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
- **`notify_hints`** (Boolean, default `true`): Toggles notifications when a slot is mentioned in an Archipelago server hint.
- **`notify_hints_remote_items`** (Boolean, default `true`): If `true`, you will be notified when a hint reveals an item on someone else's slot that belongs to you.
- **`notify_finished`** (Boolean, default `false`): If `true`, triggers a notification when a player completes their seed goal.
- **`use_condensed_messages`** (Boolean, default `false`): If `true`, condenses the notification string length (e.g., `"Sent to HeroLink by SamusAran"` instead of `"SamusAran sent Morph Ball to HeroLink (Brinstar)"`).
- **`combine_notifications`** (Boolean, default `false`): If `true`, notifications triggered during the same polling cycle are bundled together into a single message payload.
- **`suppress_own_events`** (Boolean, default `true`): If `true`, blocks notifications for items sent to you by *other* players. Useful if you are playing online and already seeing items appear in real-time.
- **`remove_emojis`** (Boolean, default `false`): If `true`, strips category prefix emojis (e.g., 🏆, ✅, 💡) from the push notification title.
- **`suppress_self_found`** (Boolean, default `true`): If `true`, blocks notifications for items you found for *yourself* in your own world.
- **`suppress_connected`** (Boolean, default `false`): If `true`, suppresses push notifications entirely if your slot's client is currently connected online to the Archipelago room.

### Step 2: Adding Item Count Thresholds (Milestones)
You can register milestone rules to notify only when a certain quantity of items is reached for a slot.
- **Endpoint**: `POST /rooms/<subscription_id>/slots/<slot_id>/thresholds`
- **Request Body**:
  ```json
  {
    "item_name": "Rupee",
    "threshold": 10
  }
  ```
- **Response (201 Created)**:
  ```json
  {
    "message": "Item count threshold milestone added."
  }
  ```

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
- **Response Framework**: Returns distinct structural delta maps tracking `new_items` and `updated_hints`, alongside state-token sync watermarks (`item_watermarks`, `hint_watermarks`).

### User Account & Slot Snoozing
Silence incoming alert tracking streams globally or down to the individual player channel level.
- **Global Snooze**: `POST /users/me/snooze`
- **Slot Snooze**: `POST /rooms/<subscription_id>/slots/<slot_id>/snooze`
- **Payload Format**:
  ```json
  {
    "duration_minutes": 60
  }
  ```
  *Note*: Pass `0` or a negative integer value to instantly lift an active snooze lock constraint.

### Global Wildcard Item Ignore Feed
Allow users to suppress specific item popups via custom criteria definitions.
- **Endpoint**: `POST /users/me/ignore-list`
- **Payload Options**:
  ```json
  {
    "item_name": "Heart",
    "game_name": "The Legend of Zelda",
    "is_group": false
  }
  ```
  Supports standardized dynamic system group filters when linking tracking profiles directly across Cheese Tracker infrastructure endpoints.

---

## 9. Push Notification Format

When a push notification is delivered via FCM to iOS, it will contain standard notification alert details, and custom data parameters containing any relevant metadata:

```json
{
  "aps": {
    "alert": {
      "title": "🏆 Hookshot - [My AP Co-op Game]",
      "body": "HeroLink sent Hookshot to SamusAran (Zelda: Hookshot Chest)"
    },
    "sound": "default",
    "badge": 1,
    "content-available": 1
  },
  "bundled_items": "[{\"item_id\": 12345, \"loc_id\": 67890}]",
  "bundle_type": "item_progression"
}
```
Use the `bundle_type` and `bundled_items` keys to load the notification details context inside the iOS app when the notification is tapped.
