import logging

from fastapi import FastAPI, Request

from . import voice, whatsapp
from .clients import api_client

logging.basicConfig(level="INFO")

app = FastAPI(title="DHARA Advisory Bot", description="WhatsApp + voice farmer advisory channel")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/webhooks/eventgrid")
async def eventgrid_webhook(request: Request):
    """Single Event Grid endpoint for both WhatsApp Advanced Messaging events
    and ACS Call Automation's IncomingCall event. Handles the Event Grid
    subscription validation handshake on first registration.
    """
    events = await request.json()
    if isinstance(events, dict):
        events = [events]

    responses = []
    for event in events:
        event_type = event.get("eventType")
        data = event.get("data", {})

        if event_type == "Microsoft.EventGrid.SubscriptionValidationEvent":
            responses.append({"validationResponse": data.get("validationCode")})
            continue

        if event_type == "Microsoft.Communication.AdvancedMessageReceived":
            try:
                whatsapp.handle_inbound_message(data)
            except Exception:
                logging.exception("failed to handle inbound WhatsApp message")

        elif event_type == "Microsoft.Communication.IncomingCall":
            # Route inbound calls (farmer calling the FPO number) to a human/agronomist queue.
            # Outbound advisory calls are initiated by /outbound/voice-advisory instead.
            logging.info("inbound call received; routing handled by ACS call-flow config")

    return responses[0] if len(responses) == 1 and "validationResponse" in responses[0] else {"status": "accepted"}


@app.post("/webhooks/call-callback")
async def call_callback(request: Request, plotId: str, lang: str = "hi"):
    """Call Automation mid-call callback events (delivered as a CloudEvent array)."""
    events = await request.json()
    for event in events:
        event_type = event.get("type", "")
        call_connection_id = event.get("data", {}).get("callConnectionId")

        if event_type.endswith("CallConnected"):
            with api_client() as client:
                dashboard = client.get(f"/plots/{plotId}/dashboard").json()
            decision = dashboard.get("latest_decision")
            message = (
                f"Namaskar. Your plot needs {decision['depth_mm']} millimetres today. Press 1 to start the pump."
                if decision and decision["depth_mm"] > 0
                else "Namaskar. No irrigation is recommended today."
            )
            voice.handle_call_connected(call_connection_id, plotId, lang, message)

        elif event_type.endswith("RecognizeCompleted"):
            choice_label = event.get("data", {}).get("choiceResult", {}).get("label", "")
            voice.handle_recognize_completed(call_connection_id, plotId, choice_label)

        elif event_type.endswith("RecognizeFailed"):
            logging.warning("recognize failed for call %s", call_connection_id)

    return {"status": "ok"}


@app.post("/outbound/voice-advisory")
def trigger_outbound_advisory(plot_id: str, language: str = "hi"):
    """Called by the decision-engine's daily advisory scheduler (rung 2: outbound voice call)."""
    return voice.start_outbound_advisory_call(plot_id, language)
