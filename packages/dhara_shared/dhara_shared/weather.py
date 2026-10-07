"""Weather + solar forecast lookup.

Uses Open-Meteo (no API key required) for both the FAO-56 reference
evapotranspiration used by the water-balance model and the shortwave solar
radiation forecast used by the energy optimizer to size the midday surplus.
A cached seven-day forecast is what lets the edge box keep scheduling
properly through a week with no connectivity at all (L1 on the degradation
ladder); the cloud decision engine re-fetches it every cycle.
"""
from dataclasses import dataclass
from datetime import date

import httpx

from .config import get_settings


@dataclass
class DailyForecast:
    day: date
    eto_mm: float
    shortwave_radiation_mj_m2: float


def fetch_forecast(lat: float, lon: float, days: int = 7) -> list[DailyForecast]:
    settings = get_settings()
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "et0_fao_evapotranspiration,shortwave_radiation_sum",
        "forecast_days": days,
        "timezone": "auto",
    }
    resp = httpx.get(settings.weather_api_base, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()["daily"]

    out = []
    for i, day_str in enumerate(data["time"]):
        out.append(
            DailyForecast(
                day=date.fromisoformat(day_str),
                eto_mm=data["et0_fao_evapotranspiration"][i] or 0.0,
                shortwave_radiation_mj_m2=data["shortwave_radiation_sum"][i] or 0.0,
            )
        )
    return out


def estimate_available_solar_kwh(
    radiation_mj_m2_day: float,
    capacity_kw: float,
    interval_minutes: int,
    performance_ratio: float = 0.78,
) -> float:
    """Very small standing-in model for how much of a plot's/cluster's solar
    surplus is available in one control-loop interval, from a daily radiation
    sum. Good enough for scheduling arbitration; not a bankable yield estimate.
    """
    # Convert MJ/m2/day shortwave sum into an equivalent full-sun hours figure,
    # then scale nameplate capacity by that and by the fraction of the day this interval covers.
    peak_sun_hours = radiation_mj_m2_day / 3.6  # 1 kWh/m2 = 3.6 MJ/m2
    daylight_minutes = 12 * 60
    daily_yield_kwh = capacity_kw * peak_sun_hours * performance_ratio
    fraction_of_day = min(1.0, interval_minutes / daylight_minutes)
    return round(daily_yield_kwh * fraction_of_day, 4)
