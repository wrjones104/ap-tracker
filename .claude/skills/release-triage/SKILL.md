---
name: release-triage
description: Triage the repo's open GitHub issues into a named release — decide what ships, what waits and why, derive a merge order from real branch overlap, and publish a walkthrough page with checklists and next steps. Use whenever planning or cutting a release, asking "what should go in the next version", reviewing the issue backlog against a release, working out what order to merge a stack of open PRs, or asking for a status page on work in flight. Also use when someone wants an issue inventory, a backlog triage, or a plan for getting a set of fixes out the door.
---

# Release Triage

Turns an open-issue backlog into a decided release: a short list that ships, a
shorter list that waits with a stated reason, a merge order derived from the
branches themselves, and a page the user can work through.

The output is a decision, not a survey. A list of everything open is not triage.

## What this produces

1. A triage of every open issue into **ship**, **pull forward**, or **defer**.
2. A **merge order** for whatever PRs are open, derived from file overlap.
3. A published **Artifact walkthrough page** with checklists for the work only a
   human can do.
4. An updated memory of the release plan, so the next session starts current.

## Step 1 — Inventory

```bash
gh issue list --repo <owner>/<repo> --state open --limit 100 \
  --json number,title,labels,createdAt --template '{{range .}}#{{.number}} [{{range .labels}}{{.name}} {{end}}] {{.title}}{{"\n"}}{{end}}'
```

Then read the bodies. Do not triage from titles: the body carries the mechanism,
the impact, and often an explicit instruction about sequencing ("read the
telemetry before touching this").

**Issues with an empty body are common and are not a reason to skip them.**
Derive the scope from the code instead — find the feature, find the gate, work
out what the title is describing. Say in your triage that you did this, so the
user can correct a wrong reading early.

Also establish what is already merged but unreleased. That is the release's
existing content, and it is often thinner than expected:

```bash
git log --oneline <last-release-commit>..main --no-merges
```

## Step 2 — Triage

Sort every issue into one of three buckets. Lead with a recommendation; do not
present an even-handed menu.

**Ship** — already done, or small, contained, and low-risk. Fixes for bugs users
are hitting now belong here even if they were not on the original plan.

**Pull forward** — worth adding, with the scope named. Large issues can often be
split: take the part that closes the common case, leave the part that needs new
schema or new infrastructure. When you ship half an issue, reference it with
`Refs #N` rather than `Fixes #N` and say in the PR what was deliberately left.

**Defer** — with a reason that would change if the reason changed. "Not now" is
not a reason. "The issue says to read the telemetry first, and that telemetry
only started accumulating when the last version shipped" is. Deadlines months
away are a legitimate reason; so is a change that needs infrastructure the repo
does not have yet.

Two failure modes worth guarding against:

- **Bundling large work into a verified release.** If the release is code-complete
  and a proposed addition is a multi-week project, say so plainly and name what
  the delay costs — especially when something already fixed is live data loss.
  Then let the user decide.
- **Deferring a cheap fix because it was not on the list.** A one-line fix for an
  active bug is worth more than plan tidiness.

For anything user-facing, check the release contains at least one thing users
will actually notice. A release of pure invisible fixes is hard to write notes for.

## Step 3 — Merge order from real overlap

`gh pr list` reporting `CLEAN` means each PR is clean **against `main`
independently** — not against each other. Two branches that both touch a file
will still both say CLEAN, and the second to merge will need a rebase.

Find the real overlap:

```bash
for b in <branch> <branch> ...; do
  echo "--- $b"
  git diff --name-only origin/main...origin/$b
done
```

Then order by two rules:

- **Dependency first.** If branch A's new code calls something branch B fixes,
  merge B first. Otherwise A ships behaving differently from how its own tests
  and comments describe.
- **Isolated before overlapping.** Land the branches that share no files, so the
  only rebase risk is concentrated at the end and is known in advance.

State the overlap explicitly in the plan — "these two both modify `X.kt`, whichever
lands second needs `main` pulled in" — because it is invisible from the PR list.

## Step 4 — The walkthrough page

Publish an Artifact. Load `artifact-design` first, then build the page from
`references/walkthrough-page.md`, which describes the section layout and the
structural choices that make it scannable.

The page is a working document, not a report. It is read while merging, so it
should answer "what do I do next" at a glance.

## Step 5 — Keep it current

Record the outcome in memory so the next session does not re-derive it. Update
the existing release-plan memory rather than adding a second one; a stale plan
that says work is pending when it shipped is worse than no plan.

When the user reports progress, republish the same file path — it keeps the same
URL, so the link they saved still works.

## Working discipline

The recurring failure in this workflow is asserting rather than verifying. Some
specific traps, each of which has actually happened here:

- **Never pipe an exhaustiveness check through `head`.** A `grep` for remaining
  references that gets truncated will look clean and be wrong. If the answer is
  "there are none left", show all of it.
- **Prove a new test can fail.** Write it, watch it fail against the unfixed
  code, then fix. A regression test that never failed pins nothing. For a
  behavioural change, mutate the fix back and confirm the test catches it.
- **Run the UI for UI changes.** Compose is not unit-testable here. Install on an
  emulator (`adb -s emulator-5554 install -r <apk>`) and walk the flow. Defects
  that are invisible in a diff — stale copy contradicting a new feature, a screen
  that never names what it is operating on — show up immediately on screen.
- **Do not write to the user's real account to verify.** Stop before the call that
  creates data and say which path is therefore unexercised.
- **Say what you did not test.** Every PR here should name the gap: the retry path
  that needs a slow endpoint, the container start that needs the real stack. An
  unstated gap reads as covered.

When something outside the current task turns out to be a real, traced problem,
file it as an issue rather than widening the change — `CLAUDE.md` grants standing
approval and describes the shape of a good one. Then finish the task you were on.

## Repo mechanics

- `main` is a staging area. Merging does not deploy; getting code to users is a
  separate manual step, and the Alembic migration runs on server boot.
- The version bump and changelog are a single `chore(release):` commit made once,
  immediately before the deploy — not per merge.
- Use the `version-manager` and `release-notes` skills for that step rather than
  editing `changelog.json` by hand.
- The Android release build is the risk. R8 has silently stripped
  reflectively-called constructors more than once, with a green build and green
  CI each time. A manual pass on a **minified** build belongs in every release
  checklist until #296 automates it.
