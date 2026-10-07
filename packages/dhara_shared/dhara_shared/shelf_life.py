"""Per-lot shelf-life clock ("predicts remaining life per lot rather than per
bay. A lot that warmed during a door-open event moves up the dispatch queue
automatically.").

Uses a standard Q10 temperature-coefficient ageing model: the rate of quality
loss roughly doubles (Q10 ~= 2) for every 10 C above the reference cold-chain
temperature. Each thermal-history sample consumes a slice of the lot's
reference shelf life at a rate scaled by how far its temperature was from the
reference; summing the consumed fraction gives remaining shelf life.
"""
from dataclasses import dataclass

REFERENCE_TEMP_C = 4.0        # target cold-room holding temperature
REFERENCE_SHELF_LIFE_HOURS = {
    "tomato": 240.0,   # ~10 days at 4C, standard produce-storage guidance
    "onion": 2400.0,   # ~100 days, cured onion
    "default": 168.0,  # 7 days, conservative default for an unlisted crop
}
Q10 = 2.0


@dataclass
class ThermalSample:
    hours_since_previous: float
    temp_c: float


def predict_remaining_shelf_life_hours(
    crop: str,
    thermal_history: list[dict],
) -> float:
    """thermal_history: list of {"ts": iso8601, "temp_c": float}, chronological."""
    reference_hours = REFERENCE_SHELF_LIFE_HOURS.get(crop.lower(), REFERENCE_SHELF_LIFE_HOURS["default"])
    if len(thermal_history) < 2:
        return reference_hours

    from datetime import datetime

    consumed_fraction = 0.0
    for prev, curr in zip(thermal_history, thermal_history[1:]):
        t0 = datetime.fromisoformat(prev["ts"])
        t1 = datetime.fromisoformat(curr["ts"])
        elapsed_hours = max(0.0, (t1 - t0).total_seconds() / 3600.0)
        avg_temp = (prev["temp_c"] + curr["temp_c"]) / 2.0

        # Rate multiplier relative to holding this lot at the reference temperature.
        rate_multiplier = Q10 ** ((avg_temp - REFERENCE_TEMP_C) / 10.0)
        consumed_fraction += elapsed_hours * rate_multiplier / reference_hours

    remaining = max(0.0, reference_hours * (1 - consumed_fraction))
    return round(remaining, 1)
