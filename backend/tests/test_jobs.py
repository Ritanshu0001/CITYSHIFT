"""Unit tests for the in-process latest-search-wins job queue.

These tests deliberately replace the registry, queue, worker starter and cache
probe for every test.  Nothing here starts a background thread or reads/writes
the repository cache, which keeps cancellation races deterministic.
"""

from __future__ import annotations

import queue
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import jobs


@pytest.fixture
def isolated_jobs(monkeypatch: pytest.MonkeyPatch):
    """Give each test a fresh, worker-free in-memory registry."""
    monkeypatch.setattr(jobs, "_jobs", {})
    monkeypatch.setattr(jobs, "_queue", queue.Queue())
    monkeypatch.setattr(jobs, "_worker", None)
    monkeypatch.setattr(jobs, "_ensure_worker", lambda: None)
    monkeypatch.setattr(jobs.cache, "has_result", lambda _slug: False)
    return jobs


def _submit(module, name: str, supersedes_job_id: str | None = None):
    return module.submit(
        name,
        40.0,
        -74.0,
        "US",
        supersedes_job_id=supersedes_job_id,
    )


def test_new_job_has_an_unset_cancellation_event(isolated_jobs):
    job = _submit(isolated_jobs, "First City")

    assert job.status == "queued"
    assert not job.cancel_event.is_set()
    assert isolated_jobs._queue.get_nowait() is job


def test_same_slug_joins_in_flight_job_without_cancelling_it(isolated_jobs):
    original = _submit(isolated_jobs, "Same City")

    joined = isolated_jobs.submit(
        "Same City",
        41.0,
        -75.0,
        "US",
        supersedes_job_id=original.job_id,
    )

    assert joined is original
    assert original.status == "queued"
    assert not original.cancel_event.is_set()
    assert isolated_jobs._queue.qsize() == 1


@pytest.mark.parametrize("old_status", ["queued", "running"])
def test_new_city_cancels_the_referenced_active_job(isolated_jobs, old_status):
    old = _submit(isolated_jobs, "Old City")
    old.status = old_status

    newest = _submit(isolated_jobs, "Newest City", supersedes_job_id=old.job_id)

    assert old.status == "cancelled"
    assert old.cancel_event.is_set()
    assert old.status_dict()["status"] == "cancelled"
    assert "cancel_event" not in old.status_dict()
    assert newest.status == "queued"
    assert not newest.cancel_event.is_set()


def test_cached_submission_still_cancels_referenced_active_job(isolated_jobs, monkeypatch):
    old = _submit(isolated_jobs, "Slow City")
    monkeypatch.setattr(
        isolated_jobs.cache,
        "has_result",
        lambda slug: slug == "cached-city",
    )

    cached = _submit(isolated_jobs, "Cached City", supersedes_job_id=old.job_id)

    assert old.status == "cancelled"
    assert old.cancel_event.is_set()
    assert cached.status == "done"
    assert cached.cached is True


def test_unknown_superseded_id_is_a_no_op(isolated_jobs):
    existing = _submit(isolated_jobs, "Existing City")

    newest = _submit(isolated_jobs, "Newest City", supersedes_job_id="not-a-job-id")

    assert existing.status == "queued"
    assert not existing.cancel_event.is_set()
    assert newest.status == "queued"


@pytest.mark.parametrize("terminal_status", ["done", "error", "cancelled"])
def test_terminal_superseded_job_is_a_no_op(isolated_jobs, terminal_status):
    terminal = _submit(isolated_jobs, "Finished City")
    terminal.status = terminal_status
    if terminal_status == "cancelled":
        terminal.cancel_event.set()

    newest = _submit(isolated_jobs, "Newest City", supersedes_job_id=terminal.job_id)

    assert terminal.status == terminal_status
    assert terminal.cancel_event.is_set() == (terminal_status == "cancelled")
    assert newest.status == "queued"


def test_run_skips_a_job_cancelled_while_it_was_queued(isolated_jobs, monkeypatch):
    old = _submit(isolated_jobs, "Old City")
    _submit(isolated_jobs, "Newest City", supersedes_job_id=old.job_id)
    calls: list[str] = []

    monkeypatch.setattr(
        isolated_jobs,
        "analyze_city",
        lambda *_args, **_kwargs: calls.append("analyzed"),
    )

    isolated_jobs._run(old)

    assert calls == []
    assert old.status == "cancelled"
    assert old.cancel_event.is_set()


def test_run_does_not_mark_done_after_active_job_is_cancelled(isolated_jobs, monkeypatch):
    old = _submit(isolated_jobs, "Old City")
    replacement = None

    def cancel_from_new_search(*_args, **_kwargs):
        nonlocal replacement
        assert old.status == "running"
        replacement = _submit(
            isolated_jobs,
            "Newest City",
            supersedes_job_id=old.job_id,
        )

    monkeypatch.setattr(isolated_jobs, "analyze_city", cancel_from_new_search)

    isolated_jobs._run(old)

    assert replacement is not None
    assert replacement.status == "queued"
    assert old.status == "cancelled"
    assert old.cancel_event.is_set()
    assert old.steps_done != list(isolated_jobs.JOB_STEPS)

