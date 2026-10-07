"""WhatsApp channel: rung 3 of the farmer interface ("Ask by speaking it.
Answers in the same language, with a photo of the affected leaf if sent.").

Inbound messages arrive as Azure Event Grid events of type
Microsoft.Communication.AdvancedMessageReceived once Advanced Messaging is
configured against a WhatsApp Business number (see docs/azure-requirements.md
-- this step needs a Meta Business verification that cannot be automated).
"""
import logging

from . import nlu
from .clients import find_plot_by_phone, log_advisory_interaction, send_whatsapp_text
from .confidence_gate import gate


def handle_inbound_message(event_data: dict) -> None:
    from_phone = event_data.get("from")
    message_body = (event_data.get("message", {}) or {}).get("content") or event_data.get("content", "")
    media_url = None
    content_type = event_data.get("contentType", "text")
    if content_type == "image":
        media_url = event_data.get("mediaUri") or event_data.get("mediaId")

    plot = find_plot_by_phone(from_phone) if from_phone else None
    plot_id = plot["id"] if plot else None
    language = "hi"  # per-cluster configuration at onboarding; hardcoded default for the pilot

    photo_description = None
    if media_url:
        photo_description = (
            "Farmer sent a photo of a plant/leaf. No automated image classifier is configured; "
            "treat this as insufficient detail for a confident diagnosis."
        )

    result = nlu.get_advisory_response(
        plot_id=plot_id, language=language, user_text=message_body, photo_description=photo_description
    )

    decision = gate(result.get("confidence", 0.0))

    if decision.should_answer and result.get("response_text"):
        send_whatsapp_text(from_phone, result["response_text"])
        escalate = False
    else:
        send_whatsapp_text(
            from_phone,
            "I am not certain from what you sent. I am passing this to the agronomist at your FPO; "
            "they will follow up before noon.",
        )
        escalate = True

    log_advisory_interaction(
        plot_id=plot_id,
        channel="whatsapp",
        direction="inbound",
        language=language,
        input_text=message_body,
        input_photo_url=media_url,
        response_text=result.get("response_text"),
        confidence=result.get("confidence"),
        model_version=result.get("model_version"),
        escalated_to_human=escalate,
        resolved=not escalate,
    )
    logging.info("whatsapp interaction handled for %s (escalated=%s)", from_phone, escalate)
