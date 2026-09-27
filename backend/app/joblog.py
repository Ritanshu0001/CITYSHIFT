"""Per-job log capture for GET /jobs/{id} (CR-019), so the browser console can show each step.

A job binds its JobLog into a context variable; every `app.*` log record emitted in that
context lands in it. Work handed to other threads keeps the binding when it is started
with `in_context` (plain threads start with an empty context).
"""
from __future__ import annotations

import contextvars
import logging
import threading
import time
from collections import deque
from typing import Callable, TypeVar

MAX_LINES = 500
MAX_MESSAGE_CHARS = 4000

T = TypeVar("T")


class JobLog:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self._lines: deque[dict] = deque(maxlen=MAX_LINES)
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, level: str, source: str, message: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append({
                "seq": self._seq,
                "t": round(time.monotonic() - self.started, 2),
                "level": level,
                "source": source,
                "message": message[:MAX_MESSAGE_CHARS],
            })

    def lines(self) -> list[dict]:
        with self._lock:
            return list(self._lines)


_current: contextvars.ContextVar[JobLog | None] = contextvars.ContextVar("job_log", default=None)


def bind(job_log: JobLog) -> contextvars.Token:
    return _current.set(job_log)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)


def in_context(fn: Callable[..., T]) -> Callable[..., T]:
    """fn, run in a copy of the caller's context: pass this to a thread or pool instead of fn."""
    ctx = contextvars.copy_context()
    return lambda *args, **kwargs: ctx.run(fn, *args, **kwargs)


class _Handler(logging.Handler):
    _formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        job_log = _current.get()
        if job_log is None:
            return
        try:
            message = record.getMessage()
            if record.exc_info:
                message = f"{message}\n{self._formatter.formatException(record.exc_info)}"
        except Exception:  # noqa: BLE001 - a bad log call never breaks a job
            return
        job_log.add(record.levelname, record.name.removeprefix("app."), message)


_installed = False


def install() -> None:
    global _installed
    if not _installed:
        logging.getLogger("app").addHandler(_Handler())
        _installed = True
