"""In-process job registry: one worker thread, one dict, one queue (contract D5)."""
from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass, field

from app import cache
from app.pipeline import analyze_city
from app.schemas import JOB_STEPS

log = logging.getLogger(__name__)

STEP_MESSAGES = {
    "roads": "Downloading the road network",
    "infrastructure": "Downloading signals, crossings, transit and places",
    "weather": "Fetching five years of weather",
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
    status: str = "queued"  # queued -> running -> done | error
    step: str | None = None
    steps_done: list[str] = field(default_factory=list)
    message: str | None = "Waiting for the previous city to finish"
    error: str | None = None
    cached: bool = False

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


def submit(name: str, lat: float, lng: float, country_code: str | None) -> JobState:
    """Returns immediately. A cached city gets a job already in 'done'."""
    slug = cache.slugify(name)
    with _lock:
        if cache.has_result(slug):
            job = JobState(uuid.uuid4().hex, slug, name, lat, lng, country_code, status="done",
                           steps_done=list(JOB_STEPS), message="Loaded from cache", cached=True)
            _jobs[job.job_id] = job
            return job
        # A second click on the same city joins the job already in flight.
        for job in _jobs.values():
            if job.slug == slug and job.status in ("queued", "running"):
                return job
        job = JobState(uuid.uuid4().hex, slug, name, lat, lng, country_code)
        _jobs[job.job_id] = job
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
        with _lock:
            if job.step and job.step not in job.steps_done:
                job.steps_done.append(job.step)
            job.step = step
            job.message = STEP_MESSAGES.get(step, step)

    with _lock:
        job.status = "running"
    log.info("job %s: analyzing %s (%s)", job.job_id, job.name, job.slug)
    try:
        analyze_city(job.name, job.lat, job.lng, job.country_code, progress)
    except Exception as exc:  # noqa: BLE001 - every failure becomes a readable job error
        log.exception("job %s failed", job.job_id)
        with _lock:
            job.status = "error"
            job.error = str(exc) or type(exc).__name__
            job.message = None
        return
    with _lock:
        job.status = "done"
        job.steps_done = list(JOB_STEPS)
        job.step = None
        job.message = "Done"
    log.info("job %s: done", job.job_id)
