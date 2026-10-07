"""Runs N virtual Tier-1 farm edge boxes against real Azure IoT Hub.

Each simulated box:
  - depletes root-zone moisture over time using a simple ETc draw-down,
  - listens for the cloud's C2D "irrigate" command and replenishes moisture
    + increments its cumulative flow counter accordingly (so the decision
    engine's verify step has something real to reconcile against),
  - packs everything into the same 16-byte uplink frame a real ESP32 edge
    box would send, and publishes it over MQTT via the IoT device SDK.

This stands in for Tiers 0-2 (field sensors, farm edge box, village cluster
gateway) so the full Tier-3 cloud loop can be demonstrated end-to-end without
physical hardware.
"""
import asyncio
import json
import logging
import math
import os
import random
import time
from dataclasses import dataclass, field

from azure.iot.device.aio import IoTHubDeviceClient
from azure.iot.device import Message
from dhara_shared.frame_codec import encode_uplink

logging.basicConfig(level="INFO")

TICK_SECONDS = int(os.environ.get("SIMULATOR_TICK_SECONDS", "60"))  # one tick = one simulated 15-minute cycle
SIMULATED_MINUTES_PER_TICK = 15.0
DEVICES_FILE = os.path.join(os.path.dirname(__file__), "devices.json")


@dataclass
class FarmState:
    hardware_id: str
    field_capacity_pct: float
    wilting_point_pct: float
    area_ha: float
    moisture_15: float = field(init=False)
    moisture_30: float = field(init=False)
    moisture_60: float = field(init=False)
    soil_temp_c: float = 24.0
    battery_mv: int = 4050
    flow_cumulative_l: int = 0
    sequence: int = 0
    pending_irrigation_m3: float = 0.0

    def __post_init__(self):
        start = self.field_capacity_pct - random.uniform(2, 8)
        self.moisture_15 = start
        self.moisture_30 = start
        self.moisture_60 = start + 1.5


def _daylight_factor(hour: float) -> float:
    if 6 <= hour <= 18:
        return max(0.0, math.sin(math.pi * (hour - 6) / 12))
    return 0.0


async def run_device(conn_str: str, state: FarmState) -> None:
    client = IoTHubDeviceClient.create_from_connection_string(conn_str)
    await client.connect()

    def on_c2d(message: Message):
        try:
            payload = json.loads(message.data)
            if payload.get("command") == "irrigate":
                state.pending_irrigation_m3 += float(payload.get("volume_m3", 0.0))
        except Exception:
            logging.exception("bad C2D payload on %s", state.hardware_id)

    client.on_message_received = on_c2d
    logging.info("device %s connected", state.hardware_id)

    try:
        while True:
            hour = time.localtime().tm_hour + time.localtime().tm_min / 60
            daylight = _daylight_factor(hour)

            # ET draw-down: ~4-6mm/day reference crop, spread across daylight ticks.
            et_mm_per_tick = (5.0 / (12 * 60 / SIMULATED_MINUTES_PER_TICK)) * (0.3 + daylight)
            depletion_pct = et_mm_per_tick / 4.0  # crude mm -> volumetric % conversion for a 400mm root zone
            state.moisture_15 = max(state.wilting_point_pct, state.moisture_15 - depletion_pct * 1.3)
            state.moisture_30 = max(state.wilting_point_pct, state.moisture_30 - depletion_pct)
            state.moisture_60 = max(state.wilting_point_pct, state.moisture_60 - depletion_pct * 0.6)

            if state.pending_irrigation_m3 > 0:
                applied_litres = state.pending_irrigation_m3 * 1000
                state.flow_cumulative_l = (state.flow_cumulative_l + int(applied_litres)) % 65536
                area_m2 = state.area_ha * 10_000
                applied_mm = (state.pending_irrigation_m3 / area_m2) * 1000 if area_m2 else 0
                gain_pct = applied_mm / 4.0
                state.moisture_15 = min(state.field_capacity_pct, state.moisture_15 + gain_pct * 1.3)
                state.moisture_30 = min(state.field_capacity_pct, state.moisture_30 + gain_pct)
                state.moisture_60 = min(state.field_capacity_pct, state.moisture_60 + gain_pct * 0.6)
                logging.info("%s irrigated %.1f L", state.hardware_id, applied_litres)
                state.pending_irrigation_m3 = 0.0

            state.battery_mv = min(4200, max(3300, state.battery_mv + int(daylight * 8) - 2))
            state.soil_temp_c = 22 + 6 * daylight + random.uniform(-0.5, 0.5)
            state.sequence += 1

            frame = encode_uplink(
                sequence=state.sequence,
                moisture_15cm_pct=state.moisture_15,
                moisture_30cm_pct=state.moisture_30,
                moisture_60cm_pct=state.moisture_60,
                soil_temp_c=state.soil_temp_c,
                battery_mv=state.battery_mv,
                flow_litres_cumulative=state.flow_cumulative_l,
                status_bits=(0b0000_1000 if state.battery_mv < 3500 else 0),
            )
            await client.send_message(Message(frame))
            await asyncio.sleep(TICK_SECONDS)
    finally:
        await client.disconnect()


async def main():
    with open(DEVICES_FILE) as f:
        data = json.load(f)

    tasks = []
    for d in data["devices"]:
        state = FarmState(
            hardware_id=d["hardware_id"],
            field_capacity_pct=d["field_capacity_pct"],
            wilting_point_pct=d["wilting_point_pct"],
            area_ha=d["area_ha"],
        )
        tasks.append(run_device(d["connection_string"], state))

    logging.info("starting %d simulated edge boxes, tick=%ss", len(tasks), TICK_SECONDS)
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
