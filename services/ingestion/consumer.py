"""Tier 3 ingestion worker -- direct Event Hub SDK consumer.

Replaces an Azure Functions Event Hub trigger, which proved unreliable in
this deployment: across two Consumption-plan recreations and two Flex
Consumption configurations (default and a dedicated consumer group, with and
without an always-ready instance), the trigger never once fired despite IoT
Hub's own metrics confirming messages arriving continuously. See
docs/SETUP.md for the full diagnostic trail. This plain polling consumer,
run as a long-lived Container App, uses the exact same decode/forward logic
but needs no Functions-specific scaling machinery to work.

Connects to IoT Hub's *built-in* Event Hub-compatible endpoint (Portal:
IoT Hub -> Built-in endpoints -> Event Hubs compatible endpoint), reading
from a dedicated consumer group so it never contends with anything else.
"""
import json
import logging
import os
from datetime import datetime, timezone

import httpx
from azure.eventhub import EventHubConsumerClient
from dhara_shared.frame_codec import decode_uplink

logging.basicConfig(level="INFO")
logging.getLogger("azure.eventhub._pyamqp").setLevel(logging.WARNING)
logging.getLogger("uamqp").setLevel(logging.WARNING)

EVENTHUB_CONNECTION_STRING = os.environ["IOT_HUB_EVENTHUB_COMPATIBLE_ENDPOINT"]
CONSUMER_GROUP = os.environ.get("IOT_HUB_EVENTHUB_CONSUMER_GROUP", "$Default")
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")

_device_id_cache: dict[str, str] = {}
_client = httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=15)


def _resolve_device_uuid(hardware_id: str) -> str | None:
    if hardware_id in _device_id_cache:
        return _device_id_cache[hardware_id]
    resp = _client.get(f"/devices/by-hardware-id/{hardware_id}")
    if resp.status_code != 200:
        logging.warning("unknown device hardware_id=%s (%s)", hardware_id, resp.status_code)
        return None
    device_uuid = resp.json()["id"]
    _device_id_cache[hardware_id] = device_uuid
    return device_uuid


def _extract_device_id(event) -> str | None:
    sys_props = event.system_properties or {}
    for key in (b"iothub-connection-device-id", "iothub-connection-device-id"):
        if key in sys_props:
            val = sys_props[key]
            return val.decode() if isinstance(val, bytes) else val
    return None


def on_event_batch(partition_context, events):
    logging.info("batch callback fired: partition=%s, event_count=%d", partition_context.partition_id, len(events))
    readings_batch: list[dict] = []
    heartbeats: dict[str, dict] = {}

    for event in events:
        hardware_id = _extract_device_id(event)
        if not hardware_id:
            logging.warning("event missing iothub-connection-device-id, skipping")
            continue

        device_uuid = _resolve_device_uuid(hardware_id)
        if not device_uuid:
            continue

        body = b"".join(event.body)
        ts = datetime.now(timezone.utc)

        try:
            if len(body) == 16:
                frame = decode_uplink(body)
                readings_batch.extend(
                    [
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "moisture_15cm", "value": frame.moisture_15cm_pct},
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "moisture_30cm", "value": frame.moisture_30cm_pct},
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "moisture_60cm", "value": frame.moisture_60cm_pct},
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "soil_temp_c", "value": frame.soil_temp_c},
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "flow_l_cumulative", "value": frame.flow_litres_cumulative},
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": "battery_mv", "value": frame.battery_mv},
                    ]
                )
                health = "fault" if (frame.valve_fault or frame.stuck_valve) else (
                    "degraded" if frame.low_battery else "healthy"
                )
                heartbeats[hardware_id] = {
                    "device_id": device_uuid,
                    "battery_mv": frame.battery_mv,
                    "health_state": health,
                }
            else:
                payload = json.loads(body)
                for metric, value in payload.get("metrics", {}).items():
                    readings_batch.append(
                        {"device_id": device_uuid, "ts": ts.isoformat(), "metric": metric, "value": value}
                    )
                if "battery_mv" in payload:
                    heartbeats[hardware_id] = {
                        "device_id": device_uuid,
                        "battery_mv": payload["battery_mv"],
                        "health_state": payload.get("health_state", "healthy"),
                    }
        except Exception:
            logging.exception("failed to decode telemetry from device %s", hardware_id)

    if readings_batch:
        resp = _client.post("/telemetry/ingest", json=readings_batch)
        resp.raise_for_status()
        logging.info("ingested %d readings from %d events", len(readings_batch), len(events))

    for hardware_id, hb in heartbeats.items():
        _client.patch(
            f"/devices/{hb['device_id']}/heartbeat",
            params={"battery_mv": hb["battery_mv"], "health_state": hb["health_state"]},
        )


def on_error(partition_context, error):
    ctx = f"partition {partition_context.partition_id}" if partition_context else "client"
    logging.error("error on %s: %s", ctx, error)


def on_partition_initialize(partition_context):
    logging.info("partition %s initialized, consumer group=%s", partition_context.partition_id, CONSUMER_GROUP)


def main():
    client = EventHubConsumerClient.from_connection_string(
        EVENTHUB_CONNECTION_STRING, consumer_group=CONSUMER_GROUP
    )
    logging.info("starting Event Hub consumer, consumer_group=%s, api=%s", CONSUMER_GROUP, API_BASE_URL)
    with client:
        client.receive_batch(
            on_event_batch=on_event_batch,
            on_error=on_error,
            on_partition_initialize=on_partition_initialize,
            starting_position="@latest",
            max_batch_size=256,
            max_wait_time=15,
        )


if __name__ == "__main__":
    main()
