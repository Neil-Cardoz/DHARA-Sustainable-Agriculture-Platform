# Build context is the repo root: docker build -f services/ingestion/Dockerfile -t dhara-ingestion .
#
# Runs as a long-lived Container App consuming IoT Hub's built-in Event Hub
# endpoint directly via the azure-eventhub SDK -- see consumer.py for why
# this replaced the Azure Functions Event Hub trigger.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY packages/dhara_shared /app/packages/dhara_shared
COPY services/ingestion/requirements.txt /app/services/ingestion/requirements.txt

RUN pip install --no-cache-dir -e /app/packages/dhara_shared \
    && pip install --no-cache-dir -r /app/services/ingestion/requirements.txt

COPY services/ingestion/consumer.py /app/services/ingestion/consumer.py

WORKDIR /app/services/ingestion
CMD ["python", "consumer.py"]
