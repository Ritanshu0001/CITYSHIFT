"""Terrain slope per hex from the Open-Meteo Elevation API (CR-011).

Copernicus DEM GLO-90 (90 m) via Open-Meteo. Per hex: elevation at the center and
its 6 corners, a least-squares plane z = a + b*x + c*y (x, y in metres around the
center), terrain_slope_pct = 100 * sqrt(b^2 + c^2). Points at or below 0 m (sea)
are dropped; fewer than 4 points left -> 0.0.

GLO-90 is a surface model, so very tall downtowns can add a few percent of
apparent slope (the Chicago Loop reads 3.5-4.4% on flat ground).
"""
from __future__ import annotations

import logging
import math
import threading

import h3
import numpy as np

from app.cancellation import checkpoint, interruptible_wait
from app.data.openmeteo import OpenMeteoError, OpenMeteoQuotaError, get_json

log = logging.getLogger(__name__)

ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
BATCH = 100  # Open-Meteo's per-request coordinate limit
RETRIES = 3  # transient failures only; a quota error is never retried
EARTH_RADIUS_M = 6371008.8


def _points(cell: str) -> list[tuple[float, float]]:
    """Center + 6 corners, rounded so corners shared by neighbouring hexes dedupe."""
    return [(round(lat, 6), round(lng, 6)) for lat, lng in (h3.cell_to_latlng(cell), *h3.cell_to_boundary(cell))]


def _fetch_batch(
    batch: list[tuple[float, float]], cancel_event: threading.Event | None = None
) -> list[float | None]:
    params = {
        "latitude": ",".join(f"{lat:.6f}" for lat, _ in batch),
        "longitude": ",".join(f"{lng:.6f}" for _, lng in batch),
    }

    def validate(data: dict) -> None:
        values = data.get("elevation") if isinstance(data, dict) else None
        if not isinstance(values, list) or len(values) != len(batch):
            raise OpenMeteoError(f"Open-Meteo elevation returned {len(values or [])} values for {len(batch)} points")

    for attempt in range(RETRIES + 1):
        try:
            return get_json(
                ELEVATION_URL, params, cost=len(batch), what="elevation", validate=validate,
                cancel_event=cancel_event,
            )["elevation"]
        except OpenMeteoQuotaError:
            raise
        except OpenMeteoError as exc:
            if attempt == RETRIES:
                raise OpenMeteoError(f"elevation failed after {RETRIES + 1} attempts: {exc}") from exc
            wait = 2 ** (attempt + 1)
            log.warning("elevation batch failed (%s); retrying in %d s", exc, wait)
            interruptible_wait(cancel_event, wait)
    raise AssertionError("unreachable")


def _slope(cell: str, elevation: dict[tuple[float, float], float | None]) -> float:
    lat0, lng0 = h3.cell_to_latlng(cell)
    rows = []
    for lat, lng in _points(cell):
        z = elevation[(lat, lng)]
        if z is None or z <= 0:
            continue
        x = math.radians(lng - lng0) * EARTH_RADIUS_M * math.cos(math.radians(lat0))
        y = math.radians(lat - lat0) * EARTH_RADIUS_M
        rows.append((x, y, float(z)))
    if len(rows) < 4:
        return 0.0
    pts = np.array(rows)
    design = np.column_stack([np.ones(len(pts)), pts[:, 0], pts[:, 1]])
    (_, b, c), *_ = np.linalg.lstsq(design, pts[:, 2], rcond=None)
    return round(100.0 * math.hypot(b, c), 6)


def terrain_slopes(
    hex_ids: list[str], stats: dict | None = None, cancel_event: threading.Event | None = None
) -> dict[str, float]:
    """terrain_slope_pct for every hex id. Raises OpenMeteoError (never returns zeros for a failure).

    Pass the full grid (hexes_for) so the batches, and therefore the cache keys, are
    the same on every run. `stats`, if given, receives points and request counts.
    """
    points = sorted({p for cell in hex_ids for p in _points(cell)})
    elevation: dict[tuple[float, float], float | None] = {}
    for start in range(0, len(points), BATCH):
        checkpoint(cancel_event)
        batch = points[start:start + BATCH]
        elevation.update(zip(batch, _fetch_batch(batch, cancel_event)))
    if stats is not None:
        stats.update(points=len(points), requests=math.ceil(len(points) / BATCH))
    return {cell: _slope(cell, elevation) for cell in hex_ids}
