---
name: version-manager
description: Reviews recent git changes across both the application (frontend/mobile) and backend server, recommends semantic version bumps (Major, Minor, Patch) for each independently, updates version files and changelog entries, regenerates markdown changelogs, and drafts platform-specific release notes for Discord, Google Play Store, and GitHub Releases. Use when cutting a release, bumping versions, updating changelogs, or reviewing shipped changes.
---

# Version Manager & Release Skill

This skill provides an end-to-end workflow for analyzing changes, determining Semantic Versioning (SemVer) increments, updating version files and changelog records, and drafting platform release notes.

> **Universal Compatibility**: This skill is structured to work seamlessly in both **Google Antigravity** (`.agents/skills/`) and **Claude Code** (`.claude/skills/` or `~/.claude/skills/`).

---

## 1. Core Architecture & Single Source of Truth

In this repository (Archipelago Alerts):
- **Single Source of Truth**: `backend/app/data/changelog.json` contains two newest-first arrays: `app_releases` (Android) and `server_releases` (Backend).
- **Generated Changelogs**: `android/CHANGELOG.md` and `backend/CHANGELOG.md` are derived from `changelog.json` using `python scripts/generate_changelog.py`. Never edit markdown changelogs manually.
- **Android App Versioning**: Backed by `android/app/build.gradle.kts` (`versionName` string and integer `versionCode`).
- **Backend Versioning**: Dynamically resolved from the latest entry in `changelog.json` (`server_releases[0].version`) via `get_server_version()`.

*(If ported to other repositories, adapt the version files to `package.json`, `pyproject.toml`, `Cargo.toml`, or the project's standard configuration.)*

---

## 2. Release & Versioning Workflow

Follow these steps sequentially whenever cutting a release or incrementing versions:

```
[1. Inspect Git Diff] ➔ [2. Determine SemVer] ➔ [3. Draft Notes & Confirm] ➔ [4. Update Files] ➔ [5. Verify & Test]
```

### Step 1: Inspect Changes (Dual-Lens Review)
Review recent commits and diffs since the last release tag or changelog entry:
1. Run `git log -n 15 --oneline` and `git diff <last-release-commit>..HEAD --stat`.
2. Inspect changes through two distinct lenses:
   - **App Lens** (`android/`): UI updates, compose screens, navigation, client storage/networking, dependency upgrades (e.g. SDK target, AndroidX).
   - **Backend Lens** (`backend/`, `alembic/`): Database schema changes/Alembic migrations, REST API routes, models, poller/worker logic, background services.

### Step 2: Semantic Versioning Decision Framework
Evaluate each component independently using [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) (`MAJOR.MINOR.PATCH`):

| Bump Type | Trigger Criteria (App / Client) | Trigger Criteria (Backend / Server) |
| :--- | :--- | :--- |
| **`MAJOR`** (`X.0.0`) | Breaking client architectural changes; removing support for earlier OS or backend versions without backward compatibility. | Breaking API changes (e.g. deleted endpoints/fields); destructive DB migrations requiring hard breaking client cutoffs; raising `min_app_version`. |
| **`MINOR`** (`1.X.0`) | New screens, major feature sets, templates, new interactive workflows, OS modernization (e.g. Edge-to-Edge). | New database tables/columns with Alembic migrations; new REST API endpoints/Blueprints; backward-compatible feature expansions. |
| **`PATCH`** (`1.6.X`) | Bug fixes, visual polish, padding/styling corrections, crash prevention, patch-level library updates. | Bug fixes, performance tuning, query optimizations, background sync error handling, rate-limit adjustments. |

*Note: The App and Backend version numbers can be incremented independently or together depending on what changed.*

### Step 3: Draft Release Highlights & Channel Snippets
Draft 2–5 plain-English highlights focused on **user benefits** (translate technical jargon into clear descriptions):
- Categorize each highlight into `features` (`Added`), `improvements` (`Changed`), or `fixes` (`Fixed`).
- Draft the 3 release-note variants:
  1. **Discord** (`release_notes.discord`):
     - Casual tone, Markdown formatted (`**bold**`, `•` bullets).
     - Under 1,200 characters.
     - Include download links at the bottom.
     - *Note*: If a backend release has no distinct user-visible changes separate from the app announcement, set `discord: ""` to avoid duplicate community pings.
  2. **Google Play Console** (`release_notes.play_store`):
     - **App releases only** (leave `""` for backend).
     - Plain text only (no markdown, no backticks, plain `•` or `-` bullets).
     - **Strictly &le; 500 characters**.
  3. **GitHub Release** (`release_notes.github`):
     - Structured markdown with `### Added`, `### Changed`, `### Fixed`.
     - Technical details, endpoint paths, or migration IDs are welcome here.

### Step 4: Propose to User Before Writing
Present the proposed version bump(s), release title, highlights, and character-counted snippets to the user in chat for confirmation.

### Step 5: Update Files & Regenerate
Once approved:
1. **For App Releases**:
   - Update `versionName` (e.g. `"1.7.0"`) and increment `versionCode` (e.g. `23` &rarr; `24`) in `android/app/build.gradle.kts`.
2. **For Changelog Entries**:
   - Prepend the release object to `app_releases` or `server_releases` in `backend/app/data/changelog.json`.
3. **Regenerate Markdown**:
   - Run: `python scripts/generate_changelog.py` (or `.\venv\Scripts\python scripts/generate_changelog.py` on Windows).

### Step 6: Verify & Test
Execute automated guardrails to ensure zero drift:
1. Check changelog and Gradle alignment:
   ```bash
   python scripts/generate_changelog.py --check
   ```
2. Run backend test suite:
   ```bash
   # Unix:
   PYTHONPATH=backend pytest backend/tests
   # Windows (PowerShell):
   $env:PYTHONPATH="backend"; .\venv\Scripts\python -m unittest discover backend/tests
   ```

### Step 7: Output Release Snippets
Present all formatted release snippets in full in the chat response so the user can easily copy and paste them directly to Discord, Google Play Console, and GitHub Releases.
