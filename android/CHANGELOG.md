# Android App Changelog

All notable changes to the **Archipelago Alerts Android Application** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.6.18] - 2026-07-30

> **Discord Copy-Paste Format:**
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
- **Push Notification Whitelist**: Added `WhitelistScreen` UI allowing users to whitelist specific items or item groups to always receive notifications regardless of mute settings.
- **What's New Dialog**: Interactive bottom sheet displaying release highlights upon app update.

### Changed
- **Cursor-Based History Sync**: Replaced timestamp-based history watermarks with integer cursors for faster sync and robust retry handling.

### Fixed
- **History Job Cancellation**: In-flight refresh coroutines in `HistoryViewModel` are properly cancelled on repeated pull-to-refresh.
- **Database Migration 20->21**: Automatically cleans up legacy timestamp watermarks upon Android app upgrade.

---

## [1.6.14] - 2026-06-24

### Fixed
- **Cheese Tracker Slot Claim**: Fixed slot claim UI state syncing for unauthenticated slots.
