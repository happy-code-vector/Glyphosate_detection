# ResidueIQ API — Cloud Run container.
# The DB is NOT baked in (~645 MB, refreshed independently each night); the
# entrypoint pulls it from GCS at startup. See api/entrypoint.sh + api/fetch_db.py.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps first → layer cache survives code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p data && chmod +x api/entrypoint.sh

# Cloud Run injects PORT=8080. Health is the unauthenticated /api/health.
EXPOSE 8080
ENTRYPOINT ["./api/entrypoint.sh"]
