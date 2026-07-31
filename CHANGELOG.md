# Archipelago Alerts - Project Changelog

Archipelago Alerts uses decoupled versioning for the Android application and the Backend server:

- 📱 **Android App Changelog**: See [android/CHANGELOG.md](android/CHANGELOG.md) for Android UI updates, feature additions, and app releases.
- ⚙️ **Backend Server Changelog**: See [backend/CHANGELOG.md](backend/CHANGELOG.md) for API enhancements, database migrations, and server performance fixes.

---

## Recent Release Summary

### Backend Server (`v1.6.19`) - 2026-07-31
- **Poller CPU & Resource Throttling**: Throttled concurrent room processing cycles to smooth CPU spikes.
- **Cycle Jitter & Staggering**: Added random jitter to poller sleep intervals to prevent wave synchronization.
- **SQLAlchemy Pool Tuning**: Optimized PostgreSQL connection pool size and recycling for high concurrency.

### Android App (`v1.6.18`) - 2026-07-30
- **Push Notification Whitelist**: Per-game and global item/item group whitelisting for push notifications.
- **Instant History Sync**: Refactored item history synchronization using cursor watermarks for faster load times.
- **Item Index Tracking**: Received item ordering now tracks Archipelago's native item index for 100% item fidelity.
