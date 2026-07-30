# Production & UAT Deployment Guide — Archipelago Alerts

This guide documents the step-by-step deployment procedure and key **"gotchas"** learned during the architecture overhaul and Docker containerization of **Archipelago Alerts**. Use this reference when deploying to Production or new GCP VM environments.

---

## Architecture Summary
* **API Server (`api`):** Flask / Waitress WSGI application listening on port `5000`.
* **Background Worker (`poller`):** Event-driven room polling service running Redis Pub/Sub listener and exponential setup backoff.
* **Cache & Event Queue (`redis`):** Containerized Redis 7 listening on port `6379`.
* **Database (`postgres`):** Host-level native PostgreSQL (port `5432`) or containerized PostgreSQL (port `5433`).
* **Reverse Proxy (`nginx`):** Host-level Nginx listening on ports `80`/`443` with SSL termination, forwarding traffic to `http://127.0.0.1:5000`.

---

## Production Deployment Checklist

### Step 1: Clone / Pull Repository
```bash
cd /var/www/ap-tracker
git fetch origin
git checkout main # or feature branch
git pull origin main
```

---

### Step 2: Configure Host PostgreSQL Permissions (Crucial for `host.docker.internal`)

If connecting Docker containers to your existing native PostgreSQL database on port `5432`:

#### 1. Update `postgresql.conf`
Edit your PostgreSQL config (e.g. `/etc/postgresql/15/main/postgresql.conf`):
```ini
# Change listen_addresses from 'localhost' to '*'
listen_addresses = '*'
```

#### 2. Update `pg_hba.conf`
Edit your authentication config (e.g. `/etc/postgresql/15/main/pg_hba.conf`) and append:
```ini
# Allow connections from Docker network subnet
host    all             all             172.16.0.0/12           md5
host    all             all             172.16.0.0/12           scram-sha-256
```

#### 3. Restart PostgreSQL
```bash
sudo systemctl restart postgresql
```

---

### Step 3: Populate `backend/.env` Secrets

Ensure `backend/.env` contains all required credentials:
```ini
# Database Connection String (Host PostgreSQL)
DATABASE_URL=postgresql://ap_user:ap_password@host.docker.internal:5432/ap_tracker_prod

# Redis Connection String (Containerized Redis)
REDIS_URL=redis://redis:6379/0

# Flask Environment
FLASK_ENV=production

# Mandatory Encryption & Auth Secrets
SECRET_KEY=<your-production-secret-key>
ENCRYPTION_KEY=<your-production-encryption-key>

# Discord OAuth Application Credentials
DISCORD_CLIENT_ID=<your-production-discord-client-id>
DISCORD_CLIENT_SECRET=<your-production-discord-client-secret>

# Cheese Tracker Base URL (Optional override)
CHEESE_BASE_URL=https://cheesetrackers.theincrediblewheelofchee.se/api
```

---

### Step 4: Stop Native Systemd Services
Prevent port collisions on host ports `5000` and `6379`:
```bash
sudo systemctl stop ap-tracker-api || true
sudo systemctl stop ap-tracker-poller || true
sudo systemctl disable ap-tracker-api || true
sudo systemctl disable ap-tracker-poller || true
```

---

### Step 5: Launch Containers & Apply Database Migrations
```bash
# 1. Build and start containers
docker compose up -d --build

# 2. Run Alembic database migrations
docker compose exec api alembic upgrade head

# 3. Verify single migration head
docker compose exec api alembic current
# Expected Output: 960bbde6606b (head) (mergepoint)

# 4. Verify database engine connection
docker compose exec api python -c "from app import engine; print(engine.connect())"
```

---

### Step 6: Configure Host Nginx Reverse Proxy
Ensure `/etc/nginx/sites-available/ap-tracker` points to `http://127.0.0.1:5000`:
```nginx
server {
    server_name archipelagoalerts.com www.archipelagoalerts.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Reload Nginx:
```bash
sudo nginx -t
sudo systemctl reload nginx
```

---

## Known Gotchas & Trouble-Shooting Reference

| Symptom / Error | Root Cause | Solution |
| :--- | :--- | :--- |
| **`502 Bad Gateway` from Nginx** | Nginx `proxy_pass` points to an old unix socket or stopped service. | Set `proxy_pass http://127.0.0.1:5000;` in Nginx site config and run `sudo systemctl reload nginx`. |
| **`Connection refused` on `host.docker.internal:5432`** | Native PostgreSQL on Linux listens only on `127.0.0.1`. | Set `listen_addresses = '*'` in `postgresql.conf`, add `172.16.0.0/12` to `pg_hba.conf`, and `sudo systemctl restart postgresql`. |
| **`400 BAD REQUEST` on Discord Login** | Missing or blank `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET` in `backend/.env`. | Fill in Discord OAuth app credentials in `backend/.env` and restart containers (`docker compose up -d`). |
| **`alembic upgrade head` Multiple Heads Error** | Parallel migrations on separate branches (e.g. filler traps vs iOS platform). | Merge revision `960bbde6606b_merge_filler_trap_and_ios_platform_heads.py` unifies them. Always run `alembic upgrade head` (singular). |
| **`No space left on device` during Docker build** | Large `venv/` or `.git/` being sent in Docker context payload (145MB+). | Root `.dockerignore` ignores `venv/`, `.git/`, shrinking payload to < 50KB. Also run `docker system prune -af`. |
| **Debian 12 Apt 404 for Docker Repo** | Apt sources pointing to `ubuntu` repo URL on a Debian VM. | Set Docker Apt source URL to `https://download.docker.com/linux/debian` using `$VERSION_CODENAME`. |
| **Docker Compose Overriding `.env` DB URL** | Hardcoded default expression in `docker-compose.yml`. | Keep `env_file: - backend/.env` without hardcoded `${DATABASE_URL:-...}` fallbacks. |

---

## Live Monitoring Commands

* **Live Poller Logs:** `docker compose logs -f poller`
* **Live API Logs:** `docker compose logs -f api`
* **All Service Logs:** `docker compose logs -f`
* **Container Health:** `docker compose ps`
