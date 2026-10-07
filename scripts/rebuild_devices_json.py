"""One-off helper: reconstruct services/edge-simulator/devices.json for an
already-provisioned cluster, by reading Device/Plot rows back from the API and
fetching each device's current IoT Hub key. Useful after devices.json is lost
locally but the cluster/devices already exist in Postgres + IoT Hub (e.g. a
Docker volume-mount mishap on Windows -- see docs/SETUP.md).
"""
import json
import os
import sys

import httpx
from azure.iot.hub import IoTHubRegistryManager
from dhara_shared.config import get_settings

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")


def main(cluster_id: str) -> None:
    settings = get_settings()
    registry = IoTHubRegistryManager(settings.iot_hub_connection_string)
    hub_hostname = f"{settings.iot_hub_name}.azure-devices.net"

    with httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=20) as client:
        cluster = client.get(f"/clusters/{cluster_id}").json()
        plots = client.get("/plots", params={"cluster_id": cluster_id}).json()

        devices_out = []
        for plot in plots:
            devices = client.get("/devices", params={"plot_id": plot["id"]}).json()
            controller = next((d for d in devices if d["device_type"] == "edge_controller"), None)
            if not controller:
                continue
            conn = registry.get_device(controller["hardware_id"])
            primary_key = conn.authentication.symmetric_key.primary_key
            connection_string = f"HostName={hub_hostname};DeviceId={controller['hardware_id']};SharedAccessKey={primary_key}"
            devices_out.append(
                {
                    "plot_id": plot["id"],
                    "device_id": controller["id"],
                    "hardware_id": controller["hardware_id"],
                    "connection_string": connection_string,
                    "field_capacity_pct": plot["field_capacity_pct"],
                    "wilting_point_pct": plot["wilting_point_pct"],
                    "area_ha": plot["area_ha"],
                }
            )

    out_path = os.path.join(os.path.dirname(__file__), "..", "services", "edge-simulator", "devices.json")
    with open(out_path, "w") as f:
        json.dump({"cluster": cluster, "devices": devices_out}, f, indent=2)
    print(f"Wrote {out_path} with {len(devices_out)} devices.")


if __name__ == "__main__":
    main(sys.argv[1])
