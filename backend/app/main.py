"""CityShift HTTP API (contract 4.1). Run: uvicorn app.main:app --port 8000"""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app import cache, jobs
from app.pipeline import write_crashes
from app.schemas import AnalyzeRequest, AnalyzeResponse, CitiesResponse, JobStatus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="CityShift")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    job = jobs.submit(req.name, req.lat, req.lng, req.country_code)
    return AnalyzeResponse(job_id=job.job_id, slug=job.slug, status=job.status, cached=job.cached)


@app.get("/jobs/{job_id}", response_model=JobStatus)
def job_status(job_id: str) -> JobStatus:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    return JobStatus(**job.status_dict())


@app.get("/cities", response_model=CitiesResponse)
def cities() -> CitiesResponse:
    return CitiesResponse(cities=cache.list_cities())


@app.get("/cities/{slug}")
def city_result(slug: str) -> Response:
    """Serves cache/{slug}/result.json as-is; it was validated against CityResult when written."""
    if not _SLUG_RE.match(slug) or not cache.has_result(slug):
        raise HTTPException(status_code=404, detail="not cached")
    return Response(content=(cache.city_dir(slug) / "result.json").read_bytes(), media_type="application/json")


@app.get("/cities/{slug}/crashes")
def city_crashes(slug: str) -> Response:
    """cache/{slug}/crashes.json (CR-017). 404 only for an unknown slug; built on demand if absent."""
    if not _SLUG_RE.match(slug) or not (cache.city_dir(slug) / "city.json").is_file():
        raise HTTPException(status_code=404, detail="not cached")
    path = cache.city_dir(slug) / "crashes.json"
    if not path.is_file():
        city = cache.read_json(slug, "city.json")
        write_crashes(slug, city["lat"], city["lng"], city.get("country_code"))
    return Response(content=path.read_bytes(), media_type="application/json")
