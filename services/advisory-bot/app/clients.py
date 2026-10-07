import logging
import os

import httpx
from azure.communication.callautomation import CallAutomationClient
from azure.communication.messages import NotificationMessagesClient
from azure.communication.messages.models import TextNotificationContent
from dhara_shared.config import get_settings

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")


def api_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=15)


def whatsapp_client() -> NotificationMessagesClient:
    settings = get_settings()
    return NotificationMessagesClient.from_connection_string(settings.acs_connection_string)


def call_automation_client() -> CallAutomationClient:
    settings = get_settings()
    return CallAutomationClient.from_connection_string(settings.acs_connection_string)


def send_whatsapp_text(to_e164: str, text: str) -> None:
    settings = get_settings()
    try:
        client = whatsapp_client()
        content = TextNotificationContent(
            channel_registration_id=settings.acs_whatsapp_channel_registration_id,
            to=[to_e164],
            content=text,
        )
        client.send(content)
    except Exception:
        logging.exception("failed to send WhatsApp reply to %s", to_e164)


def find_plot_by_phone(phone_e164: str) -> dict | None:
    with api_client() as client:
        resp = client.get("/plots")
        resp.raise_for_status()
        for plot in resp.json():
            if plot["farmer_phone_e164"] == phone_e164:
                return plot
    return None


def log_advisory_interaction(**kwargs) -> None:
    with api_client() as client:
        try:
            client.post("/advisory/interactions", json=kwargs)
        except Exception:
            logging.exception("failed to log advisory interaction")
