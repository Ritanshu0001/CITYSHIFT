"""Cooperative cancellation shared by the job runner and data fetchers."""
from __future__ import annotations

import threading
import time


class AnalysisCancelled(RuntimeError):
    """Raised at safe checkpoints when a newer city search supersedes a job."""


def checkpoint(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AnalysisCancelled("Replaced by a newer city search")


def interruptible_wait(cancel_event: threading.Event | None, seconds: float) -> None:
    if cancel_event is None:
        time.sleep(seconds)
        return
    if cancel_event.wait(seconds):
        checkpoint(cancel_event)
