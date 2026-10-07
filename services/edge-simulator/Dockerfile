# Build context is the repo root: docker build -f services/edge-simulator/Dockerfile -t dhara-edge-simulator .
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY packages/dhara_shared /app/packages/dhara_shared
COPY services/edge-simulator/requirements.txt /app/services/edge-simulator/requirements.txt

RUN pip install --no-cache-dir -e /app/packages/dhara_shared \
    && pip install --no-cache-dir -r /app/services/edge-simulator/requirements.txt

COPY services/edge-simulator/*.py /app/services/edge-simulator/

WORKDIR /app/services/edge-simulator
CMD ["python", "simulator.py"]
