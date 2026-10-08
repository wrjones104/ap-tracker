---
name: version-manager
description: The release procedure. Reviews recent git changes across the Android app and the backend server, recommends semantic version bumps (Major, Minor, Patch) for each independently, updates version files and changelog entries, regenerates markdown changelogs, verifies, and walks the ship order (PR, deploy, device pass, Play). The release-note copy itself (highlights, Discord, Play Store, GitHub) is drafted with the release-notes skill. Use when cutting a release, bumping versions, updating changelogs, or reviewing shipped changes.
---

# Version Manager & Release Skill

This skill is the release **procedure**: analyze changes, choose Semantic Versioning (SemVer) increments, update version files and changelog records, verify, and ship in the right order.

It does **not** define how release notes read. The **release-notes** skill owns all copy rules: voice, length budgets, and the Discord / Play Store / GitHub channel specs. Step 3 hands off to it, so the two cannot drift apart.

> **Claude Code only.** Releases are cut from Claude Code, so this skill has no `.agents/skills/` copy for Antigravity. A second copy drifted seven weeks behind this one and was deleted (#448). Do not recreate it.

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
[1. Inspect Git Diff] ➔ [2. Determine SemVer] ➔ [3. Draft Copy (release-notes)] ➔ [4. Confirm] ➔ [5. Update Files] ➔ [6. Verify & Test] ➔ [7. PR & Ship Order] ➔ [8. Output Snippets] ➔ [9. Screenshots (app)]
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

### Step 3: Draft the Copy with the release-notes Skill
Invoke the **release-notes** skill and follow its Flow steps 2–4: gather what shipped, draft highlights and categories, and draft the three snippets. Skip its step 1, because the version is already chosen here, and its step 6, because this skill writes the files. Every copy rule (voice, length budgets, the Discord title line, Play Store's 500-character cap, when to leave `discord` empty) lives in release-notes. Do not restate or override them here.

### Step 4: Propose to User Before Writing
Present the proposed version bump(s) together with the release-notes preview (title, highlights, character-counted snippets) and wait for confirmation.

### Step 5: Update Files & Regenerate
Once approved, on a branch (`chore/release-app-X.Y.Z` or `chore/release-server-X.Y.Z`), never directly on `main`:
1. **For App Releases**:
   - Update `versionName` (e.g. `"1.7.0"`) and increment `versionCode` (e.g. `23` &rarr; `24`) in `android/app/build.gradle.kts`.
2. **For Changelog Entries**:
   - Prepend the release object to `app_releases` or `server_releases` in `backend/app/data/changelog.json`.
   - Insert it **as text**, matching the 4-space entry indent and CRLF line endings. The file does not survive a `json.load`/`json.dump` round trip.
3. **Regenerate Markdown**:
   - Run: `python scripts/generate_changelog.py` (or `.\venv\Scripts\python scripts/generate_changelog.py` on Windows).
4. Commit as a single `chore(release): app X.Y.Z` (or `server X.Y.Z`) commit.

### Step 6: Verify & Test
Execute automated guardrails to ensure zero drift:
1. Check changelog and Gradle alignment:
   ```bash
   python scripts/generate_changelog.py --check
   ```
2. Run the **full** backend suite, one test file per process (`unittest discover` over the directory does not work here):
   ```bash
   for f in backend/tests/test_*.py; do PYTHONPATH="backend;." venv/Scripts/python.exe -m unittest "$f" || echo "FAILED: $f"; done
   ```
   CI runs Linux, and some test bugs only show there. For a release, prefer running the same loop in Docker (`python:3.13-slim`) on a `git archive HEAD` export of the branch. Install `requirements.txt` and `backend/requirements.txt` in **separate** `pip` calls, because they pin different alembic versions.

### Step 7: Open the PR and Ship in Order
Before opening the PR, decide which side goes first. **Server first when it adds behaviour, app first when the server withdraws or moves something** an installed app relies on, or raise the floor: set `MIN_APP_VERSION` in the server's `backend/.env`, run `docker compose up -d api` (not `restart`, which keeps the old environment), and confirm `curl https://archipelagoalerts.com/config` serves the new value before deploying. Check every change in the release, including background tasks: a behaviour removed from the poller or a sync does not show up in an API contract diff. See the deploy-order gotcha in `LLM.md`. State the order in the PR.

Open the release PR. After the user merges it, walk the ship order:
- **Server release:** the user deploys `main`. The version is read from `changelog.json`, so the label updates on deploy.
- **App release:** the app fetches What's New from the server (`GET /api/whats_new/latest?version=<versionName>`), so the entry must be **on the prod server before anyone tests the build**:
  1. The user redeploys the server (a data-only change, so a plain restart is enough).
  2. Confirm it answers 200:
     ```bash
     curl -s -o /dev/null -w "%{http_code}" "https://archipelagoalerts.com/api/whats_new/latest?version=X.Y.Z&target=app"
     ```
  3. The user's device pass on a minified build (the release gate), then the Play upload.

### Step 8: Output Release Snippets
Present all formatted release snippets in full in the chat response so the user can easily copy and paste them directly to Discord, Google Play Console, and GitHub Releases.

### Step 9: Screenshots for the Discord Post (app releases)
The Discord announcement goes out with screenshots attached. They are for **Discord only**: not the GitHub release, not Play (its "What's new" is text-only), and never committed to the repo.

1. **Pick what to show.** One screenshot per highlight a user can *see*, usually 1 to 3. A new screen, control or visibly fixed layout earns one. A background, battery, data or crash fix does not.
2. **Capture on the emulator** with the dev build (`com.jones.aptracker.dev.debug`), from `main` after the release PR's fixes are merged. Portrait, default font scale, the app's normal dark theme. Show the change in its finished state: the filter switched on, the dialog open, the list scrolled to its pinned buttons. Do not tap anything that writes (Save, Add, a confirm button) just to set up a shot, unless it is on a throwaway slot you then put back.
   ```bash
   MSYS_NO_PATHCONV=1 adb -s emulator-5554 exec-out screencap -p > <scratchpad>/release-X.Y.Z/01-<slug>.png
   ```
   Screenshots taken while verifying the release's PRs can be reused if they show the final behaviour.
3. **Hand them over** with `SendUserFile`, in the order of the Discord bullets, each captioned with the highlight it illustrates. **Name anything to blur:** other players' slot names and room names are visible in most screens. The user posts from their own account and blurs those themselves before posting.
