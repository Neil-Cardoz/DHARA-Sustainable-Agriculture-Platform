# Build context is the repo root: docker build -f services/advisory-bot/Dockerfile -t dhara-advisory-bot .
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential libssl-dev libasound2 curl \
    && rm -rf /var/lib/apt/lists/*

COPY packages/dhara_shared /app/packages/dhara_shared
COPY services/advisory-bot/requirements.txt /app/services/advisory-bot/requirements.txt

RUN pip install --no-cache-dir -e /app/packages/dhara_shared \
    && pip install --no-cache-dir -r /app/services/advisory-bot/requirements.txt

COPY services/advisory-bot/app /app/services/advisory-bot/app

WORKDIR /app/services/advisory-bot
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -f http://localhost:8100/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
