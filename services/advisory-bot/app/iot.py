import json
import logging

from azure.iot.hub import IoTHubRegistryManager
from dhara_shared.config import get_settings

_registry = None


def _get_registry():
    global _registry
    settings = get_settings()
    if settings.iot_hub_connection_string is None:
        return None
    if _registry is None:
        _registry = IoTHubRegistryManager(settings.iot_hub_connection_string)
    return _registry


def send_irrigate_command(device_hardware_id: str, depth_mm: float, decision_id: str) -> None:
    registry = _get_registry()
    if registry is None:
        logging.info("IOT_HUB_CONNECTION_STRING not set; skipping C2D send for %s", device_hardware_id)
        return
    try:
        registry.send_c2d_message(
            device_hardware_id,
            json.dumps({"command": "irrigate", "depth_mm": depth_mm, "decision_id": decision_id, "source": "voice_confirm"}),
        )
    except Exception:
        logging.exception("failed to send C2D irrigate command to %s", device_hardware_id)
