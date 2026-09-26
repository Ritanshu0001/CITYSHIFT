"""Open-Meteo historical climate per city (contract D16).

A failed fetch raises: fake zeros in city.json would silently rescale every
climate comparison and scenario (e.g. "0 rain days"), so the job errors instead.
"""
from __future__ import annotations

import threading
from datetime import date

from app.data.openmeteo import OpenMeteoError, get_json, weather_cost
from app.schemas import HEAVY_RAIN_MM, RAIN_MM, SNOW_CM, WEATHER_END, WEATHER_START

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
N_YEARS = 5  # 2020-01-01 to 2024-12-31
DAILY = ["precipitation_sum", "snowfall_sum"]


def _series(data: dict, n_days: int) -> tuple[list[float], list[float]]:
    """Daily precipitation and snowfall, or OpenMeteoError if the payload is unusable."""
    try:
        daily = data["daily"]
        precip = [p for p in daily["precipitation_sum"] if p is not None]
        snow = [s for s in daily["snowfall_sum"] if s is not None]
    except (KeyError, TypeError) as exc:
        raise OpenMeteoError(f"Open-Meteo weather response is missing {exc}") from exc
    if len(precip) < n_days * 0.9:
        raise OpenMeteoError(f"Open-Meteo weather has only {len(precip)} of {n_days} days")
    return precip, snow


def climate_for(lat: float, lng: float, cancel_event: threading.Event | None = None) -> dict:
    """Rain, heavy-rain and snow days per year. Raises OpenMeteoError on any failure."""
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": WEATHER_START,
        "end_date": WEATHER_END,
        "daily": ",".join(DAILY),
        "timezone": "auto",
    }
    n_days = (date.fromisoformat(WEATHER_END) - date.fromisoformat(WEATHER_START)).days + 1
    data = get_json(ARCHIVE_URL, params, cost=weather_cost(n_days, len(DAILY)), what="weather",
                    validate=lambda d: _series(d, n_days), cancel_event=cancel_event)
    precip, snow = _series(data, n_days)

    return {
        "rain_days_per_year": round(sum(p >= RAIN_MM for p in precip) / N_YEARS, 1),
        "heavy_rain_days_per_year": round(sum(p >= HEAVY_RAIN_MM for p in precip) / N_YEARS, 1),
        "snow_days_per_year": round(sum(s >= SNOW_CM for s in snow) / N_YEARS, 1),
    }
