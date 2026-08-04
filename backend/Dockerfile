FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for PostgreSQL client libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source. This includes app/data/changelog.json, the
# hand-authored single source of truth for release notes and versions served by
# /api/whats_new and the landing page (no build-time generation step).
COPY backend/ /app/

# Copy Alembic database migrations and configuration
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

# Run as non-root user for security
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "run.py"]
