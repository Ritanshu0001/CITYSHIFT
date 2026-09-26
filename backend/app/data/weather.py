"""Open-Meteo historical climate per city (contract D16)."""
from __future__ import annotations

import logging

import requests

from app.schemas import HEAVY_RAIN_MM, RAIN_MM, SNOW_CM, WEATHER_END, WEATHER_START

log = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
N_YEARS = 5  # 2020-01-01 to 2024-12-31

ZERO_CLIMATE = {"rain_days_per_year": 0.0, "heavy_rain_days_per_year": 0.0, "snow_days_per_year": 0.0}


def climate_for(lat: float, lng: float) -> dict:
    """Rain, heavy-rain and snow days per year. Returns zeros on any failure; never raises."""
    params = {
        "latitude": lat,
        "longitude": lng,
        "start_date": WEATHER_START,
        "end_date": WEATHER_END,
        "daily": "precipitation_sum,snowfall_sum",
        "timezone": "auto",
    }
    try:
        resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
        resp.raise_for_status()
        daily = resp.json()["daily"]
        precip = [p for p in daily["precipitation_sum"] if p is not None]
        snow = [s for s in daily["snowfall_sum"] if s is not None]
    except Exception as exc:  # noqa: BLE001 - weather must never take down a city
        log.warning("Open-Meteo failed for (%s, %s): %s; using zeros", lat, lng, exc)
        return dict(ZERO_CLIMATE)

    return {
        "rain_days_per_year": round(sum(p >= RAIN_MM for p in precip) / N_YEARS, 1),
        "heavy_rain_days_per_year": round(sum(p >= HEAVY_RAIN_MM for p in precip) / N_YEARS, 1),
        "snow_days_per_year": round(sum(s >= SNOW_CM for s in snow) / N_YEARS, 1),
    }
