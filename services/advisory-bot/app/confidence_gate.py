"""Confidence gating: a hard requirement, not a nicety.

An advisory that is wrong once loses the farmer for a season. Below the
calibrated threshold the system says it does not know and routes to a human
agronomist, rather than guessing fluently.
"""
from dataclasses import dataclass

from dhara_shared.config import get_settings


@dataclass
class GateResult:
    should_answer: bool
    threshold: float


def gate(confidence: float) -> GateResult:
    settings = get_settings()
    return GateResult(should_answer=confidence >= settings.advisory_confidence_threshold, threshold=settings.advisory_confidence_threshold)
