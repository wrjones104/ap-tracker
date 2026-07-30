# Changelog

All notable changes to **Archipelago Alerts** (AP Tracker) will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.6.18] - 2026-07-30

> **Discord Copy-Paste Format:**
> ```markdown
> **Archipelago Alerts v1.6.18 Released!**
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
- **Item & Group Whitelist**: Introduced `UserWhitelistItem` backend model and Android UI screen (`WhitelistScreen`). Users can mark specific items or item groups as priority targets to always receive push notifications, bypassing ignore/mute rules.
- **`GET /api/whats_new` Endpoint**: Backend API to dynamically fetch release notes and patch highlights.

### Changed
- **Cursor-Based History Sync**: Replaced timestamp-based history watermarks with `max_id` integer cursors, drastically speeding up Android sync and eliminating lockout bugs.
- **Native `item_index` Preservation**: Backend poller now logs and orders received items using Archipelago's native `item_index` sequence.
- **Database Performance**: Added composite performance indexes for history queries and room subscription polling.

### Fixed
- **History Job Cancellation**: In-flight refresh coroutine jobs in Android `HistoryViewModel` are properly cancelled on repeated pull-to-refresh.
- **Database Migration 20->21**: Automatically cleans up legacy timestamp watermarks upon Android app upgrade.

---

## [1.6.14] - 2026-06-24

### Fixed
- **Cheese Tracker Slot Claim Handling**: Fixed an issue where the Cheese Tracker slot claim handling didn't work correctly with unauthenticated slots.
- **Milestone Groups Optimizations**: Improved the backend process that supplies the items and item_groups for the Milestone Group builder.
