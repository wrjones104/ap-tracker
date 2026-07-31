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

# Copy backend application source
COPY backend/ /app/

# Copy Alembic database migrations, configuration, and VERSION files
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini
COPY VERSION /app/VERSION
COPY backend/VERSION /app/backend/VERSION

# Generate changelog.json from CHANGELOG files at build time
COPY CHANGELOG.md /app/CHANGELOG.md
COPY android/CHANGELOG.md /app/android/CHANGELOG.md
COPY backend/CHANGELOG.md /app/backend/CHANGELOG.md
COPY scripts/sync_changelog.py /app/scripts/sync_changelog.py
RUN python /app/scripts/sync_changelog.py && rm -rf /app/CHANGELOG.md /app/android/CHANGELOG.md /app/backend/CHANGELOG.md /app/scripts/sync_changelog.py

# Run as non-root user for security
RUN adduser --disabled-password --gecos '' appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "run.py"]
