"""Country -> driving side, offline (contract D15)."""
from __future__ import annotations

import logging
from typing import Literal

log = logging.getLogger(__name__)

LEFT_HAND_TRAFFIC = frozenset("""
    GB IE MT CY AU NZ PG FJ SB TO WS KI NR TV CK NU JP TH MY SG ID BN TL HK MO
    IN PK BD LK NP BT MV ZA NA BW ZW ZM MW MZ LS SZ KE UG TZ MU SC JM TT BB BS
    GY SR AG DM GD KN LC VC BM KY VG AI MS TC FK SH
""".split())


def driving_side(country_code: str | None) -> Literal["left", "right"]:
    if country_code and country_code.strip().upper() in LEFT_HAND_TRAFFIC:
        return "left"
    return "right"


def country_for(lat: float, lng: float) -> str | None:
    """ISO alpha-2 code from an offline reverse geocode, or None if that fails."""
    try:
        import reverse_geocoder as rg

        hit = rg.search([(lat, lng)], mode=1, verbose=False)[0]
        return hit["cc"] or None
    except Exception as exc:  # noqa: BLE001 - fall back to "right"
        log.warning("reverse_geocoder failed for (%s, %s): %s", lat, lng, exc)
        return None
