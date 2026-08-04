<!-- GENERATED FILE — do not edit by hand.
     Source of truth: backend/app/data/changelog.json
     Regenerate with: python scripts/generate_changelog.py -->

# Android App Changelog

All notable changes to the **Android App** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This file is generated from `backend/app/data/changelog.json`.

## [1.6.23] - 2026-08-04

_Item Group Filtering Fixes & Cleaner Ignore Menu_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.6.23 Released!**
>
> **Fixes**
> • **Item Group Filtering**: Ignoring or whitelisting an item *group* now actually hides/shows those items in your History — previously these rules were silently ignored there.
> • **Hint Filtering**: Hints now correctly respect per-game ignore/whitelist rules instead of applying them across every game.
> • **Faster Activity Feed**: The Activity feed now loads instantly from your synced history instead of waiting on a network call first.
>
> **Improvements**
> • **Cleaner Ignore/Whitelist Menu**: The item detail sheet now uses two simple "Whitelist..." / "Ignore..." buttons that expand into the full options, instead of a wall of buttons.
>
> GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
> Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> Fixed: ignoring or whitelisting an item group now actually hides/shows those items in History and hints (previously had no effect there). Hint filtering also now respects per-game rules instead of applying across every game.
>
> Improved: the whitelist/ignore menu on item details is now two simple buttons instead of a long list.
>
> Fixed: the Activity feed now loads your synced history instantly instead of waiting on a network call first.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Fixed
> - **Item Group Ignore/Whitelist Filtering**: Item-group ignore/whitelist rules are now computed server-side (`filtering_service.py`) and returned per item/hint via `isIgnored`/`isWhitelisted` fields, fixing group rules having no effect in the History "Show ignored items" filter.
> - **Hint Filtering Game Scope**: Hint filtering now correctly respects the game-specific scope of ignore/whitelist rules instead of applying them across all games.
> - **Activity Feed Warm-Load Stall**: `HistoryViewModel.refreshAllHistory()` now paints from the local DB immediately when tracked-slot metadata from a prior load is already in memory, instead of blocking on `getUserTrackedSlots()` first — removing a 1-2s stall on every tab/room transition. First load in a session is unaffected since there's no warm metadata yet.
>
> ### Changed
> - **Consolidated Ignore/Whitelist Menu**: The History item detail sheet's 6+ whitelist/ignore action buttons are now collapsed into two entry buttons that expand in-place to the scoped options.
> ```

### Changed
- **Cleaner Whitelist & Ignore Menu**: The whitelist and ignore options on an item's detail screen are now two simple buttons that expand into the full set of choices, instead of a long wall of buttons.

### Fixed
- **Item Group Ignore/Whitelist Now Applies in History**: Ignoring or whitelisting an item group now correctly hides or shows those items in your History; previously group-based rules had no effect there.
- **Hint Filtering Respects Per-Game Rules**: Hints now correctly honor game-specific ignore/whitelist rules instead of applying them across all your games.
- **Faster Activity Feed Loads**: The Activity feed now shows your synced history right away instead of waiting on a network call first, so switching to it feels instant.

---

## [1.6.22] - 2026-08-03

_Cheese Tracker Notes, Statuses & Ping Preferences_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts v1.6.22 — Cheese Tracker Notes & Statuses**
>
> • View & edit Cheese Tracker notes and status (Unknown / Unblocked / BK / Soft BK / Go Mode) per slot
> • "Still BK" button to refresh your Last Checked time
> • Per-slot ping preference + a default ping for newly claimed slots
> • Default ping no longer stuck on "Never" when you claim a slot
> ```

### Added
- **Cheese Tracker Notes & Status**: View and edit your Cheese Tracker notes, progression status (Unknown, Unblocked, BK, Soft BK, Go Mode) and completion status right from a slot's detail screen.
- **"Still BK" Button**: Keep your BK/Soft BK status while refreshing your Last Checked time, matching the popular Cheese Tracker web feature.
- **Ping Preferences**: Edit per-slot ping preference on the slot detail screen and choose a default ping preference for newly claimed slots in the Cheese Tracker integration card.

### Changed
- **Forfeit Safeguard**: Marking a slot as Forfeit now shows a confirmation, since Forfeit is permanent on Cheese Tracker and cannot be reversed.
- **Conflict Handling**: Edits that collide with concurrent changes on Cheese Tracker now surface a clear "please refresh" message instead of silently overwriting.

### Fixed
- **Ping Default No Longer Stuck on "Never"**: Claiming a slot now applies your chosen default ping preference instead of always defaulting to "Never".

---

## [1.6.21] - 2026-08-03

_Real-Time History Sync Progress & System Improvements_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.6.21 Released!**
>
> **New Features & Enhancements**
> • **Real-Time History Progress**: Track history sync status live with a dynamic percentage bar (`X% / 100%`) and clear progress indicators.
> • **Background History Syncing**: History syncing now continues seamlessly via WorkManager and ApplicationScope when screen is locked or app is minimized.
> • **Instant Ignore & Whitelist Updates**: Mute rules and whitelists update instantly when returning to the history screen without needing an app restart.
>
> Update now on Google Play or download the latest APK from GitHub Releases!
> ```

### Added
- **Real-Time History Sync Progress**: Added percentage calculation and LinearProgressIndicator banner showing exact item counts (Syncing history... 45% (1,200 / 2,668 items)).
- **WorkManager & ApplicationScope Execution**: Delegated sync execution to HistorySyncManager and Android WorkManager so sync jobs complete cleanly even when phone screen locks or app is backgrounded.

### Changed
- **Pure Delta Synchronization**: Removed full-feed re-downloads on pull-to-refresh; sync relies strictly on slot watermarks for fast ~100ms updates.
- **Shared Ignore/Whitelist State**: Shared UserViewModel across IgnoreListScreen and WhitelistScreen navigation routes to update rules instantly on history screen re-entry.

---

## [1.6.19] - 2026-07-31

_Instant Slot Detail Navigation_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.6.19 Released!**
>
> **Improvements & Fixes**
> • **Instant Slot Detail Navigation**: Zero-latency screen transitions when opening slot details with dynamic player alias support.
> • **On-Demand Autocomplete**: Lazy loading for item and location autocomplete options to accelerate screen loads.
> • **Preferences UI Cleanup**: Streamlined notification preference screens.
>
> Update now on Google Play or download the latest APK from GitHub Releases!
> ```

### Changed
- **Instant Slot Detail Navigation**: Shared UserViewModel across navigation routes for immediate transition into slot details and player alias rendering.
- **On-Demand Autocomplete Loading**: Deferred item/location autocomplete fetching until user interacts with dropdowns to eliminate initial screen load lag.
- **Preferences UI Cleanup**: Removed duplicate help section from notification preferences screen.

---

## [1.6.18] - 2026-07-30

_Push Notification Whitelist & System Improvements_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.6.18 Released!**
>
> **New Features**
> • **Push Notification Whitelist**: Want notifications for specific items (e.g. Progressive Swords, Bombs) even if filler/category mutes are enabled? You can now whitelist individual items or item groups per-game or globally!
>
> **Improvements & Fixes**
> • **Instant History Sync**: Refactored item history synchronization using cursor watermarks for faster load times and zero missing items.
> • **Item Index Tracking**: Received item ordering now tracks Archipelago's native item index for 100% item fidelity.
> • **Cheese Tracker Sync**: Improved slot claim validation and conflict resolution.
>
> Update now on Google Play or download the latest APK from GitHub Releases!
> ```

### Added
- **Push Notification Whitelist**: Added WhitelistScreen UI allowing users to whitelist specific items or item groups to always receive notifications regardless of mute settings.
- **What's New Dialog**: Interactive bottom sheet displaying release highlights upon app update.

### Changed
- **Cursor-Based History Sync**: Replaced timestamp-based history watermarks with integer cursors for faster sync and robust retry handling.

### Fixed
- **History Job Cancellation**: In-flight refresh coroutines in HistoryViewModel are properly cancelled on repeated pull-to-refresh.
- **Database Migration 20->21**: Automatically cleans up legacy timestamp watermarks upon Android app upgrade.

---

## [1.6.14] - 2026-06-24

_App Release v1.6.14_

### Fixed
- **Cheese Tracker Slot Claim**: Fixed slot claim UI state syncing for unauthenticated slots.
