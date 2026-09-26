"""Cancellation checkpoints for the slow elevation path."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import h3
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.cancellation import AnalysisCancelled, interruptible_wait
from app.data import elevation, openmeteo


def test_interruptible_wait_stops_as_soon_as_job_is_cancelled():
    event = threading.Event()
    timer = threading.Timer(0.02, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(AnalysisCancelled):
            interruptible_wait(event, 10)
    finally:
        timer.cancel()

    assert time.monotonic() - started < 0.5


def test_openmeteo_quota_wait_is_interruptible(monkeypatch: pytest.MonkeyPatch):
    event = threading.Event()
    monkeypatch.setattr(openmeteo, "_window", openmeteo.deque([(time.monotonic(), openmeteo.MINUTE_BUDGET)]))
    timer = threading.Timer(0.02, event.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(AnalysisCancelled):
            openmeteo._wait_for_budget(1, event)
    finally:
        timer.cancel()

    assert time.monotonic() - started < 0.5


def test_elevation_stops_before_starting_another_batch(monkeypatch: pytest.MonkeyPatch):
    event = threading.Event()
    event.set()
    calls = 0

    def unexpected_fetch(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(elevation, "_fetch_batch", unexpected_fetch)
    cell = h3.latlng_to_cell(40.7128, -74.006, 8)

    with pytest.raises(AnalysisCancelled):
        elevation.terrain_slopes([cell], cancel_event=event)

    assert calls == 0
