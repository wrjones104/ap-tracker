<!-- GENERATED FILE — do not edit by hand.
     Source of truth: backend/app/data/changelog.json
     Regenerate with: python scripts/generate_changelog.py -->

# Android App Changelog

All notable changes to the **Android App** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This file is generated from `backend/app/data/changelog.json`.

## [1.9.1] - 2026-08-28

_The Console Shows Names, Not Numbers_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts v1.9.1 is out!**
>
> 🔤 **The console shows names again** — items, locations and players were printing as raw ID numbers. They resolve properly now, and player names appear the moment you connect.
>
> ⚡ **Faster, and it works offline** — each game's name list is stored on your device now. Reopening a room you have visited before needs no download at all, so the console is readable even on a bad connection.
>
> 🔧 **Show Finished stays put** — upgrading to 1.9.0 could quietly flip My Slots over to showing finished slots. Your choice now carries across properly and follows your account, not just one device.
>
> Grab it on Google Play: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> Fixed: the console was showing raw ID numbers instead of item, location and player names. Names now appear as soon as you connect.
>
> Improved: each game's name list is stored on your device, so reopening a room you have visited before loads instantly and works without a connection.
>
> Fixed: upgrading could silently switch My Slots to showing finished slots. Your Show Finished choice now carries over correctly and follows your account.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - On-device datapackage cache (`cached_game_datapackages`, Room migration 24 → 25), keyed by Archipelago's per-game checksum. Because a checksum is a content hash, rows never expire and two rooms running the same game share one entry.
>
> ### Changed
> - Player names and slot → game mapping are now built from the Archipelago handshake (`RoomInfo.datapackage_checksums`, `Connected.players`, `Connected.slot_info`) instead of a separate API call, so player names render before any ID table loads. `Connected.players` is filtered to the connecting client's own team, since slot numbers restart at 1 per team.
> - ID tables are fetched from the new `GET /datapackage/checksum/<checksum>` endpoint, cache first. Failures retry with backoff and partial results are published rather than discarded; the map is never reset to null.
> - Autocomplete no longer carries the console's ID tables as a passenger.
>
> ### Fixed
> - Console rendered raw IDs for items, locations and players. `_datapackage` was only populated by `fetchAutocompleteData`, whose call sites are all milestone/hint dialog `LaunchedEffect`s; `e8f56c5` (1.6.19) removed the eager load from `SlotDetailScreen`, leaving no path that ran on connect.
> - IDs from the generic `Archipelago` world (location -1 Cheat Console, -2 Server) now resolve via a fallback lookup against that package.
> - `migrateLegacyValue` was gated on `prefs.contains("ui_show_finished")`, which `HistoryViewModel` seeds from the server default on first profile fetch, making the migration unreachable for the existing install base and silently flipping My Slots on upgrade. The legacy value now wins, and `UserViewModel` syncs the carried-over value to the server.
> - `setFinishedDefinition` now rolls back the local store on a failed save, matching `updateSlotFinishedDefinition`.
>
> ### Internal
> - Kotlin unit tests run in CI; new `DatapackageLookupTest` covers per-team slot scoping, per-game ID uniqueness, and generic-world fallback.
> - Removed the dead `UpdateGlobalPrefsRequest` model.
> ```

### Changed
- **On-Device Game Data Cache**: Item and location name tables are stored on the device, keyed by the checksum Archipelago assigns each game. Because that checksum is a content hash, a stored table can never go out of date, and two rooms running the same game share one copy. The console no longer waits on the network to become readable.
- **Names Resolve From The Room Connection**: Player names and each slot's game now come from the Archipelago handshake itself rather than a separate request, so they are current and appear with no delay. Multi-team rooms are handled correctly: slot numbers restart at 1 for each team, and only your own team's players are used.

### Fixed
- **Console Printed IDs Instead Of Names**: Nothing loaded the ID-to-name tables when the console connected. They were only fetched as a side effect of opening a milestone or hint dialog, so anyone who never opened one saw raw numbers for the entire session. Connecting now loads them directly, and a failed load is retried instead of leaving the console unreadable.
- **Show Finished Flipped On Upgrade**: The migration that carries your old slots-only “show finished” choice into the unified setting could not run, because the new key was already being filled in from the server before the migration looked for it. Since the old flag defaulted to hiding finished slots and the new one defaults to showing them, upgrading silently reversed the setting for anyone who had not touched it.
- **Finished Setting Could Drift From Your Account**: Changing the account-wide “Finished means” setting kept the new value on the device even when the save failed, so every screen filtered on a definition the server did not have. A failed save now rolls back.
- **Generic Archipelago Locations Showed As Numbers**: Locations belonging to Archipelago itself rather than to a game -- Cheat Console and Server -- were never resolvable, because they live in their own data package. The console now falls back to it.

---

## [1.9.0] - 2026-08-20

_You Decide What “Finished” Means_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.9.0 Released!**
>
> **New**
> • **You decide what "finished" means**: goaled, all checks, both, or either. Set it once in Settings, or override it for a single slot. Everyone starts on goaled, so nothing changes unless you want it to.
> • **Built for release-off rooms**: a slot that goaled but still has items to send no longer has to disappear from your lists.
> • **Check counts on slot cards**: see "215/375 checks" right in the list.
>
> **Improved**
> • Room headers now show how many slots are active vs finished, so you can tell when the filter is hiding something.
> • One "Show Finished" toggle now covers the slots list, history, and both widgets — including the Milestones widget, which used to ignore it.
>
> **Fixed**
> • A room no longer vanishes from My Slots the moment its last slot finishes.
> • "Copy settings to all slots" no longer wipes your per-slot "Suppress if I'm connected" overrides.
>
> GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
> Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> New: You choose what "finished" means - goaled, all checks, both, or either. Set it globally or per slot. Everyone starts on goaled, so nothing changes unless you want it to.
>
> New: Slot cards show check counts, and room headers show active vs finished slots.
>
> Fixed: A room no longer disappears from My Slots when its last slot finishes.
>
> Fixed: "Copy settings to all slots" no longer clears your per-slot connected-suppression overrides.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Added
> - User-defined "finished" definition: `goal`, `all_checks`, `both`, or `either`, as an account default with an optional per-slot override. Defaults to `goal`, so behavior is unchanged until a user opts in.
> - Slot cards show `checks_done / total_locations`, and room headers carry a persistent active/finished progress indicator.
> - Room DB migration 23 -> 24, storing both completion facts on history rows and the milestone cache so widgets can filter without a network call.
>
> ### Changed
> - The slots list and history feed now share one server-synced "show finished" toggle. The former slots-only local flag is migrated once, and only when it was explicitly set.
> - Status flags are Material vector icons rather than hardcoded emoji, and distinguish "goaled, still sending" from "fully done" (#262).
> - The Milestones widget honors the show-finished toggle (#268).
>
> ### Fixed
> - `applySlotSettingsToAll` cleared `suppress_connected` on every target slot. Both slot-preference write paths now build from a single `toPrefsRequest()` builder, since `serializeNulls()` means an omitted field arrives as an explicit null and clears the override (#261).
> - The slots list dropped a room entirely once every slot was filtered out, so a room vanished when its last slot finished. Search emptying a room still removes it; the finished filter no longer does.
> ```

### Added
- **Finished Definition Setting**: A new “Finished means” setting offers Goaled, All checks, Goaled + all checks, and Goaled or all checks. It lives in Settings under the finished-slot notification toggle, and every tracked slot can override it from that slot's settings sheet. It governs which slots are hidden by “Show Finished” across the slots list, history, hints, and both widgets.
- **Check Counts And Room Progress**: Slot cards show completed locations against the slot's total. Room headers carry a progress bar and an active-versus-finished count that is always present, whatever the finished filter is doing, so hidden slots are never a surprise.

### Changed
- **One “Show Finished” Toggle**: The slots list used to keep its own separate switch that lived only on that device, while history and the widgets used the account-wide one. They are now a single setting that follows you between devices. If you had set the old slots-only switch, its value carries over.
- **Status Icons Instead Of Emoji**: The finished flag on slots, players, and history rows is now a drawn icon rather than an emoji character. It renders the same on every device, screen readers can describe it, and it can tell “goaled, still sending” apart from “fully done” at a glance.
- **Milestones Widget Respects Show Finished**: The Milestones widget kept showing progress for slots the rest of the app had already hidden. It now follows the same toggle and the same definition as everything else.

### Fixed
- **Finished Rooms No Longer Disappear**: With finished slots hidden, a room vanished from My Slots entirely once every one of its slots was finished. The room now stays in the list with a note about what is hidden and a one-tap way to show it. Searching still removes rooms that do not match, which is what searching is for.
- **Copy Settings To All Slots Kept Your Overrides**: Using “copy settings to all slots” silently cleared the “Suppress if I'm connected” setting on every other slot in the room, with no sign anything had happened. All thirteen of the other preferences copied correctly; that one was left out of the list the copy was built from. The copy is now built from one place, so a preference cannot go missing from it again.

---

## [1.8.2] - 2026-08-17

_Milestone Group Progress_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.8.2 Released!**
>
> **Fixes**
> • **Item Group Milestones Show Progress**: Milestones built from item groups (Essences, Medals, and the like) sat at "Tracked on server" with an empty bar. They now show a real count and fill in like every other milestone.
> • **More Accurate Counts**: Progress no longer undercounts items that aged out of your history or were hidden by your ignore list.
>
> Pinned widgets pick this up on their own - no need to remove and re-add them.
>
> GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
> Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
> ```

> **Play Console — What's New Copy-Paste:**
> ```markdown
> Fixed: Milestones built from item groups now show real progress in the Milestones widget. They previously showed "Tracked on server" with an empty bar.
>
> Fixed: Milestone progress no longer undercounts items that aged out of your history or were hidden by your ignore list.
>
> Pinned widgets pick this up automatically.
> ```

> **GitHub Release Copy-Paste:**
> ```markdown
> ### Fixed
> - **Item-group milestone progress**: The Milestones widget left any requirement backed by a datapackage item group indeterminate and excluded it from the totals, so a milestone made entirely of groups rendered as "Tracked on server" with an empty bar. Group requirements now display real progress from the server's `acquired` count. Requires server 1.8.0.
> - **Undercounted progress on plain items**: counts now take `max(local history, server acquired)`. Local history is live but lossy — pruned by the retention window, and missing anything excluded by an ignore rule.
> ```

### Fixed
- **Item Group Milestone Progress**: The Milestones widget could not count requirements built from an item group, because it counts items by name on your device and an item group is not an item name. Those milestones sat at "Tracked on server" with an empty bar, and mixed milestones quietly left their groups out of the total. Progress for them now comes from the server.
- **Undercounted Progress**: Milestone progress is now the higher of what your device has in history and what the server counts. History is pruned after 90 days and leaves out anything an ignore rule hid, so it could report less progress than the milestone was actually credited with.

---

## [1.8.1] - 2026-08-16

_Widget Loading Fix_

> **Discord Copy-Paste:**
> ```markdown
> **Archipelago Alerts Android App v1.8.1 Released!**
>
> **Fixes**
> • **Widgets Load Again**: The home screen widgets added in 1.8.0 came up empty on the Play Store build and never filled in. They now load and refresh the way they were meant to.
> • **Manual Refresh Works Again**: Refreshing by hand now fetches new data straight away instead of leaving you to wait for the next background sync.
>
> If you pinned a widget on 1.8.0 and gave up on it, this is the update that makes it work - no need to remove and re-add it.
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
> ### Fixed
> - **Widgets never loaded in minified builds**: WorkManager failed with `NoSuchMethodException: androidx.work.OverwritingInputMerger.<init> []` before any worker ran. R8 full mode (the default since AGP 8) does not implicitly retain default constructors for `-keep` rules that carry no member spec, so it stripped the constructor WorkManager instantiates reflectively. `work-runtime` ships `-keep class * extends androidx.work.InputMerger`, but that rule is written for ProGuard-compat semantics. Added an explicit `<init>();` member spec to `proguard-rules.pro`.
> - **Every one-time WorkRequest failed before `doWork()`**: `WorkerWrapper.runWorker` skips input merging for periodic work, so the fault was scoped to `OneTimeWorkRequest` - the widget refresh in `RecentItemsWidget` and the foreground sync in `HistorySyncManager`. The 15-minute periodic sync in `MyApplication` still ran, so data arrived eventually but never on demand. `prodDebug` was unaffected because the debug build type never minifies, which is what hid this until it reached production.
>
> ### Changed
> - **New `minified` build type** (`./gradlew :app:assembleProdMinified`): `initWith(release)`, so it inherits the same R8 pipeline, resource shrinking, and proguard files, but is debuggable and debug-signed. Verified it reproduces the stripped constructor when the keep rule is removed, so this class of fault surfaces during testing rather than in the store build. It reuses the `.debug` application id because `google-services.json` only declares Firebase clients for `com.jones.aptracker` and `com.jones.aptracker.debug`, so it installs over `prodDebug`, and it borrows the debug manifest so `devMinified` can still reach `10.0.2.2` over cleartext.
> ```

### Fixed
- **Home Screen Widgets Not Loading**: Both widgets stayed empty on the Play Store build because the background job that fills them failed before it could start. Widgets pinned on 1.8.0 will start working on this update without needing to be removed and re-added.
- **On-Demand Sync**: Refreshing from the app or from a widget now pulls new data immediately. Previously these requests were dropped and only the automatic sync every 15 minutes brought anything in.

---

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
> • **Widget Customization**: Pin a widget to one room or all of them, give it a custom title, choose Standard or Compact text, and hide the milestone flags or item colour dots if you prefer a plainer look.
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
> - **Recent Items Home Screen Widget**: Glance-based widget with responsive small/medium/large layouts, item classification colours (Progression, Useful, Filler, Trap), and on-demand refresh.
> - **Milestones Home Screen Widget**: Shows milestone group progress per tracked slot - progress bar, acquired/required counts, and per-item breakdown - scoped to a single room or all active rooms.
> - **Android Notification Channels**: Push notifications are categorized into dedicated system channels under the "Game & Room Alerts" group (`channel_progression`, `channel_non_progression`, `channel_hints`, `channel_general`), enabling per-category sound, vibration, heads-up, and DND control.
> - **Widget Configuration**: Per-room scoping with a searchable room picker, optional custom widget titles on both widgets, Standard/Compact density presets, and toggles for the milestone flag emoji and the item colour dots.
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
- **Widget Personalization**: Give any widget a custom title, and turn off the milestone flags or the item colour dots if you would rather keep things plain.
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
