"""Voice channel: rung 2 of the farmer interface ("6:40 AM, outbound call.
Voice, any handset."). Built on Azure Communication Services Call Automation,
with text-to-speech supplied inline (no separate Speech SDK call needed for
outbound prompts -- Call Automation's Play/Recognize actions accept a
TextSource with a Cognitive Services voice directly).
"""
import logging
import os
from uuid import uuid4

from azure.communication.callautomation import (
    CallInvite,
    DtmfTone,
    PhoneNumberIdentifier,
    RecognitionChoice,
    RecognizeInputType,
    TextSource,
)
from dhara_shared.config import get_settings

from .clients import api_client, call_automation_client, log_advisory_interaction

CALLBACK_BASE_URL = os.environ.get("ADVISORY_BOT_PUBLIC_URL", "https://localhost")

VOICE_NAME_BY_LANGUAGE = {
    "hi": "hi-IN-SwaraNeural",
    "mr": "mr-IN-AarohiNeural",
    "ta": "ta-IN-PallaviNeural",
    "en": "en-IN-NeerjaNeural",
}


def _voice_for(language: str) -> str:
    return VOICE_NAME_BY_LANGUAGE.get(language, VOICE_NAME_BY_LANGUAGE["hi"])


def start_outbound_advisory_call(plot_id: str, language: str = "hi") -> dict:
    """Rung 2: place an outbound call carrying the latest Decision as a spoken
    recommendation, then let the farmer press 1 to start the pump.
    """
    settings = get_settings()
    with api_client() as client:
        dashboard = client.get(f"/plots/{plot_id}/dashboard").json()

    plot = dashboard["plot"]
    decision = dashboard.get("latest_decision")
    if not decision or decision["depth_mm"] <= 0:
        message = "Namaskar. No irrigation is recommended for your plot in this cycle."
    else:
        message = (
            f"Namaskar. Your {dashboard.get('active_crop_cycle', {}).get('crop', 'crop')} plot needs "
            f"{decision['depth_mm']} millimetres today. Press 1 to start the pump now. "
            f"Press 2 to hear this again. Press 9 to speak to a person."
        )

    client_automation = call_automation_client()
    call_connection_properties = client_automation.create_call(
        target_participant=CallInvite(target=PhoneNumberIdentifier(plot["farmer_phone_e164"])),
        source_caller_id_number=PhoneNumberIdentifier(settings.acs_sender_phone_number),
        callback_url=f"{CALLBACK_BASE_URL}/webhooks/call-callback?plotId={plot_id}&lang={language}",
        operation_context=str(uuid4()),
    )

    log_advisory_interaction(
        plot_id=plot_id,
        channel="voice_call",
        direction="outbound",
        language=language,
        response_text=message,
        confidence=decision.get("confidence") if decision else None,
        model_version=decision.get("model_version") if decision else None,
    )
    return {"call_connection_id": call_connection_properties.call_connection_id, "message": message}


def handle_call_connected(call_connection_id: str, plot_id: str, language: str, message: str) -> None:
    client = call_automation_client()
    call_connection = client.get_call_connection(call_connection_id)

    with api_client() as api:
        plot = api.get(f"/plots/{plot_id}").json()

    choices = [
        RecognitionChoice(label="start_pump", tones=[DtmfTone.ONE]),
        RecognitionChoice(label="repeat", tones=[DtmfTone.TWO]),
        RecognitionChoice(label="human", tones=[DtmfTone.NINE]),
    ]
    call_connection.start_recognizing_media(
        input_type=RecognizeInputType.CHOICES,
        target_participant=PhoneNumberIdentifier(plot["farmer_phone_e164"]),
        choices=choices,
        play_prompt=TextSource(text=message, voice_name=_voice_for(language)),
        interrupt_prompt=True,
        initial_silence_timeout=8,
    )


def handle_recognize_completed(call_connection_id: str, plot_id: str, choice_label: str) -> None:
    client = call_automation_client()
    call_connection = client.get_call_connection(call_connection_id)

    if choice_label == "start_pump":
        with api_client() as api:
            devices = api.get("/devices", params={"plot_id": plot_id}).json()
            controller = next((d for d in devices if d["device_type"] == "edge_controller"), None)
            dashboard = api.get(f"/plots/{plot_id}/dashboard").json()
            decision = dashboard.get("latest_decision")
        if controller and decision:
            from .iot import send_irrigate_command

            send_irrigate_command(controller["hardware_id"], decision["depth_mm"], decision_id=decision["id"])
        call_connection.play_media_to_all(
            play_source=TextSource(text="Pump started. Thank you.", voice_name=_voice_for("hi"))
        )
    elif choice_label == "human":
        call_connection.play_media_to_all(
            play_source=TextSource(
                text="Connecting you to the FPO office. Please hold.", voice_name=_voice_for("hi")
            )
        )
        log_advisory_interaction(
            plot_id=plot_id, channel="voice_call", direction="inbound", escalated_to_human=True, resolved=False
        )
    logging.info("call %s recognized choice %s", call_connection_id, choice_label)
