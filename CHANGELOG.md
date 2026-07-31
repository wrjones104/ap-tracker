# Archipelago Alerts - Project Changelog

Archipelago Alerts uses decoupled versioning for the Android application and the Backend server:

- 📱 **Android App Changelog**: See [android/CHANGELOG.md](android/CHANGELOG.md) for Android UI updates, feature additions, and app releases.
- ⚙️ **Backend Server Changelog**: See [backend/CHANGELOG.md](backend/CHANGELOG.md) for API enhancements, database migrations, and server performance fixes.

---

## Recent Release Summary

### Android App (`v1.6.19`) - 2026-07-31
- **Instant Slot Detail Navigation**: Shared `UserViewModel` across navigation routes for immediate transition into slot details and player alias rendering.
- **On-Demand Autocomplete Loading**: Deferred item/location autocomplete fetching until user interacts with dropdowns to eliminate initial screen load lag.
- **Preferences UI Cleanup**: Streamlined notification preference screens.

### Backend Server (`v1.6.19`) - 2026-07-31
- **Poller CPU & Resource Throttling**: Throttled concurrent room processing cycles to smooth CPU spikes.
- **Cycle Jitter & Staggering**: Added random jitter to poller sleep intervals to prevent wave synchronization.
- **SQLAlchemy Pool Tuning**: Optimized PostgreSQL connection pool size and recycling for high concurrency.
- **Datapackage Cache Lock**: Prevented redundant parallel datapackage fetches during autocomplete queries.
