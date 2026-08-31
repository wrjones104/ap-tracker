---
name: release-notes
description: Collaboratively draft a new release entry for backend/app/data/changelog.json — user-friendly highlights plus separate Discord, Play Console, and GitHub Release snippets — then write it in and regenerate the CHANGELOG.md files. Use when cutting an Android or backend release, or when asked to "write release notes", "draft a changelog entry", "what's new for this release", or similar.
---

# Release Notes

This skill turns a plain-language description of what shipped into a `changelog.json`
entry plus three ready-to-paste release-note snippets (Discord, Google Play Console,
GitHub Release). `backend/app/data/changelog.json` is this project's single source of
truth for release notes and versions — see [LLM.md](../../../LLM.md) for the full
system. Nothing else needs to be hand-edited; `scripts/generate_changelog.py` derives
`android/CHANGELOG.md` and `backend/CHANGELOG.md` from whatever this skill writes.

This file is meant to be tweaked over time — the **Voice & Style** section below is
where to adjust tone; the **Channel Specs** section is where to adjust hard
constraints (length limits, formatting rules). Edit either independently.

## Flow

1. **Figure out component and version.**
   - Ask (or infer from context) whether this release is for the **Android app** or
     the **backend/server** — they version independently and go in different arrays
     (`app_releases` vs `server_releases`).
   - Read the current newest entry in the relevant array in `changelog.json` to see
     the last version number, so you can suggest the next one. Don't guess a bump
     type (patch/minor) — ask, or infer from the size of the change.
   - For an **app** release, also check `android/app/build.gradle.kts` `versionName`.
     If it's already ahead of the changelog (someone bumped it for a build before
     writing notes), use that version rather than inventing a new one.
   - The two components aren't symmetric, and that's intentional: the app version is
     backed by a real build artifact (`build.gradle.kts`, which Gradle needs to
     produce a signed APK, and Play requires a strictly increasing `versionCode`),
     so it gets bumped when a build is about to ship. The **server has no such
     file** — it's one continuously-redeployed container, not a discrete release
     artifact. Writing a new entry into `server_releases` *is* the entire act of
     "cutting a server release"; there's nothing else to bump or reconcile. Don't
     bump the server version on every commit — batch whatever's landed since the
     last entry into one version, the same way the historical entries already do
     (e.g. `1.6.19` alone bundled five unrelated backend commits).

2. **Gather what actually shipped.**
   - Ask the user to describe the changes in their own words, or point you at
     something concrete (a branch, recent commits, a PR). If they point you at code,
     use `git log`/`git diff` against `main` to see what actually changed — don't
     rely on memory of an unrelated conversation.
   - Don't invent scope. If something is ambiguous or you're not sure it's
     user-facing, ask rather than guessing.

3. **Draft highlights, categorized.**
   - Distill the raw changes into 2–5 highlights, each a short **title** + one-sentence
     **description**, written for the *end user* — see Voice & Style below.
   - Sort each highlight into `features` (new capability), `improvements` (changed
     existing behavior), or `fixes` (bug fix). A highlight can only live in one
     category, but the same wording appears in the flat `highlights` list too — keep
     both in sync (this mirrors the existing entries in `changelog.json`).
   - Draft a short release `title` (the headline feature, or a short phrase spanning
     the top 2 if there's no single standout).

4. **Draft the three release-note snippets** per the Channel Specs below.

5. **Preview before writing anything.** Show the user:
   - The draft highlights/categories/title.
   - All three snippets, each in its own fenced block, with the Play Console one's
     character count shown so they can see it's within budget.
   - Ask for edits or confirmation. Iterate in chat — don't write to disk until
     they've signed off.

6. **Write and regenerate.**
   - Prepend the finished entry to the correct array (`app_releases` or
     `server_releases`) in `backend/app/data/changelog.json`, keeping the existing
     2-space-indent JSON formatting.
   - Run `python scripts/generate_changelog.py` to regenerate the two `CHANGELOG.md`
     files.
   - If this was an app release and `build.gradle.kts` `versionName` doesn't yet
     match, remind the user to bump `versionName`/`versionCode` — then run
     `python scripts/generate_changelog.py --check` to confirm it's now green.

7. **Hand back the three snippets in your chat response, in full**, clearly labeled,
   so the user can copy-paste each one directly into Discord, Play Console, and the
   GitHub Release form without having to open the JSON file.

## Voice & Style

Past entries in this project leaned heavily on implementation detail — class names,
internal mechanisms, jargon ("WorkManager and ApplicationScope", "cursor watermarks",
"db_process_semaphore"). The user wants highlights to read as **plain, high-level,
benefit-first** descriptions instead. Translate, don't transcribe:

- ❌ "Delegated sync execution to HistorySyncManager and Android WorkManager so sync
  jobs complete cleanly even when phone screen locks or app is backgrounded."
- ✅ "History now keeps syncing in the background, even if your screen locks or you
  switch apps."

- ❌ "Introduced db_process_semaphore (limit=3) to throttle concurrent synchronous
  database processing during room poll cycles."
- ✅ "Smoothed out server CPU spikes during busy polling cycles."

Guidelines:
- Say what changed *for the user*, not how it was built.
- Name a class, file, or internal system only if the user explicitly wants a
  technical/developer-facing note (e.g. sometimes appropriate for the GitHub Release
  channel — see below).
- It's fine to be a little upbeat/casual (this is a small hobby-community project),
  but don't oversell — no marketing-speak for minor fixes.

### Length budgets

**Be brief.** Entries have repeatedly drifted into 300–500 character paragraphs that
re-argue the whole diff. Nobody reads a changelog that way. These are hard budgets,
not aspirations — count them before presenting, and cut rather than compress into
mush:

| Field | Budget |
|---|---|
| `highlights[].description` | **1 sentence, ≤ 180 chars** |
| `categories[*][].description` | **1 sentence, ≤ 160 chars** |
| `release_notes.discord` | **≤ 900 chars** including the download links |
| `release_notes.play_store` | **≤ 500 chars** (Google's hard cap) |
| `release_notes.github` | one line per bullet; **≤ 3500 chars** total |

The recurring failure is writing the *cause* as well as the effect. State the effect;
the cause belongs in the commit message and the issue, both of which are already
written by the time this skill runs.

- ❌ "Rooms and Slots were two tabs showing the same rooms that disagreed about what
  tapping one meant — one opened the activity feed, the other expanded the slots — so
  you ended up bouncing between them to reach the thing you had already tapped. They
  are now one tab. Tapping a room expands it to the slots inside it. Manage Slots sits
  at the end of that list instead of three taps deep inside the rename dialog…"
- ✅ "Rooms and Slots are one tab now. Tap a room to expand it to its slots, with
  Manage Slots right there and Room Activity in the overflow menu."

The GitHub channel is the one place a mechanism is welcome — but one line of it, not a
paragraph. If a fix genuinely needs the full story, link the issue instead of retelling
it.

## Channel Specs

Each snippet targets a different audience and platform, so the same release reads
differently in each:

**Discord** (`release_notes.discord`)
- Audience: the community Discord, people who already use the app and want to know
  what's new.
- Format: casual, Discord markdown OK (`**bold**`, `•` bullets), a short header line
  with the version. No hype/CTA closing line ("Update now on...!") — the user finds
  that tone too excitable; just end with the download links (see below).
- Length: **under 900 characters** including the links, so it reads as one clean
  message rather than a wall someone scrolls past.
- Add a section at the very end with download links like this:
     GitHub: <https://github.com/wrjones104/ap-tracker/releases/latest>
     Play Store: <https://play.google.com/store/apps/details?id=com.jones.aptracker>
- **Skip Discord entirely when there's nothing new to tell users.** This comes up
  when one commit touches both app and server code (common in this project) and the
  app release already announced the user-facing effect — a second Discord post for
  the server release would just repeat it. Leave `discord: ""` in that case rather
  than padding out a redundant announcement; still fill in `github` normally.

**Play Console — "What's new"** (`release_notes.play_store`)
- **App releases only.** The backend has no Play Store listing — always leave this
  `""` for `server_releases` entries, same as historical ones.
- Audience: prospective/existing users browsing the Play Store listing — much wider
  and less invested than Discord.
- Format: **plain text only** — Play Store strips markdown, so no `**bold**` or
  backticks. Short bullet lines using a plain `•` or `-` are fine. Lead with the most
  user-visible change.
- Length: **hard limit of 500 characters** (Google Play's actual cap on this field).
  Count it before presenting — if over, cut secondary items rather than shortening
  everything into mush.

**GitHub Release** (`release_notes.github`)
- Audience: developers, contributors, technically-curious users browsing GitHub.
- Format: markdown, structured like `### Added` / `### Changed` / `### Fixed`
  (mirrors the `categories` breakdown). This is the one channel where naming a
  specific endpoint, file, or mechanism is appropriate if it's genuinely useful
  context.
- Length: **under 3500 characters** — favor scannable over exhaustive. One line per
  bullet. Link an issue rather than retelling it.

## Notes for historical entries

Entries from before this skill existed only have `release_notes.discord` populated;
`play_store` and `github` are empty strings. That's intentional — those releases
already shipped, so backfilling invented copy for them isn't worth doing. Only new
entries need all three filled in.
