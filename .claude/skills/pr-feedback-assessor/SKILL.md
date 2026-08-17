---
name: pr-feedback-assessor
description: Analyzes code review comments and PR review reports provided by users or reviewers, assesses the technical validity and severity of each finding, verifies against codebase reality, implements surgical fixes, runs test/build verifications, and pushes resolved commits. Use when receiving PR review comments, code audit reports, or reviewer feedback.
---

# PR Feedback Assessor Skill

This skill provides an end-to-end workflow for analyzing incoming Pull Request reviews, assessing the technical validity of each comment, implementing surgical fixes, verifying tests and builds, and pushing clean resolution commits.

> **Universal Compatibility**: Structured to work in both **Google Antigravity** (`.agents/skills/`) and **Claude Code** (`.claude/skills/`).

---

## 1. Assessment & Execution Workflow

```
[1. Parse Feedback] ➔ [2. Assess Validity] ➔ [3. Implement Fixes] ➔ [4. Verify & Test] ➔ [5. Commit & Push]
```

### Step 1: Parse Review Feedback
When the user invokes `/pr-feedback-assessor` followed by review text:
1. Break down the feedback into individual findings/comments.
2. Extract the severity level (`Must Change / Blockers`, `Could Change / Optional`, `Questions / Notes`).
3. Identify the referenced source file(s) and line number(s).

### Step 2: Technical Validity Assessment
For every finding, evaluate against the codebase:
- **Inspect Current State**: Read the actual code referenced using `view_file` or `grep_search`.
- **Determine Validity**:
  - **`VALID (Blocker)`**: Direct bug, logical inconsistency, or regression that violates the PR's stated goals.
  - **`VALID (Improvement)`**: Good design practice, performance boost, or safety guard that improves code health without breaking behavior.
  - **`INVALID / INTENTIONAL`**: Reviewer misunderstood architecture, or the divergence is an intentional, documented tradeoff (e.g. standalone background widget constraint vs in-app live state).
- **Formulate Rationale**: Document the exact technical reason why each item is valid or invalid.

### Step 3: Implement Surgical Fixes
For all valid findings:
1. Make targeted, minimal edits using `replace_file_content` (avoid wholesale rewrites).
2. If an item is an intentional divergence, add a clear code comment explaining the architectural reason.
3. Preserve existing coding conventions and strict types.

### Step 4: Verification & Automated Testing
Execute relevant build and test suites to verify zero regressions:
1. **Backend**:
   ```bash
   $env:PYTHONPATH="backend"; .\venv\Scripts\python -m unittest discover backend/tests
   ```
2. **Android**:
   ```powershell
   $env:JAVA_HOME = 'C:\Program Files\Android\Android Studio\jbr'; ./gradlew.bat :app:assembleDevDebug
   ```
3. **Changelog Alignment** (if versions were modified):
   ```bash
   .\venv\Scripts\python scripts/generate_changelog.py --check
   ```

### Step 5: Commit, Push & Report
1. Check `git status` to ensure only task-relevant files are staged.
2. Commit with conventional message (e.g. `fix(component): address PR review feedback on X, Y, and Z`).
3. Push to the active feature branch.
4. Present a clear assessment report summarizing:
   - Validity determination for each reviewer comment.
   - Code adjustments made.
   - Test and build verification results.
