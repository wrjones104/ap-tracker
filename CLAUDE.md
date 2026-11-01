# Project Guide — Archipelago Alerts

Please refer to the primary project documentation files:
- **[LLM.md](LLM.md):** Project overview, directory structure, gotchas, and guidelines.
- **[architecture.md](architecture.md):** Detailed system architecture, Mermaid diagrams, Redis Pub/Sub events, database composite indexes, and Docker topology.

## iOS App Impact

An independent developer's native iOS app uses this server, and we cannot update it. Before you write code for any server change that could affect it, tell the user what changes and what iOS users would notice, and wait for their decision. Prefer changes that leave the iOS app alone. When a breaking change is necessary, the user gives its developer notice first. What counts, and the full rule: the "Third-party iOS app" gotcha in [LLM.md](LLM.md).

## Out-of-Scope Findings

If you find a real problem that is outside the scope of the work you were asked to do, file it as a GitHub issue on `wrjones104/ap-tracker` rather than fixing it inline or only mentioning it in chat. Standing approval is granted for this — no need to ask first.

```bash
gh issue create --repo wrjones104/ap-tracker --title "<title>" --label bug --body-file <path>
```

Guidelines:
- **File it, don't fix it.** Filing the issue is instead of widening the current change, not a preface to it. Finish the task you were given.
- **Only real, verified problems.** A bug you have traced, a latent trap, dead code you have confirmed is dead. Not hunches, style preferences, or "this could be refactored."
- **Make it self-contained.** Include the mechanism, `file.py:line` references, actual impact (including "no live bugs, but here is the trap"), and a suggested fix. Someone should be able to act on it without reading the conversation it came from.
- **Check for duplicates first** with `gh issue list --search`.
- Use the `bug` label for defects, `enhancement` for gaps. Reference the originating work if there is a related PR or issue.

See [#256](https://github.com/wrjones104/ap-tracker/issues/256) for the shape of a good one.

## Key Development Commands

### Backend Execution & Testing
```bash
# Run unit test suite
$env:PYTHONPATH="backend;." ; python -m unittest backend/tests/test_cheese_sync.py

# Run local development server
python backend/run.py

# Run local dev containers (PostgreSQL 15 + Redis 7)
docker-compose -f docker-compose.dev.yml up -d
```

### Database Migrations (Alembic)
```bash
alembic upgrade heads
```
