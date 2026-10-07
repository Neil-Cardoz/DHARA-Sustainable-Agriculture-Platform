"""Seeds one demo FPO cluster with N farms and registers a simulated edge-box
device identity for each one, both in the DHARA core API (Postgres) and in
Azure IoT Hub's device registry.

Usage:
    python provision_devices.py --farms 20 --cluster-name "Niphad Cluster" \
        --district Nashik --state Maharashtra --lat 20.0859 --lon 73.9862

Writes services/edge-simulator/devices.json with each device's IoT Hub
connection string, consumed by simulator.py.
"""
import argparse
import json
import os
import random
from datetime import date, timedelta

import httpx
from azure.iot.hub import IoTHubRegistryManager
from dhara_shared.config import get_settings
from dhara_shared.water_balance import DEFAULT_KC_CURVES

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")

CROPS = ["tomato", "onion", "chickpea"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--farms", type=int, default=20)
    parser.add_argument("--cluster-name", default="Niphad Demo Cluster")
    parser.add_argument("--district", default="Nashik")
    parser.add_argument("--state", default="Maharashtra")
    parser.add_argument("--lat", type=float, default=20.0859)
    parser.add_argument("--lon", type=float, default=73.9862)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.iot_hub_connection_string or not settings.iot_hub_name:
        raise SystemExit("Set IOT_HUB_CONNECTION_STRING and IOT_HUB_NAME before provisioning.")

    registry = IoTHubRegistryManager(settings.iot_hub_connection_string)
    hub_hostname = f"{settings.iot_hub_name}.azure-devices.net"

    with httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=20) as client:
        cluster = client.post(
            "/clusters",
            json={
                "name": args.cluster_name,
                "district": args.district,
                "state": args.state,
                "centroid_lat": args.lat,
                "centroid_lon": args.lon,
                "seasonal_volumetric_allocation_m3": 650_000,
                "cold_room_capacity_kg": 5000,
                "cold_room_pv_kwp": 5.0,
                "thermal_store_capacity_kwh_equiv": 15.0,
                "battery_capacity_kwh": 2.0,
            },
        ).json()
        print(f"created cluster {cluster['id']} ({cluster['name']})")

        gateway_hw_id = f"dhara-gateway-{cluster['id'][:8]}"
        _register_iot_device(registry, gateway_hw_id)
        gateway_device = client.post(
            "/devices",
            json={
                "cluster_id": cluster["id"],
                "device_type": "gateway",
                "hardware_id": gateway_hw_id,
                "firmware_version": "1.0.0",
                "health_state": "healthy",
            },
        ).json()
        print(f"registered gateway device {gateway_device['hardware_id']}")

        devices_out = []
        for i in range(args.farms):
            lat_jitter = args.lat + random.uniform(-0.03, 0.03)
            lon_jitter = args.lon + random.uniform(-0.03, 0.03)
            plot = client.post(
                "/plots",
                json={
                    "cluster_id": cluster["id"],
                    "farmer_name": f"Demo Farmer {i+1:03d}",
                    "farmer_phone_e164": f"+91900000{i:04d}",
                    "centroid_lat": lat_jitter,
                    "centroid_lon": lon_jitter,
                    "area_ha": round(random.uniform(0.8, 1.6), 2),
                    "soil_texture": "loam",
                    "field_capacity_pct": 32.0,
                    "wilting_point_pct": 14.0,
                    "farmer_profile": "A",
                    "seasonal_volumetric_cap_m3": 6500.0,
                    "seasonal_volumetric_used_m3": 0.0,
                    "solar_pump_capacity_kw": 3.0,
                    "pumping_head_m": 40.0,
                    "pump_wire_to_water_efficiency": 0.35,
                },
            ).json()

            crop = random.choice(CROPS)
            client.post(
                f"/plots/{plot['id']}/crop-cycles",
                json={
                    "crop": crop,
                    "sowing_date": (date.today() - timedelta(days=random.randint(20, 60))).isoformat(),
                    "stage": random.choice(["development", "mid_season"]),
                    "kc_curve": DEFAULT_KC_CURVES.get(crop, {}),
                    "seasonal_eto_mm": 450.0,
                    "status": "active",
                },
            )

            hw_id = f"dhara-edge-{i:04d}"
            _register_iot_device(registry, hw_id)
            device = client.post(
                "/devices",
                json={
                    "plot_id": plot["id"],
                    "device_type": "edge_controller",
                    "hardware_id": hw_id,
                    "firmware_version": "0.1.0",
                    "health_state": "healthy",
                },
            ).json()

            conn = registry.get_device(hw_id)
            primary_key = conn.authentication.symmetric_key.primary_key
            connection_string = f"HostName={hub_hostname};DeviceId={hw_id};SharedAccessKey={primary_key}"

            devices_out.append(
                {
                    "plot_id": plot["id"],
                    "device_id": device["id"],
                    "hardware_id": hw_id,
                    "connection_string": connection_string,
                    "field_capacity_pct": plot["field_capacity_pct"],
                    "wilting_point_pct": plot["wilting_point_pct"],
                    "area_ha": plot["area_ha"],
                }
            )
            print(f"  provisioned plot {i+1}/{args.farms}: {plot['farmer_name']} ({hw_id})")

    out_path = os.path.join(os.path.dirname(__file__), "devices.json")
    with open(out_path, "w") as f:
        json.dump({"cluster": cluster, "devices": devices_out}, f, indent=2)
    print(f"\nWrote {out_path} -- run simulator.py to start streaming telemetry.")


def _register_iot_device(registry: IoTHubRegistryManager, device_id: str) -> None:
    try:
        registry.create_device_with_sas(device_id, None, None, "enabled")
    except Exception as exc:
        if "already exists" in str(exc).lower() or "409" in str(exc):
            pass
        else:
            raise


if __name__ == "__main__":
    main()
