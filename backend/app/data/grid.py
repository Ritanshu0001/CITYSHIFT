"""H3 grid for a city center + fixed radius (contract D8)."""
from __future__ import annotations

import h3

from app.schemas import H3_RES, RADIUS_KM

if not h3.__version__.startswith("4."):
    raise ImportError(f"CityShift needs h3 v4, found {h3.__version__} (CONTRACTS.md D11)")

# Res-8 cells are ~0.92 km apart center to center, so 10 rings covers 8 km with margin.
_RINGS = 10


def hexes_for(lat: float, lng: float) -> list[str]:
    """Res-8 cells whose center is within RADIUS_KM of (lat, lng), sorted for determinism."""
    center = h3.latlng_to_cell(lat, lng, H3_RES)
    keep = [
        cell for cell in h3.grid_disk(center, _RINGS)
        if h3.great_circle_distance((lat, lng), h3.cell_to_latlng(cell), unit="km") <= RADIUS_KM
    ]
    return sorted(keep)
