<!-- GENERATED FILE — do not edit by hand.
     Source of truth: backend/app/data/changelog.json
     Regenerate with: python scripts/generate_changelog.py -->

# Android App Changelog

All notable changes to the **Android App** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This file is generated from `backend/app/data/changelog.json`.

## [1.8.0] - 2026-08-16

_Home Screen Widgets & Notification Channels_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.8.0 Released!**
>
> **New Features & Improvements**
> • **Recent Items Widget**: See the latest items flowing through your multiworld right on your home screen.
> • **Milestones Widget**: Track progress toward your milestone goals at a glance, with a progress bar for every tracked slot.
> • **Categorized Notifications**: Alerts are now split into **Progression Items**, **Non-Progression Items**, **Hints**, and **General & System**, so you can give each its own sound, vibration, and Do Not Disturb rules in Android settings.
> • **Widget Customization**: Pin a widget to one room or all of them, give it a custom title, choose Standard or Compact text, and hide the milestone flags or item color dots if you prefer a plainer look.
> • **Stays Current**: Widgets refresh in the background as new items arrive, and tapping one opens the app right where you were looking.
>
> GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
> Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> New: Recent Items home screen widget - see the latest items in your multiworld at a glance.
>
> New: Milestones home screen widget - track progress toward your goals with a bar for every tracked slot.
>
> New: Categorized notifications - give progression items, hints, and general alerts their own sounds and Do Not Disturb rules in Android settings.
>
> Widgets can be pinned to one room or all of them, renamed, resized, and simplified to taste.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - **Recent Items Home Screen Widget**: Glance-based widget with responsive small/medium/large layouts, item classification colors (Progression, Useful, Filler, Trap), and on-demand refresh.
> - **Milestones Home Screen Widget**: Shows milestone group progress per tracked slot - progress bar, acquired/required counts, and per-item breakdown - scoped to a single room or all active rooms.
> - **Android Notification Channels**: Push notifications are categorized into dedicated system channels under the "Game & Room Alerts" group (`channel_progression`, `channel_non_progression`, `channel_hints`, `channel_general`), enabling per-category sound, vibration, heads-up, and DND control.
> - **Widget Configuration**: Per-room scoping with a searchable room picker, optional custom widget titles on both widgets, Standard/Compact density presets, and toggles for the milestone flag emoji and the item color dots.
> - **Deep Linking**: Tapping a widget opens the relevant Activity Feed or room screen, filtered to that room where applicable.
>
> ### Changed
> - **Milestone data moved out of the widget composition**: `MilestonesRepository` caches the tracked-slot roster and threshold-group definitions into Room (`cached_tracked_slots`, `cached_milestone_groups`, schema v23), refreshed by the sync layer. The widget reads local data only, so it renders immediately instead of blocking on a ~750 KB roster fetch plus one `threshold-groups` request per slot from inside `provideGlance`. Per-slot fetches now run in parallel, are coalesced across concurrent callers, and are skipped entirely when no Milestones widget is placed.
> - **Aggregated history tallies**: Added `HistoryDao.getItemCountsForRoom()` so milestone progress is computed from a grouped SQL count rather than loading every history row for a room.
> - **FCM channel routing**: `MyFirebaseMessagingService` routes incoming notifications to the resolved category channel and cleans up legacy channel registrations on startup.
> - **Room-specific widget queries**: Widgets pinned to a room query that room's history directly from SQLite rather than scanning a global window.
> - **Widget title and room-alias display decoupled**: Per-item room aliases now key off the widget's room scope rather than the header text, so setting a custom title no longer changes which aliases are shown.
> ```

### Added
- **Recent Items Home Screen Widget**: See the latest items flowing through your multiworld right on your Android home screen, in a compact single-item or scrollable multi-item layout.
- **Milestones Home Screen Widget**: Track progress toward your milestone goals at a glance, with a progress bar and item breakdown for every tracked slot.
- **Categorized Notifications**: Alerts are now sorted into their own Android categories - Progression Items, Non-Progression Items, Hints, and General & System - each with its own sound, vibration, heads-up popup, and Do Not Disturb behaviour in your system settings.
- **Room Scope & Widget Setup**: Choose whether a widget follows all your active rooms or just one, with a searchable room picker during setup.
- **Tap Straight Through**: Tapping a widget opens the app on the matching Activity Feed or room, already filtered to what you were looking at.

### Changed
- **Widget Personalization**: Give any widget a custom title, and turn off the milestone flags or the item color dots if you would rather keep things plain.
- **Display Density Presets**: Pick Standard for larger, comfortable text or Compact to fit more rows into the same space.
- **Faster Widgets, Less Data**: Widgets now draw from data already stored on your phone, so they appear instantly after setup and use far less mobile data.
- **Activity Feed Filter Mirroring**: The Recent Items widget respects the same item type and ignore filters you have set in the in-app Activity Feed.

---

## [1.7.0] - 2026-08-13

_Milestone Templates & Android 15 Edge-to-Edge_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.7.0 Released!**
>
> **New Features**
> • **Milestone Templates**: Save your favorite milestone threshold groups as reusable templates! Pick templates when setting up new slots, or export/import templates as JSON to share with others.
>
> **Improvements**
> • **Collapsible Cheese Tracker Card**: The Cheese Tracker section on the Slot Details screen is now collapsible and starts collapsed by default for a cleaner view.
> • **Android 15 Edge-to-Edge**: Updated system bar insets and dependencies for full Android 15 (SDK 35+) edge-to-edge display compatibility.
>
> GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
> Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> New: Milestone Templates — save your threshold groups as reusable templates, create groups from templates, and export/import templates as JSON.
>
> Improved: Collapsible Cheese Tracker card on the Slot Details screen, collapsed by default.
>
> Improved: Android 15 edge-to-edge display support and insets modernization.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - **Milestone Templates**: Save threshold groups as reusable templates from slot details, choose templates when creating new milestone groups, and manage/export/import templates via JSON on the Milestone Templates screen.
>
> ### Changed
> - **Collapsible Cheese Tracker Card**: Made the Cheese Tracker card on `SlotDetailScreen` collapsible (starts collapsed by default) with an interactive header and status badge.
> - **Android 15 Edge-to-Edge Support**: Upgraded `androidx.activity` to 1.10.1 and `androidx.core:core-ktx` to 1.15.0 to migrate away from deprecated `Window` color APIs; corrected `WindowInsets` handling on `SettingsScreen`, `SlotOverridesScreen`, `ActivityFeedScreen`, and `ProfileScreen`.
> ```

### Added
- **Milestone Templates**: Save milestone threshold groups as reusable templates from slot details, pick templates when creating new groups, and manage/export/import them via JSON.

### Changed
- **Collapsible Cheese Tracker Card**: The Cheese Tracker card on the Slot Details screen is now collapsible with an interactive header and status badge, collapsed by default.
- **Android 15 Edge-to-Edge & Window Insets**: Updated system bar insets across screens and upgraded AndroidX dependencies to eliminate deprecated window management APIs.

---

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
