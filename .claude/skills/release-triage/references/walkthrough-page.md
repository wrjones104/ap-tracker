# The walkthrough page

The Artifact the triage produces. It is read while merging, so every choice
should serve "what do I do next" rather than "what happened".

Load the `artifact-design` skill before writing it. This file covers what goes on
the page and why; that skill covers how to make it look considered.

## Treatment

Utilitarian, not editorial. This is a working document: real typographic
hierarchy, considered spacing, a proper palette, no oversized hero. It is also
partly a UI — it gets scanned, not read top to bottom — so the summary comes
before the detail and state is visible at a glance.

Keep the design stable across updates. The user returns to the same URL through a
release; a page that looks different every time is harder to navigate, not
fresher. Republishing the same file path keeps the URL.

## Sections

Roughly this order. Drop any that would be empty rather than padding them.

**Masthead** — the release name as the page title. A standfirst that says in two
sentences where the release actually stands. Then a small row of vitals: current
version, next version, count of open PRs, count of open issues. Numbers the user
would otherwise go and look up.

**Already merged, unreleased** — what is sitting on `main` waiting. Often thinner
than expected, and that is exactly the fact that justifies bundling more in.

**What was done** *(status updates only)* — one row per PR with its state. Include
what review changed on each, because a reader coming back later wants to know
which parts got a second look.

**Ship / pull forward** — the triage itself. One row per item: the issue number,
what it is, and one line on why it earned its place. For a scoped-down item, say
what was left out.

**The release gate** — whatever manual check the release must not skip, given
prominence. If the repo has a history that justifies it, show that history
concretely: three dated occurrences of the same fault argue better than a
sentence saying it is risky.

**Merge order** — a numbered sequence. This is one of the few places where
numbering is honest, because the order genuinely carries information. Give the
reason beside each step, especially any dependency or file overlap.

**What still needs doing** — a checklist, one item per action, phrased as the
thing to do rather than the thing that is missing. Every item here should be work
only the user can do: a decision, a real device, infrastructure the test suite
lacks. Include the gaps named in each PR, so nothing that was flagged as
unverified quietly disappears.

**Waiting, and why** — deferrals with their reasons. Nothing is "dismissed"; each
is held for something that could change.

**Arrived after triage** — anything filed since the plan was set, marked
untriaged. Do not silently fold new issues into the existing buckets; surface
them as needing a call.

**Footnote** — one or two things worth carrying into review. Honest limitations
belong here, including patterns in your own work that should affect how much the
user delegates.

## Structure carries meaning

Use structural devices only where they encode something true.

- **Tiers** (ship / pull forward / defer) are the right spine, because the tier
  *is* the decision.
- **Numbering** belongs in the merge order and nowhere else. A numbered list of
  unordered items reads as sequence where there is none.
- **Checkboxes** belong on work the user does by hand, and nowhere else. They
  imply "you, now" — using them for merged work makes the page lie.
- **State chips** (merged / in review / untriaged) let the reader find the live
  rows without reading every line.

## Writing the rows

One line of why per item, in the user's terms rather than the code's. "A room
with only watched slots disappears on the next sync" beats "the prune query does
not exclude subscriptions with tracked slots".

Name the cost of a deferral where there is one. Name the trade-off where a scope
decision could reasonably have gone the other way — the user should be able to
disagree with a specific sentence rather than with the whole plan.
