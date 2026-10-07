# Build context is the repo root: docker build -f services/api/Dockerfile -t dhara-api .
FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY packages/dhara_shared /app/packages/dhara_shared
COPY services/api/requirements.txt /app/services/api/requirements.txt

RUN pip install --no-cache-dir -e /app/packages/dhara_shared \
    && pip install --no-cache-dir -r /app/services/api/requirements.txt

COPY services/api/app /app/services/api/app

WORKDIR /app/services/api
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -f http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
