"""Cancellation checkpoints for waits inside a job (Open-Meteo budget pauses)."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.cancellation import AnalysisCancelled, interruptible_wait
from app.data import openmeteo


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
