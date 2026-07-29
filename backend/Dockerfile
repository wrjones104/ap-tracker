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

# Copy Alembic database migrations and configuration
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini

ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "run.py"]
