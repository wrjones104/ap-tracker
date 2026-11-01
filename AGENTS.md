# Agent Orientation Guide — Archipelago Alerts

This repository contains:
- **[LLM.md](LLM.md):** Complete codebase reference, data models, gotchas, and guidelines for AI agents.
- **[architecture.md](architecture.md):** Detailed system architecture, Mermaid diagrams, Redis Pub/Sub events, and containerization structure.
- **[CLAUDE.md](CLAUDE.md):** Quick command reference for Claude Code CLI and coding assistants.

**Before any server change:** a third-party iOS app uses this server, and we cannot update it. Raise any change that could affect it with the user before you write code. See the "Third-party iOS app" gotcha in [LLM.md](LLM.md).
