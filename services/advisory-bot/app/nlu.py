"""Azure OpenAI-backed advisory reasoning.

The model is asked to answer strictly from the plot's own sensed/decided data
(fetched from the core API, never invented) and to self-report a calibrated
confidence. Every response carries its inputs and model version so a wrong
call can be traced and corrected -- the advisory-side half of the same audit
principle that Decision/IrrigationEvent implement on the control side.
"""
import json
import logging
import os

import httpx
from dhara_shared.config import get_settings
from openai import AzureOpenAI

MODEL_VERSION_PREFIX = "advisory-nlu-0.1.0"

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_SHARED_SECRET", "dev-only-change-me")

SYSTEM_PROMPT = """You are DHARA's farm advisory assistant. You answer smallholder farmers about
irrigation, crop stress, and post-harvest storage, in the language they wrote in.

Rules:
- Use ONLY the plot data given to you below. Never invent a moisture reading, price, or
  recommendation you were not given.
- Reason before instruction: say WHY (what the data shows), then WHAT to do.
- Keep answers to 2-3 short sentences, suitable for a WhatsApp voice note transcript.
- If a leaf-disease/pest photo description is given without clear diagnostic detail,
  or the question is outside plot irrigation/storage/basic agronomy, set confidence low
  and say you are unsure rather than guessing.
- Reply with strict JSON: {"response_text": str, "confidence": float 0-1, "reason_code": str}.
"""


def _get_client() -> AzureOpenAI:
    settings = get_settings()
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _fetch_plot_context(plot_id: str | None) -> dict:
    if not plot_id:
        return {}
    with httpx.Client(base_url=API_BASE_URL, headers={"X-API-Key": API_KEY}, timeout=10) as client:
        resp = client.get(f"/plots/{plot_id}/dashboard")
        if resp.status_code != 200:
            return {}
        return resp.json()


def get_advisory_response(
    *, plot_id: str | None, language: str, user_text: str, photo_description: str | None = None
) -> dict:
    """Returns {"response_text", "confidence", "reason_code", "model_version"}."""
    settings = get_settings()
    context = _fetch_plot_context(plot_id)

    user_payload = {
        "language": language,
        "question": user_text,
        "photo_description": photo_description,
        "plot_context": context,
    }

    try:
        client = _get_client()
        completion = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, default=str)},
            ],
        )
        parsed = json.loads(completion.choices[0].message.content)
        parsed["model_version"] = f"{MODEL_VERSION_PREFIX}:{settings.azure_openai_deployment}"
        return parsed
    except Exception:
        logging.exception("advisory NLU call failed; escalating to human by default")
        return {
            "response_text": "",
            "confidence": 0.0,
            "reason_code": "NLU_UNAVAILABLE",
            "model_version": MODEL_VERSION_PREFIX,
        }
