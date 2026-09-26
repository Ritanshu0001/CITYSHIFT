"""In-process job registry: one worker thread, one dict, one queue (contract D5)."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from app import cache
from app.cancellation import AnalysisCancelled
from app.pipeline import analyze_city
from app.schemas import JOB_STEPS

log = logging.getLogger(__name__)

STEP_MESSAGES = {
    "roads": "Downloading the road network",
    "infrastructure": "Downloading signals, crossings, transit and places",
    "weather": "Pulling weather and elevation",
    "scoring": "Scoring hexes against Waymo's established cities",
    "scenarios": "Building test scenarios",
}


@dataclass
class JobState:
    job_id: str
    slug: str
    name: str
    lat: float
    lng: float
    country_code: str | None
    status: str = "queued"  # queued -> running -> done | error | cancelled
    step: str | None = None
    steps_done: list[str] = field(default_factory=list)
    message: str | None = "Waiting for the previous city to finish"
    error: str | None = None
    cached: bool = False
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)
    submitted_at: float = field(default_factory=time.monotonic, repr=False, compare=False)

    def status_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "slug": self.slug,
            "status": self.status,
            "step": self.step,
            "steps_done": list(self.steps_done),
            "message": self.message,
            "error": self.error,
        }


_jobs: dict[str, JobState] = {}
_queue: "queue.Queue[JobState]" = queue.Queue()
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _cancel(job: JobState) -> None:
    """Mark an active job as superseded. Queue entries are skipped as tombstones."""
    if job.status not in ("queued", "running"):
        return
    log.info("job %s: cancelling %s (was %s, step %s)", job.job_id, job.slug, job.status, job.step)
    job.cancel_event.set()
    job.status = "cancelled"
    job.step = None
    job.message = "Replaced by a newer city search"
    job.error = None


def submit(
    name: str,
    lat: float,
    lng: float,
    country_code: str | None,
    supersedes_job_id: str | None = None,
) -> JobState:
    """Returns immediately; a new search may supersede that browser tab's prior job."""
    slug = cache.slugify(name)
    with _lock:
        previous = _jobs.get(supersedes_job_id) if supersedes_job_id else None
        # A second click on the same city joins the job already in flight.
        for job in _jobs.values():
            if job.slug == slug and job.status in ("queued", "running"):
                if previous is not None and previous is not job:
                    _cancel(previous)
                log.info("job %s: %s is already %s; joining it", job.job_id, slug, job.status)
                return job

        if previous is not None:
            _cancel(previous)

        if cache.has_result(slug):
            job = JobState(uuid.uuid4().hex, slug, name, lat, lng, country_code, status="done",
                           steps_done=list(JOB_STEPS), message="Loaded from cache", cached=True)
            _jobs[job.job_id] = job
            log.info("job %s: %s loaded from cache", job.job_id, slug)
            return job
        ahead = sum(j.status in ("queued", "running") for j in _jobs.values())
        job = JobState(uuid.uuid4().hex, slug, name, lat, lng, country_code)
        _jobs[job.job_id] = job
        log.info("job %s: queued %s (%s) at (%.5f, %.5f), %d job(s) ahead",
                 job.job_id, name, slug, lat, lng, ahead)
        _ensure_worker()
    _queue.put(job)
    return job


def get(job_id: str) -> JobState | None:
    return _jobs.get(job_id)


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run_forever, name="cityshift-jobs", daemon=True)
        _worker.start()


def _run_forever() -> None:
    while True:
        job = _queue.get()
        try:
            _run(job)
        finally:
            _queue.task_done()


def _run(job: JobState) -> None:
    def progress(step: str) -> None:
        if job.cancel_event.is_set():
            raise AnalysisCancelled("Replaced by a newer city search")
        with _lock:
            if job.step and job.step not in job.steps_done:
                job.steps_done.append(job.step)
            job.step = step
            job.message = STEP_MESSAGES.get(step, step)

    with _lock:
        if job.status == "cancelled" or job.cancel_event.is_set():
            return
        job.status = "running"
    started = time.monotonic()
    log.info("job %s: analyzing %s (%s) after %.1f s in the queue",
             job.job_id, job.name, job.slug, started - job.submitted_at)
    try:
        analyze_city(job.name, job.lat, job.lng, job.country_code, progress, job.cancel_event)
    except AnalysisCancelled:
        with _lock:
            _cancel(job)
        log.info("job %s: superseded after %.1f s", job.job_id, time.monotonic() - started)
        return
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable job error
        with _lock:
            if job.cancel_event.is_set():
                _cancel(job)
                log.info("job %s: superseded", job.job_id)
                return
            job.status = "error"
            job.error = str(exc) or type(exc).__name__
            job.message = None
        log.exception("job %s failed at step %s after %.1f s", job.job_id, job.step, time.monotonic() - started)
        return
    with _lock:
        if job.cancel_event.is_set():
            _cancel(job)
            return
        job.status = "done"
        job.steps_done = list(JOB_STEPS)
        job.step = None
        job.message = "Done"
    log.info("job %s: done %s in %.1f s", job.job_id, job.slug, time.monotonic() - started)
