"""Per-job log capture for GET /jobs/{id} (CR-019). No network, no worker thread, no cache writes."""
from __future__ import annotations

import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import joblog, jobs
from app.data import osm
from app.schemas import JOB_STEPS, JobStatus


@pytest.fixture(autouse=True)
def app_info_logs(caplog: pytest.LogCaptureFixture):
    joblog.install()
    caplog.set_level(logging.INFO, logger="app")


def _messages(job_log: joblog.JobLog) -> list[str]:
    return [line["message"] for line in job_log.lines()]


def test_threads_started_in_context_log_to_their_job_only():
    mine, other = joblog.JobLog(), joblog.JobLog()
    token = joblog.bind(mine)
    try:
        logging.getLogger("app.pipeline").info("from the job thread")
        t = threading.Thread(target=joblog.in_context(
            lambda: logging.getLogger("app.data.osm").warning("from a download thread")))
        t.start()
        t.join()
        plain = threading.Thread(target=lambda: logging.getLogger("app.data.osm").info("unrelated thread"))
        plain.start()
        plain.join()
    finally:
        joblog.unbind(token)
    logging.getLogger("app.pipeline").info("after the job")

    assert _messages(mine) == ["from the job thread", "from a download thread"]
    assert [line["level"] for line in mine.lines()] == ["INFO", "WARNING"]
    assert [line["source"] for line in mine.lines()] == ["pipeline", "data.osm"]
    assert _messages(other) == []


def test_exception_tracebacks_are_kept():
    job_log = joblog.JobLog()
    token = joblog.bind(job_log)
    try:
        try:
            raise ValueError("bad hex")
        except ValueError:
            logging.getLogger("app.jobs").exception("job failed")
    finally:
        joblog.unbind(token)
    (line,) = job_log.lines()
    assert line["level"] == "ERROR"
    assert "job failed" in line["message"] and "ValueError: bad hex" in line["message"]


def test_finished_job_reports_logs_and_step_times(monkeypatch: pytest.MonkeyPatch):
    def fake_analyze(name, lat, lng, country_code, progress, cancel_event):
        for step in JOB_STEPS:
            progress(step)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(joblog.in_context(logging.getLogger("app.pipeline").info), f"{step} work").result()

    monkeypatch.setattr(jobs, "analyze_city", fake_analyze)
    job = jobs.JobState("abc123", "test-town", "Test Town", 1.0, 2.0, "US")
    jobs._run(job)

    status = JobStatus(**job.status_dict())
    assert status.status == "done"
    assert set(status.step_elapsed_s) == set(JOB_STEPS)
    assert status.elapsed_s is not None and status.elapsed_s >= 0
    messages = [line.message for line in status.logs]
    for step in JOB_STEPS:
        assert f"{step} work" in messages
        assert any(m.startswith(f"job abc123: step {step} took") for m in messages)
    assert [line.seq for line in status.logs] == sorted(line.seq for line in status.logs)


def test_failed_job_keeps_the_failing_step_and_its_time(monkeypatch: pytest.MonkeyPatch):
    def fake_analyze(name, lat, lng, country_code, progress, cancel_event):
        progress("roads")
        progress("infrastructure")
        raise RuntimeError("infrastructure failed: Overpass down")

    monkeypatch.setattr(jobs, "analyze_city", fake_analyze)
    job = jobs.JobState("def456", "test-town", "Test Town", 1.0, 2.0, "US")
    jobs._run(job)

    status = job.status_dict()
    assert status["status"] == "error" and status["step"] == "infrastructure"
    assert set(status["step_elapsed_s"]) == {"roads", "infrastructure"}
    assert any(line["level"] == "ERROR" and "Overpass down" in line["message"] for line in status["logs"])


def test_osmnx_network_messages_are_forwarded_with_the_download_name():
    job_log = joblog.JobLog()
    token = joblog.bind(job_log)
    try:
        def fn():
            osm.ox_utils.log("Pausing 12 second(s) before making HTTP POST request to 'overpass-api.de'")
            osm.ox_utils.log("Post https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D...")
            osm.ox_utils.log("Created graph with 10 nodes and 20 edges")
            osm.ox_utils.log("'overpass-api.de' responded 429 Too Many Requests: we'll retry in 55 secs",
                             level=logging.WARNING)
            return "graph"

        assert osm._with_fallback("roads", fn) == ("graph", osm.DEFAULT_OVERPASS_URL)
    finally:
        joblog.unbind(token)

    forwarded = [m for m in _messages(job_log) if " via " in m]
    assert forwarded == [
        f"roads via {osm.DEFAULT_OVERPASS_URL}: Pausing 12 second(s) before making HTTP POST request to "
        "'overpass-api.de'",
        f"roads via {osm.DEFAULT_OVERPASS_URL}: 'overpass-api.de' responded 429 Too Many Requests: "
        "we'll retry in 55 secs",
    ]
