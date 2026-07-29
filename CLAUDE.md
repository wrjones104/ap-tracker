# Project Guide — Archipelago Alerts

Please refer to the primary project documentation files:
- **[LLM.md](LLM.md):** Project overview, directory structure, gotchas, and guidelines.
- **[architecture.md](architecture.md):** Detailed system architecture, Mermaid diagrams, Redis Pub/Sub events, database composite indexes, and Docker topology.

## Key Development Commands

### Backend Execution & Testing
```bash
# Run unit test suite
python -m unittest backend/tests/test_cheese_sync.py

# Run local development server
python backend/run.py

# Run local dev containers (PostgreSQL 15 + Redis 7)
docker-compose -f docker-compose.dev.yml up -d
```

### Database Migrations (Alembic)
```bash
alembic upgrade heads
```
