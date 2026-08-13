# Milestone Templates — Implementation Plan

Reusable, user-owned templates for Milestone Groups. A user can save a set of
items + quantities as a named template, then start a new Milestone Group from it
on any slot of the same game. Templates can also be exported as a portable string
and shared with other users.

> Status: **MVP complete (Phases 1–6) + UX polish pass.** Branch: `feature/milestone-templates`.
> Picking back up? Read §0 first. Phase 7 (Batch Apply, post-MVP bonus) in §9 is the only
> unbuilt feature; otherwise what's left is migration/tests/changelog polish in §7.

**UX polish pass (post-Phase-6, based on the author's own hands-on testing):**
Three usability gaps were identified after using the feature end-to-end:
1. The bookmark ("save as template") icon on an existing Milestone Group wasn't
   obviously discoverable.
2. The management screen (Profile → Milestone Templates) felt decoupled from
   where templates are actually used/created (a slot's detail screen).
3. The management screen had no explanation that new templates can't be
   authored there — only edited/deleted/imported.

Fixes, all in `SlotDetailScreen.kt` / `MilestoneTemplatesScreen.kt` /
`AppNavigation.kt`:
- `ThresholdGroupSheet` gained an `allowSaveAsTemplateToggle` param — the
  Create Milestone Group sheet now has an "Also save as a template" checkbox,
  so a template can be created in the same step as the group instead of
  requiring a second trip through the bookmark icon afterward. Checking it
  makes the group name required (it doubles as the template name), enforced
  via the same enabled-button gating pattern as `nameRequired`. This changed
  `onConfirm`'s signature to `(String?, List<ThresholdGroupItemRequest>,
  Boolean) -> Unit` — all three call sites (create, edit-group, edit-template)
  were updated; the latter two just ignore the new flag.
- The single-group "save as template" conflict-resolution state
  (`templateOverwriteConflict`) was generalized from `Pair<ThresholdGroup,
  String>` to `Pair<List<ThresholdGroupItemRequest>, String>` so both the
  existing bookmark-icon flow and the new inline-checkbox flow can share one
  conflict dialog instead of duplicating it.
- A one-line gray hint ("Tap 🔖 to save a group's items as a reusable
  template.") now appears under the Milestone Groups header, only when the
  list isn't empty (so the bookmark icon is actually on screen when the hint
  shows).
- A Bookmarks icon button next to "Add" in the Milestone Groups header
  (`onNavigateToMilestoneTemplates`, threaded through `AppNavigation.kt`'s
  existing `"milestone_templates"` route) now links straight to the
  management screen from the slot detail screen — the missing link the author
  called out between "where you set them" and "where you manage them."
- `MilestoneTemplatesScreen.kt` gained a persistent `TemplatesTips` callout
  (same visual pattern as `IgnoreListTips`) explaining templates are created
  from a slot's Milestone Groups, not from this screen — shown above the list
  when templates exist; the empty state (already had similar copy) also
  gained a matching "Import a Template" shortcut button so first-time visitors
  aren't stuck looking at plain text with no obvious next action.
- Verified with a real `compileDevDebugKotlin` build — no new warnings.
  On-device visual verification wasn't completed: the only connected device
  was locked (fingerprint prompt) and unlocking someone's personal phone
  isn't something to do without them present — worth a manual pass by the
  author before merging.

---

## 0. Where things stand (resume-here notes)

**Branch:** `feature/milestone-templates` (created off `main`, pushed to origin).
Nothing has been merged yet — this branch is the entire feature so far.

**Done — Phase 1 (Backend):**
- `MilestoneTemplate` / `MilestoneTemplateItem` models in
  `backend/app/models.py` (added right before `UserIgnoreItem`).
- Alembic migration `alembic/versions/a3f8c91d2e47_add_milestone_templates.py`
  (down-revision `f92a101b1a20`, the current head at the time this was written —
  **re-check `alembic heads` before running `alembic upgrade heads` in case
  something else merged to main in the meantime**).
- `backend/app/routes/templates_routes.py` — full CRUD, registered in
  `backend/app/api.py` alongside `thresholds_bp`.
- `backend/tests/test_milestone_templates.py` — 20 tests, all passing
  (CRUD, ownership scoping, 409-on-duplicate, cascade delete, case-insensitive
  game filter, auth guard). Run with:
  ```bash
  $env:PYTHONPATH="backend;." ; python -m unittest backend/tests/test_milestone_templates.py -v
  ```
  Needs `firebase_admin` etc. installed (`pip install -r backend/requirements.txt`)
  if the environment doesn't already have them.

**Done — Phase 2 (Client plumbing):**
- `ApiService.kt` — `MilestoneTemplate` / `CreateMilestoneTemplateRequest` data
  classes (reusing `ThresholdGroupItem(Request)`), plus the four
  `/milestone-templates` endpoints.
- `UserViewModel.kt` — new `MILESTONE TEMPLATES` section: `milestoneTemplates`
  StateFlow (request-id race guard), `fetchMilestoneTemplates(game)`,
  `createMilestoneTemplate(name, gameName, items, onConflict)` (the `onConflict`
  callback is how the UI hooks the overwrite flow — see Phase 3),
  `updateMilestoneTemplate(...)`, `deleteMilestoneTemplate(...)` (optimistic
  delete with revert-on-failure, matching `deleteIgnoreItem`'s convention).

**Done — Phase 3 (Save-as-template):**
- `ThresholdGroupRow` in `SlotDetailScreen.kt` has a new `BookmarkAdd` icon
  action (`onSaveAsTemplate`) alongside Edit/Delete. Available even on
  triggered groups (unlike Edit).
- New `SaveAsTemplateDialog` composable prompts for a name (default = the
  group's name).
- On confirm → `createMilestoneTemplate(...)`. On **409** → a second dialog
  ("A template named 'X' already exists for {game} — overwrite it?") re-fetches
  that game's templates and disables the Overwrite button (small spinner) until
  the conflicting template shows up in the refreshed list — guards against a
  race where the local list hasn't caught up yet — then resolves its id and
  calls `updateMilestoneTemplate`.
- Verified with a real `compileDevDebugKotlin` build (JDK 17 via Android
  Studio's bundled JBR — plain `gradlew` needs `$env:JAVA_HOME` pointed at
  `"C:\Program Files\Android\Android Studio\jbr"` since the system default was
  JDK 8). No new warnings introduced.

**Done — Phase 4 (Start-from-template picker + apply-time diff):**
- `ThresholdGroupSheet` in `SlotDetailScreen.kt` gained `milestoneTemplates` and
  `allowTemplatePicker` params. When `allowTemplatePicker` is true and the user
  has ≥1 template for the game, a "Start from a template" button appears above
  the name field.
- The "Create Milestone Group" call site (the `showAddThresholdDialog` block)
  now fetches `fetchMilestoneTemplates(slot?.game)` alongside the existing
  autocomplete fetch, and passes `allowTemplatePicker = true`. The Edit sheet
  call site is unchanged (picker stays create-mode-only per §5b).
- Tapping the button opens a chooser `AlertDialog` (name + item-summary list,
  no inline edit/delete — management stays on the Phase 5 screen).
- Picking a template runs `resolveTemplateItems(...)` (new top-level fun,
  case-insensitive match against `availableItems`, `is_group`-aware) which
  prefills `groupName` + `selectedItems` and sets a light gray note under
  "Items & Quantities" if items were dropped or if `availableItems` was empty
  (validation-skip fallback per §5c) — never blocks.
- Verified with a real `compileDevDebugKotlin` build (same JBR JAVA_HOME
  workaround as Phase 3). No new warnings.

**Done — Phase 5 (Dedicated management screen):**
- New `ui/MilestoneTemplatesScreen.kt` — fetches *all* the user's templates
  (`fetchMilestoneTemplates()`, no game filter), groups them by `game_name`
  (sorted, with templates alphabetized within each group), and renders each as
  a card (name + item summary) with Edit/Delete icon actions.
- Edit reuses `ThresholdGroupSheet` from `SlotDetailScreen.kt` (cross-game,
  same-package, no import needed). Availability data comes from
  `userViewModel.gameAvailableItems` / `fetchGameAvailableItems(gameName)` —
  the existing full-autocomplete path (already used by `IgnoreRuleSheet`),
  **not** slot-scoped `availableItems`, since there's no slot/checksum context
  on this screen. Confirmed with `clearGameAvailableItems()` on dismiss/save.
  No apply-time diff is run here — that's slot-context-only (§5c), correctly
  N/A for cross-game authoring.
- `ThresholdGroupSheet` gained a `nameRequired: Boolean = false` param (label
  switches to "Template Name", confirm button gated on non-blank name) since
  template names are NOT NULL server-side, unlike optional Milestone Group
  names. Only the template-edit call site sets it true; the Milestone Group
  create/edit call sites are unaffected (default false).
- Delete goes through a confirm `AlertDialog` before calling
  `deleteMilestoneTemplate` (which is already optimistic client-side).
- Navigation: `onNavigateToMilestoneTemplates` threaded through
  `AppNavigation.kt` → `MainScreen.kt` → `ProfileScreen.kt`, new
  `composable("milestone_templates")` route, new "Milestone Templates"
  `ProfileMenuItem` (Bookmarks icon) placed under Whitelist.
- Verified with a real `compileDevDebugKotlin` build. No new warnings.

**Done — Phase 6 (Export / import):**
- New `network/MilestoneTemplateShare.kt` — the `APMT1:<base64url(json)>`
  envelope codec described in §6. Wire DTOs (`TemplateShareItemDto` /
  `TemplateShareEntryDto` / `TemplateShareEnvelopeDto`, all file-private) have
  nullable fields on purpose — Gson can populate a Kotlin non-null property
  with `null` on malformed/untrusted input, silently bypassing the type
  system, so every field is validated and coerced into a non-null domain
  model (`ParsedTemplate` / `ParsedTemplateItem`) before anything downstream
  touches it. `parseMilestoneTemplateShareString(...)` returns a sealed
  `TemplateImportResult` (`Success`/`Failure`); the whole parse is wrapped in
  a `try/catch` since it's arbitrary pasted text. Accepts a bare (unprefixed)
  JSON string as the lenient fallback per §6. `exportMilestoneTemplates(...)`
  takes any `List<MilestoneTemplate>`, so it already supports a future
  multi-select bundle export (§10), not just single-template.
- **Export** — a Share icon on each `MilestoneTemplateCard` in
  `MilestoneTemplatesScreen.kt` serializes that one template and hands the
  string to the Android system share sheet (`Intent.ACTION_SEND`,
  `text/plain`).
- **Import** — an Upload icon in the screen's `TopAppBar` opens a paste-string
  `AlertDialog` (`ImportTemplatesDialog`). On parse success, templates are
  imported **sequentially** through a small queue (`importItems`/`importIndex`
  state + a `LaunchedEffect` keyed on both, so each `POST` fires exactly once
  per index): each one calls the now-extended
  `UserViewModel.createMilestoneTemplate(..., onSuccess = ...)` (added an
  `onSuccess` callback alongside the existing `onConflict` one, same for
  `updateMilestoneTemplate`, to drive queue advancement). A `409` pauses the
  queue on an overwrite/skip `AlertDialog` (re-fetches templates first and
  disables "Overwrite" until the conflicting entry shows up in the refreshed
  list, same race guard as the Phase 3 save-as-template flow) rather than
  aborting the whole batch — mirrors the "handle partial failure, don't
  abort" guardrail written for the future Batch Apply phase (§9.2), applied
  here to import instead. A final "Import Complete" dialog lists a
  created/overwrote/skipped line per template so nothing is silently dropped.
  Toast feedback (`integrationMessage`/`errorMessage`) is now also wired into
  this screen, matching the pattern already used in `ProfileScreen.kt`.
- **Docs**: added a new §9 "Milestone Templates" to
  `backend/iOS_DEVELOPER_GUIDE.md` (bumping the old §9 "Push Notification
  Format" to §10) — documents the four REST endpoints and, per §6's
  cross-platform note, the full `APMT1` wire format so an iOS client can
  produce/consume identical strings.
- Verified with a real `compileDevDebugKotlin` build (one missed
  `Modifier.size` import caught and fixed by the compiler). No new warnings.

**Not started:** Phase 7 (Batch Apply, post-MVP bonus, §9) is the only
remaining item on the phase list — genuinely optional. Otherwise what's left
before this could ship is the cross-cutting §7 checklist: Alembic migration
already exists from Phase 1, but re-verify `alembic heads` before running it;
backend tests exist (20, Phase 1) but there's no Android instrumentation test
for the export/import path; and a `CHANGELOG.md` /
`backend/app/data/changelog.json` entry hasn't been written yet — held off
deliberately, since that's normally done at release-cut time (via the
`release-notes` skill) rather than mid-feature-branch.

---

## 1. Goals & decisions

| Decision | Choice | Rationale |
|---|---|---|
| **Ownership** | Per-user (private). No global/official library. | Archipelago players are too varied for global templates to carry their weight. |
| **Keying** | By **game name** (not datapackage checksum). | A template should span versions/seeds of a game. Validation bridges name→version at apply time. |
| **Name collision** | `UniqueConstraint(user_id, game_name, name)`; `POST` returns **409**; client prompts to overwrite (→ `PUT`). | One clean library, no silent dupes. |
| **Management** | Dedicated screen (Profile → Milestone Templates), full CRUD across all games. | More discoverable/complete than picker-only. |
| **Entry points** | (a) Start a group *from* a template; (b) Save an existing group *as* a template. | The two flows users asked for. |
| **Sharing** | Export template(s) to a portable string; import from a pasted string. | Lets users share a specific setup even though templates are otherwise private. |

### Context that shaped the design
- Item names rarely change or get removed across datapackage versions — additions
  are the common case. So the apply-time validation is a **light-touch** safety
  net, not a heavy gate.
- `"Items"` in the canonical Mega Man 2 example is an **item group**
  (`is_group = true`), so `is_group` must round-trip through every layer.
- The validation truth already exists client-side: the Create sheet loads
  `availableItems` via `get_slot_available_items`, which is scoped to the room's
  actual datapackage checksum for that slot's game.

### Hard limit (be honest in copy)
Validation can confirm an item **exists in this version's datapackage**. It
**cannot** confirm the item is present in *this particular seed*, or in the
requested quantity — the datapackage is the game's item *catalog*, not the seed's
item *pool*. "Matched" means *exists in this version*, never *guaranteed to drop
in your seed*.

---

## 2. Data model

Two new tables, mirroring the `ThresholdGroup` / `ThresholdGroupItem` split.
Closest existing precedent: `UserIgnoreItem` (user-owned, game-name-scoped,
`is_group`-aware) — `backend/app/models.py:157`.

```
milestone_templates
  id           PK
  user_id      FK users.id, indexed, NOT NULL
  game_name    String(255), NOT NULL, indexed
  name         String(255), NOT NULL          # required (Milestone Group names are optional; template names are not)
  created_at   DateTime, default utcnow
  items        relationship(cascade="all, delete-orphan")
  UniqueConstraint(user_id, game_name, name)   # → 409 on dup

milestone_template_items
  id           PK
  template_id  FK milestone_templates.id, NOT NULL
  item_name    String(255), NOT NULL
  quantity     Integer, NOT NULL, default 1
  is_group     Boolean, NOT NULL, default False
```

- Game names are matched **case-insensitively** on lookup (`game_name.lower()`),
  consistent with the rest of the datapackage/cache code.
- No checksum stored — name-keyed by design.

---

## 3. Backend

New blueprint `backend/app/routes/templates_routes.py`, registered alongside
`thresholds_bp`. All endpoints `@token_required` and **scoped to
`current_user.id`** (404 on another user's template, same pattern as the
threshold routes).

| Method & path | Body / params | Notes |
|---|---|---|
| `GET /milestone-templates` | `?game=<name>` (optional) | Lists the user's templates, optional game filter. |
| `POST /milestone-templates` | `{name, game_name, items:[{item_name, quantity, is_group}]}` | Reuses the item-validation loop from `create_threshold_group` (`backend/app/routes/thresholds_routes.py:74`) — non-empty name, `quantity >= 1`. Returns **409** on unique-constraint hit. |
| `PUT /milestone-templates/<id>` | same as POST | Rename / edit items. Used for the overwrite path. **MVP** (not optional). |
| `DELETE /milestone-templates/<id>` | — | Ownership-checked. |

**No `apply` or `from-group` endpoint.** Both are client orchestration over data
already in hand:
- *Apply* = prefill the existing Create sheet → normal `createThresholdGroup`.
- *Save as template* = client already holds the group's name + items → plain `POST`.

**Export/import are also client-side** (see §6) — no dedicated backend endpoint;
import just calls `POST` per template.

---

## 4. Client — plumbing

**`network/ApiService.kt`** — new data classes + endpoints mirroring the threshold
group ones (`ApiService.kt:499`). Reuse `ThresholdGroupItem` /
`ThresholdGroupItemRequest` as-is (identical shape):

```kotlin
data class MilestoneTemplate(
    val id: Int,
    val name: String,
    val game_name: String,
    val items: List<ThresholdGroupItem>
)

data class CreateMilestoneTemplateRequest(
    val name: String,
    val game_name: String,
    val items: List<ThresholdGroupItemRequest>
)
```

**`ui/UserViewModel.kt`** — mirror the existing threshold group methods:
- `StateFlow<List<MilestoneTemplate>> milestoneTemplates`
- `fetchMilestoneTemplates(game: String? = null)`
- `createMilestoneTemplate(name, gameName, items)` → surfaces 409 for overwrite
- `updateMilestoneTemplate(id, name, gameName, items)`
- `deleteMilestoneTemplate(id)`

---

## 5. Client — UX

### 5a. Save a group as a template
- Action on `ThresholdGroupRow` (`ui/SlotDetailScreen.kt:990`) — icon/overflow.
- Prompts for a template name (default = the group's name).
- Calls `createMilestoneTemplate(slot.game, group.items)`.
- On **409**: "A template named *X* already exists for this game — overwrite it?"
  Confirm → resolve the id locally from the already-loaded template list →
  `updateMilestoneTemplate(...)`.

### 5b. Start a group from a template
- A **"Start from a template"** row at the top of `ThresholdGroupSheet`
  (create mode only), shown only when the user has templates for `slot.game`.
- Fetch the game's templates in the `LaunchedEffect` that already fires when the
  add sheet opens (`SlotDetailScreen.kt:540`), alongside `fetchAutocompleteData`.
- Tapping it opens a chooser (reuse the `SearchableSelectDialog` pattern) listing
  the user's templates for this game with item summaries. **Chooser only** — no
  inline management (delete/edit live on the dedicated screen, §5d).
- On pick → run the apply-time diff (§5c) → prefill `groupName` + `selectedItems`
  → user lands in the normal review/create flow and can edit before saving.

### 5c. Apply-time diff (reuses loaded `availableItems`)
`availableItems` is already the version-specific set for this slot. On pick:
- For each template item, case-insensitive membership check against
  `availableItems` (compare `name`; respect `isGroup` for group entries).
- **Matched** → prefilled into `selectedItems`.
- **Missing** → left out, with a light note ("2 items aren't in this version and
  were left out"). Kept low-friction because removals are rare.
- **Fallback:** if `availableItems` is empty (autocomplete didn't load /
  datapackage unavailable), skip the diff, prefill everything as-is, show a subtle
  "couldn't verify against this version" note. **Never block on validation.**

### 5d. Dedicated management screen
- New Compose screen `ui/MilestoneTemplatesScreen.kt` — lists the user's templates
  across all games, grouped by `game_name`, each with edit / delete / export.
- Reuses `ThresholdGroupSheet` (or a trimmed variant) for editing template items.
  Editing here has **no** version diff — there's no slot/checksum context on a
  cross-game screen — so it's plain authoring against full autocomplete. Fine.
- Navigation: new route + a "Milestone Templates" entry point in
  `ui/ProfileScreen.kt`.
- Hosts the **Import** action (§6) and per-template **Export** action.

---

## 6. Export / import (sharing)

Client-side serialization; no backend involvement. Import reuses `POST`.

### Portable format
A magic-prefixed, base64url-encoded JSON envelope so the format is
self-identifying and versioned, and pastes cleanly into Discord/text:

```
APMT1:<base64url(json)>
```

`APMT1` = *Archipelago Alerts Milestone Template, format v1*. Envelope:

```json
{
  "v": 1,
  "templates": [
    {
      "game": "Mega Man 2",
      "name": "Standard Start",
      "items": [
        { "item_name": "Items",        "quantity": 3, "is_group": true  },
        { "item_name": "Bubble Lead",  "quantity": 1, "is_group": false },
        { "item_name": "Crash Bomber", "quantity": 1, "is_group": false }
      ]
    }
  ]
}
```

- A single-template export is just a one-entry `templates` array; a bundle export
  is many. Import handles either.
- No `id` / `user_id` in the payload — portable and user-agnostic.

### Export
- Per-template (and optionally multi-select bundle) on the management screen.
- Serialize → hand the string to the Android system share sheet as plain text.

### Import
- "Import" on the management screen: paste the string into a field.
- Parse: strip the `APMT1:` prefix (accept raw JSON as a lenient fallback),
  base64url-decode, validate `v`, then validate each template
  (`game`/`name` non-empty, items well-formed, `quantity >= 1`).
- Create each via `POST`. Name collisions hit the same **409 → overwrite prompt**.
- **No datapackage validation at import** — the importer may not own a slot for
  that game yet. Validation happens later at apply time, exactly like any template.

### Cross-platform note
Because the format is defined on the client, document it here so an iOS client
(`backend/iOS_DEVELOPER_GUIDE.md`) can produce/consume identical strings.

---

## 7. Migration, tests, docs

- **Alembic**: new revision creating both tables. Apply with `alembic upgrade heads`.
- **Tests**: backend unit test for template CRUD + **ownership scoping**
  (user B cannot GET/PUT/DELETE user A's template) + 409-on-duplicate. Mirror
  `backend/tests/test_threshold_reconciliation.py`.
- **Changelog**: entries in `CHANGELOG.md` and `backend/app/data/changelog.json`
  (in-app What's New), per existing convention.

---

## 8. Phasing

1. **Backend** — models + migration + `templates_routes.py`
   (GET/POST/PUT/DELETE, ownership-scoped, 409 on dup) + CRUD/ownership test.
   Independently verifiable via curl before any Android work.
2. **Client plumbing** — `ApiService` + `UserViewModel`.
3. **Save-as-template** on `ThresholdGroupRow` (with overwrite prompt) — smallest
   loop, no diff.
4. **Start-from-template** picker + apply-time diff in the Create sheet.
5. **Dedicated management screen** + Profile entry point + nav route.
6. **Export / import** on the management screen.
7. **Batch Apply** — post-MVP bonus (see §9).

---

## 9. Batch Apply (post-MVP bonus)

An "Apply Templates" button in the Milestones header of `SlotDetailScreen.kt`,
shown only when the user has ≥1 templates for `slot.game`. Opens a multi-select
dialog; confirmed selections are created as milestone groups in one shot.

**Guardrails — required before shipping this phase:**

1. **Still run the per-template diff.** Each template's items are validated against
   `availableItems` (same case-insensitive membership check as single apply)
   before any groups are created. Don't skip validation because it's batched.

2. **Handle partial failure per template.** The backend rejects a group with zero
   valid items (400 "No valid items provided" —
   `backend/app/routes/thresholds_routes.py:91`). If all of a template's items are
   missing in this version, that create fails. The batch must let the remaining
   creates succeed and not abort as a whole.

3. **Post-apply summary instead of inline review.** Since batch apply bypasses the
   Create sheet review, surface a summary after completion: e.g. "Created 3
   groups. Skipped 'Bubble Lead' in 'Wily Ready' (not in this version)." Silent
   omissions in saved groups the user never reviewed is the main risk to avoid.

4. **Duplicate groups are allowed** (no unique constraint on group names), but
   show a soft nudge if the user already has a group that was likely created from
   the same template (same name + items). Don't block, just inform.

---

## 10. Open items / future
- Import via Android share-target intent (open a shared `.json`/text directly into
  the app) — MVP is paste-string import; intent handling is a later add.
- Bundle export UI (multi-select) can follow single-template export.
- Optional: seed/suggest templates by mining a user's own most-common Milestone
  Groups per game (dropped from scope as global templates, but still viable as a
  *personal* convenience).
