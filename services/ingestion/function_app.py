"""Tier 3 ingestion worker.

Consumes the built-in Event Hub-compatible endpoint of Azure IoT Hub -- every
farm edge box's uplink lands here first. Each message body is the 16-byte
packed binary frame described in the architecture ("sixteen bytes on the
radio, seven entities in the store"); this function decodes it, resolves the
IoT Hub deviceId to our internal Device row, and writes Reading rows through
the core API (kept as the single writer of the Postgres store).

Connection is configured via the `IotHubEventHubConnection` app setting,
which must be the IoT Hub's *built-in* Event Hub-compatible endpoint
connection string (Portal: IoT Hub -> Built-in endpoints -> Event Hubs
compatible endpoint), not the general service connection string.
"""
import json
import logging
import os
import typing
from datetime import datetime, timezone

import azure.functions as func
import httpx
from dhara_shared.frame_codec import decode_uplink

app = func.FunctionApp()

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")

_device_id_cache: dict[str, str] = {}


def _resolve_device_uuid(client: httpx.Client, hardware_id: str) -> str | None:
    if hardware_id in _device_id_cache:
        return _device_id_cache[hardware_id]
    resp = client.get(f"{API_BASE_URL}/devices/by-hardware-id/{hardware_id}")
    if resp.status_code != 200:
        logging.warning("unknown device hardware_id=%s (%s)", hardware_id, resp.status_code)
        return None
    device_uuid = resp.json()["id"]
    _device_id_cache[hardware_id] = device_uuid
    return device_uuid


@app.function_name(name="OnIotTelemetry")
@app.event_hub_message_trigger(
    arg_name="events",
    event_hub_name="%IOT_HUB_EVENTHUB_NAME%",
    connection="IotHubEventHubConnection",
    consumer_group="%IOT_HUB_CONSUMER_GROUP%",
    cardinality="many",
)
def on_iot_telemetry(events: typing.List[func.EventHubEvent]) -> None:
    readings_batch: list[dict] = []
    heartbeats: dict[str, dict] = {}

    with httpx.Client(headers={"X-API-Key": API_KEY}, timeout=10) as client:
        for event in events:
            props = event.iothub_metadata or {}
            hardware_id = props.get("connection-device-id") or props.get("iothub-connection-device-id")
            if not hardware_id:
                logging.warning("event missing device id metadata, skipping")
                continue

            device_uuid = _resolve_device_uuid(client, hardware_id)
            if not device_uuid:
                continue

            body = event.get_body()
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
                    # JSON telemetry path (gateway/energy meter/pump box status; not the 16-byte soil frame).
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
            resp = client.post(f"{API_BASE_URL}/telemetry/ingest", json=readings_batch)
            resp.raise_for_status()
            logging.info("ingested %d readings", len(readings_batch))

        for hardware_id, hb in heartbeats.items():
            client.patch(
                f"{API_BASE_URL}/devices/{hb['device_id']}/heartbeat",
                params={"battery_mv": hb["battery_mv"], "health_state": hb["health_state"]},
            )
