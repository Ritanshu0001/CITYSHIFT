"""AI summary for the briefing (CR-018): one Gemini call per city, grounded on briefing.json only.

Saved to cache/{slug}/ai_summary.md with a "<!-- model: ... -->" first line. A summary whose
numbers are not all in the briefing is retried once, then not saved.
"""
from __future__ import annotations

import json
import logging
import threading

from google.genai import types

from app import cache, gemini
from app.briefing import build_briefing, write_briefing
from app.chat import data_numbers, ungrounded

log = logging.getLogger(__name__)

PROMPT = (
    "Write a 5-7 sentence plain-text summary of this City readiness briefing (a candidate test plan built "
    "from public data) for an autonomous-vehicle test planner. Use ONLY facts and numbers that appear in "
    "the JSON below, quoted exactly; do not compute new numbers. Cover how unfamiliar the city is overall "
    "compared with Waymo's established cities, the biggest infrastructure differences, the top two or three "
    "scenarios, and any city-level flags. Red means unfamiliar, not dangerous. If crash data is present, "
    "mention it only as within-city context. Do not claim this trains Waymo's models or describes Waymo's "
    "internal systems. No markdown, no lists.\n\nBRIEFING JSON:\n"
)
STRICTER = ("\n\nYour previous draft used numbers that are not in the JSON ({bad}). Rewrite it using only "
            "numbers copied from the JSON.")

_running: set[str] = set()
_lock = threading.Lock()


def generate(slug: str) -> tuple[str | None, list[str]]:
    """(summary text or None, ungrounded numbers of the last draft). Writes nothing."""
    briefing = build_briefing(slug)
    briefing.pop("ai_summary", None)
    grounding = json.dumps(briefing, separators=(",", ":"))
    allowed = data_numbers(briefing)
    prompt, bad = PROMPT + grounding, []
    for _ in range(2):
        resp = gemini.generate([types.Content(role="user", parts=[types.Part(text=prompt)])],
                               system="You summarise data faithfully and never invent numbers.")
        text = (resp.text or "").strip()
        bad = ungrounded(text, allowed)
        if text and not bad:
            return text, []
        prompt = PROMPT + grounding + STRICTER.format(bad=", ".join(bad) or "none")
    return None, bad


def write(slug: str) -> bool:
    """Generate, save ai_summary.md, rebuild the briefing files. True if a summary was saved."""
    text, bad = generate(slug)
    if text is None:
        log.warning("AI summary for %s not saved: ungrounded numbers %s", slug, bad)
        return False
    path = cache.city_dir(slug) / "ai_summary.md"
    path.write_text(f"<!-- model: {gemini.model_name()} -->\n{text}\n", encoding="utf-8")
    write_briefing(slug)
    return True


def ensure_async(slug: str) -> None:
    """First request for a city without a summary: generate it in the background, once."""
    if not gemini.configured() or (cache.city_dir(slug) / "ai_summary.md").is_file():
        return
    with _lock:
        if slug in _running:
            return
        _running.add(slug)

    def run() -> None:
        try:
            write(slug)
        except Exception as exc:  # noqa: BLE001 - the briefing works without it
            log.warning("AI summary for %s failed: %s", slug, exc)
        finally:
            with _lock:
                _running.discard(slug)

    threading.Thread(target=run, name=f"ai-summary-{slug}", daemon=True).start()
