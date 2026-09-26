"""POST /chat (CR-018): Gemini with backend data tools and validated UI actions.

Gemini sees a compact city summary, the UI state and the last 10 messages; everything else
goes through data tools that run here. UI tools are declared to Gemini but never executed
here: each call is validated against this city's data and returned as an action for P3.
If Gemini is unconfigured, fails, or runs past the turn budget, the reply is a deterministic
summary from the briefing (fallback: true). The reply is never empty.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from typing import Literal

import h3
import pandas as pd
from google.genai import types
from pydantic import BaseModel, Field

from app import cache, gemini
from app.briefing import TITLE, build_briefing
from app.schemas import FEATURE_CSV_COLUMNS, RADIUS_KM, REFERENCE_LABEL

log = logging.getLogger(__name__)

MAX_MESSAGES = 10
MAX_TOOL_ROUNDS = 3
TURN_BUDGET_S = 15.0
MAX_ACTIONS = 5
PANELS = ("why", "comparison", "scenarios")


# --------------------------------------------------------------------------- request/response
class ChatMessage(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=4000)


class UIState(BaseModel):
    selected_hex: str | None = None
    open_panel: str | None = None
    crashes_on: bool = False


class ChatRequest(BaseModel):
    slug: str
    messages: list[ChatMessage] = Field(min_length=1)
    ui_state: UIState = UIState()


# --------------------------------------------------------------------------- city data
@dataclass
class City:
    slug: str
    briefing: dict
    result: dict
    crashes: dict | None
    features: pd.DataFrame
    hexes: dict
    scenarios: dict


_CITY_CACHE: dict[str, tuple[tuple, City]] = {}


def cached_slugs() -> list[str]:
    return sorted(p.parent.name for p in cache.CACHE_ROOT.glob("*/result.json"))


def load_city(slug: str) -> City:
    """Everything the tools need for one city, reloaded only when a source file changes."""
    d = cache.city_dir(slug)
    stamp = tuple((d / f).stat().st_mtime if (d / f).is_file() else 0
                  for f in ("result.json", "city.json", "crashes.json", "features.csv", "ai_summary.md"))
    hit = _CITY_CACHE.get(slug)
    if hit and hit[0] == stamp:
        return hit[1]
    result = cache.read_json(slug, "result.json")
    crashes = json.loads((d / "crashes.json").read_text(encoding="utf-8")) if (d / "crashes.json").is_file() else None
    city = City(
        slug=slug,
        briefing=build_briefing(slug),
        result=result,
        crashes=crashes,
        features=cache.read_features(slug).set_index("h3"),
        hexes={h["h3"]: h for h in result["hexes"]},
        scenarios={s["id"]: s for s in result["scenarios"]},
    )
    _CITY_CACHE[slug] = (stamp, city)
    return city


def _crashes_ok(c: City) -> bool:
    return bool(c.crashes and c.crashes.get("available"))


def _latlng(cell: str) -> tuple[float, float]:
    lat, lng = h3.cell_to_latlng(cell)
    return round(lat, 5), round(lng, 5)


def city_summary(c: City, include_crashes: bool = True) -> dict:
    """Compact grounding context (well under ~3k tokens)."""
    b = c.briefing
    k = b["key_numbers"]
    out = {
        "city": b["city"]["name"], "slug": c.slug, "reference": REFERENCE_LABEL,
        "pct_red": k["pct_red"], "n_hexes": k["n_hexes"], "bands": k["bands"],
        "driving_side": k["driving_side"], "novel_city": k["novel_city"],
        "osm_completeness": k["osm_completeness"], "climate": k["climate"],
        "biggest_differences": b["biggest_differences"],
        "scenarios": [{"id": s["id"], "title": s["title"], "priority": s["priority"],
                       "n_hexes": s["n_hexes"], "triggered_by": s["triggered_by"]} for s in b["scenarios"]],
        "top_unfamiliar": [{"h3": a["h3"], "shift_score": a["shift_score"],
                            "top_reason": {f: a["top_features"][0][f] for f in ("name", "value", "z")}
                            if a["top_features"] else None, "novel": a["novel"]}
                           for a in b["unfamiliar_areas"][:5]],
    }
    cc = b["crash_context"]
    if not include_crashes:
        out["crashes"] = "omitted: crash counts are never compared across cities"
    elif cc["available"]:
        out["crashes"] = {k2: cc[k2] for k2 in ("source", "note", "years", "preliminary_years", "total",
                                                "pct_pedestrian", "pct_cyclist", "pct_dark")}
    else:
        out["crashes"] = {"available": False, "reason": cc["reason"]}
    return out


# --------------------------------------------------------------------------- data tools
class ToolError(ValueError):
    """Bad tool arguments; the message goes back to Gemini so it can correct itself."""


def _hex_brief(c: City, h: dict, feature: str | None = None) -> dict:
    lat, lng = _latlng(h["h3"])
    out = {"h3": h["h3"], "lat": lat, "lng": lng, "shift_score": h["shift_score"], "band": h["band"],
           "top_features": [{k: f[k] for k in ("name", "value", "z")} for f in h["top_features"]],
           "novel": h["novel"]}
    if feature and feature in c.features.columns:
        out[feature] = round(float(c.features.loc[h["h3"], feature]), 3)
    if _crashes_ok(c):
        out["fatal_crashes"] = c.crashes["by_hex"].get(h["h3"], {}).get("count", 0)
    return out


def t_get_city_summary(c: City, slug: str | None = None) -> dict:
    if slug and slug != c.slug:
        if slug not in cached_slugs():
            raise ToolError(f"{slug!r} is not a cached city; cached: {', '.join(cached_slugs())}")
        return city_summary(load_city(slug), include_crashes=False)
    return city_summary(c)


def t_list_hexes(c: City, band: str | None = None, novel_only: bool = False, feature: str | None = None,
                 min_z: float = 2.0, limit: int = 10) -> dict:
    limit = max(1, min(int(limit), 20))
    if band and band not in ("red", "yellow", "green"):
        raise ToolError("band must be red, yellow or green")
    rows = list(c.hexes.values())
    if band:
        rows = [h for h in rows if h["band"] == band]
    if novel_only:
        rows = [h for h in rows if h["novel"]]
    if feature:
        known = set(FEATURE_CSV_COLUMNS) - {"h3", "area_km2", "road_km"}
        if feature not in known:
            raise ToolError(f"unknown feature {feature!r}; use one of {sorted(known)}")

        def z_of(h: dict) -> float | None:
            return next((f["z"] for f in h["top_features"] if f["name"] == feature), None)

        rows = [h for h in rows if feature in h["novel"] or (z_of(h) is not None and z_of(h) >= min_z)]
        rows.sort(key=lambda h: (-(z_of(h) if z_of(h) is not None else math.inf), -h["shift_score"], h["h3"]))
    else:
        rows.sort(key=lambda h: (-h["shift_score"], h["h3"]))
    return {"matching": len(rows), "returned": min(limit, len(rows)),
            "match_rule": ("feature in the hex's top-3 reasons with z >= min_z, or in its novel flags"
                           if feature else None),
            "hexes": [_hex_brief(c, h, feature) for h in rows[:limit]]}


def t_get_hex(c: City, h3_id: str) -> dict:
    h = c.hexes.get(h3_id)
    if h is None:
        raise ToolError(f"{h3_id!r} is not a hex of {c.slug}")
    out = _hex_brief(c, h)
    out["top_features"] = h["top_features"]
    out["raw_features"] = {k: (None if pd.isna(v) else round(float(v), 3))
                           for k, v in c.features.loc[h3_id].items()}
    out["in_scenarios"] = [s["id"] for s in c.scenarios.values() if h3_id in s["hex_ids"]]
    if _crashes_ok(c):
        out["fatal_crashes_pct_within_city"] = c.crashes["by_hex"].get(h3_id, {}).get("pct")
    return out


def t_get_scenario(c: City, scenario_id: str) -> dict:
    s = c.scenarios.get(scenario_id)
    if s is None:
        raise ToolError(f"{scenario_id!r} is not a scenario of {c.slug}; ids: {sorted(c.scenarios)}")
    hexes = [{"h3": x, "lat": _latlng(x)[0], "lng": _latlng(x)[1]} for x in s["hex_ids"][:30]]
    return {**{k: s[k] for k in ("id", "title", "priority", "scope", "description", "triggered_by")},
            "n_hexes": len(s["hex_ids"]), "hexes": hexes, "hexes_truncated": len(s["hex_ids"]) > 30}


def t_get_crash_summary(c: City, h3_id: str | None = None) -> dict:
    if not _crashes_ok(c):
        return {"available": False, "reason": (c.crashes or {}).get("reason", "no crash data")}
    if h3_id:
        if h3_id not in c.hexes and h3_id not in c.crashes["by_hex"]:
            raise ToolError(f"{h3_id!r} is not a hex of {c.slug}")
        pts = [p for p in c.crashes["points"] if p["h3"] == h3_id]
        stats = c.crashes["by_hex"].get(h3_id, {"count": 0, "pct": None})
        return {"h3": h3_id, "fatal_crashes": stats["count"], "pct_within_city": stats["pct"],
                "crashes": [{k: p[k] for k in ("year", "month", "hour", "fatalities", "pedestrian", "cyclist", "dark")}
                            for p in pts[:20]]}
    cc = c.briefing["crash_context"]
    by_year: dict[int, int] = {}
    for p in c.crashes["points"]:
        by_year[p["year"]] = by_year.get(p["year"], 0) + 1
    ped_hot = sorted(((cell, sum(p["pedestrian"] for p in c.crashes["points"] if p["h3"] == cell))
                      for cell in c.crashes["by_hex"]), key=lambda kv: (-kv[1], kv[0]))[:5]
    return {**{k: cc[k] for k in ("source", "note", "years", "preliminary_years", "total",
                                  "pct_pedestrian", "pct_cyclist", "pct_dark", "hotspots")},
            "by_year": by_year,
            "pedestrian_hotspots": [{"h3": cell, "lat": _latlng(cell)[0], "lng": _latlng(cell)[1],
                                     "pedestrian_fatal_crashes": n} for cell, n in ped_hot if n]}


def t_compare_feature(c: City, name: str) -> dict:
    row = next((r for r in c.result["summary"]["feature_comparison"] if r["name"] == name), None)
    if row is None:
        raise ToolError(f"{name!r} is not in this city's feature comparison")
    col = pd.to_numeric(c.features[name], errors="coerce") if name in c.features.columns else None
    return {"name": name, "city_median": row["target"], "reference_median": row["reference"],
            "ratio": round(row["target"] / row["reference"], 2) if row["reference"] else None,
            "city_p95": round(float(col.quantile(0.95)), 3) if col is not None else None,
            "hexes_where_top_reason_z_over_2": sum(any(f["name"] == name and f["z"] > 2 for f in h["top_features"])
                                                   for h in c.hexes.values())}


DATA_TOOLS = {
    "get_city_summary": t_get_city_summary, "list_hexes": t_list_hexes, "get_hex": t_get_hex,
    "get_scenario": t_get_scenario, "get_crash_summary": t_get_crash_summary,
    "compare_feature": t_compare_feature,
}


# --------------------------------------------------------------------------- UI actions
def validate_action(c: City, name: str, args: dict) -> dict:
    """The action dict for a UI tool call, or ToolError. Nothing unvalidated reaches P3."""
    if name == "select_hex":
        if args.get("h3") not in c.hexes:
            raise ToolError(f"{args.get('h3')!r} is not a hex of {c.slug}")
        return {"type": "select_hex", "h3": args["h3"]}
    if name == "highlight_scenario":
        if args.get("id") not in c.scenarios:
            raise ToolError(f"{args.get('id')!r} is not a scenario of {c.slug}")
        return {"type": "highlight_scenario", "id": args["id"]}
    if name == "open_panel":
        if args.get("panel") not in PANELS:
            raise ToolError(f"panel must be one of {PANELS}")
        return {"type": "open_panel", "panel": args["panel"]}
    if name == "toggle_crashes":
        if not isinstance(args.get("on"), bool):
            raise ToolError("on must be true or false")
        if args["on"] and not _crashes_ok(c):
            raise ToolError("no crash data for this city (FARS covers US crashes only)")
        return {"type": "toggle_crashes", "on": args["on"]}
    if name == "fly_to":
        try:
            lat, lng, zoom = float(args["lat"]), float(args["lng"]), float(args["zoom"])
        except (KeyError, TypeError, ValueError):
            raise ToolError("fly_to needs numeric lat, lng and zoom") from None
        center = c.result["summary"]["center"]
        if h3.great_circle_distance((center["lat"], center["lng"]), (lat, lng), unit="km") > RADIUS_KM + 2:
            raise ToolError("fly_to target is outside this city's area")
        if zoom != int(zoom) or not 3 <= zoom <= 20:
            raise ToolError("zoom must be an integer from 3 to 20")
        return {"type": "fly_to", "lat": round(lat, 6), "lng": round(lng, 6), "zoom": int(zoom)}
    if name == "open_city":
        if args.get("slug") not in cached_slugs():
            raise ToolError(f"{args.get('slug')!r} is not a cached city")
        return {"type": "open_city", "slug": args["slug"]}
    if name == "download_briefing":
        if args.get("format") not in ("md", "json"):
            raise ToolError("format must be md or json")
        return {"type": "download_briefing", "format": args["format"]}
    raise ToolError(f"unknown UI tool {name!r}")


UI_TOOLS = {"select_hex", "highlight_scenario", "open_panel", "toggle_crashes", "fly_to", "open_city",
            "download_briefing"}


# --------------------------------------------------------------------------- declarations
def _decl(name: str, description: str, props: dict | None = None, required: list[str] | None = None):
    schema = {"type": "object", "properties": props or {}}
    if required:
        schema["required"] = required
    return types.FunctionDeclaration(name=name, description=description, parameters_json_schema=schema)


DECLARATIONS = [
    _decl("get_city_summary", "Key numbers, scenarios and top unfamiliar hexes. Pass slug for another cached "
          "city (for comparisons; its crash counts are omitted).", {"slug": {"type": "string"}}),
    _decl("list_hexes", "Hexes sorted by shift_score (or by the feature's z when feature is given). "
          "feature matches a hex's top-3 reasons with z >= min_z or its novel flags (e.g. "
          "movable_bridge_count for drawbridges).",
          {"band": {"type": "string", "enum": ["red", "yellow", "green"]}, "novel_only": {"type": "boolean"},
           "feature": {"type": "string"}, "min_z": {"type": "number"},
           "limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
    _decl("get_hex", "Everything about one hex: score, reasons, raw features, crashes, scenarios.",
          {"h3_id": {"type": "string"}}, ["h3_id"]),
    _decl("get_scenario", "One scenario card with its hexes.", {"scenario_id": {"type": "string"}}, ["scenario_id"]),
    _decl("get_crash_summary", "NHTSA FARS fatal crashes in this city (US only), or in one hex if h3_id is given. "
          "Includes pedestrian hotspots.", {"h3_id": {"type": "string"}}),
    _decl("compare_feature", "This city's median vs the reference median for one feature.",
          {"name": {"type": "string"}}, ["name"]),
    _decl("select_hex", "UI: select a hex on the map (opens its details).", {"h3": {"type": "string"}}, ["h3"]),
    _decl("highlight_scenario", "UI: highlight a scenario card and its hexes.", {"id": {"type": "string"}}, ["id"]),
    _decl("open_panel", "UI: open a side panel.", {"panel": {"type": "string", "enum": list(PANELS)}}, ["panel"]),
    _decl("toggle_crashes", "UI: show or hide the fatal-crash layer.", {"on": {"type": "boolean"}}, ["on"]),
    _decl("fly_to", "UI: move the map.", {"lat": {"type": "number"}, "lng": {"type": "number"},
                                          "zoom": {"type": "integer"}}, ["lat", "lng", "zoom"]),
    _decl("open_city", "UI: open another cached city.", {"slug": {"type": "string"}}, ["slug"]),
    _decl("download_briefing", "UI: download this city's briefing file.",
          {"format": {"type": "string", "enum": ["md", "json"]}}, ["format"]),
]
TOOLS = [types.Tool(function_declarations=DECLARATIONS)]


def system_prompt(c: City, ui_state: UIState) -> str:
    return (
        "You are CityShift's assistant inside a map app. CityShift uses public data to rank where a city's "
        f"driving environment differs from {REFERENCE_LABEL} (Phoenix, San Francisco, Los Angeles, Austin, "
        f"Atlanta) and turns those differences into candidate test scenarios. Its output is a \"{TITLE}\".\n"
        "Rules:\n"
        "- Answer only from the city context below and tool results. Quote numbers exactly as given; do not "
        "compute new ones. If something is not there, say \"That's not in our data.\"\n"
        "- Red means unfamiliar to the car compared with the reference cities, not dangerous. shift_score is "
        "how unusual a hex is versus the reference hexes (0-100).\n"
        "- Crash data is NHTSA FARS: fatal crashes only, US cities only, 2024 preliminary. Never compare crash "
        "counts across cities.\n"
        "- Never claim knowledge of Waymo's internal systems. CityShift does not train Waymo's models; it "
        "proposes candidate test scenarios from public data. Say so plainly if asked.\n"
        "- When the user asks to show, select, open, zoom, switch city or download, call the UI tools, then say "
        "in one short sentence what you did. Only use hex ids, scenario ids and slugs from the context or tool "
        "results.\n"
        "- Be concise: 2-5 sentences of plain text, no tables, no markdown headings.\n"
        f"City context (JSON): {json.dumps(city_summary(c), separators=(',', ':'))}\n"
        f"UI state: {ui_state.model_dump_json()}\n"
        f"Cached cities: {', '.join(cached_slugs())}"
    )


# --------------------------------------------------------------------------- fallback
NOT_TRAINING = ("No. CityShift does not train Waymo's models or describe Waymo's internal systems; it proposes "
                "candidate test scenarios from public data.")


def fallback_reply(c: City, question: str = "") -> str:
    b = c.briefing
    k = b["key_numbers"]
    parts = [NOT_TRAINING] if re.search(r"\btrain", question, re.I) else []
    parts += [f"{b['city']['name']}: {k['pct_red']:g}% of {k['n_hexes']} hexes are red (unfamiliar compared "
             f"with {REFERENCE_LABEL}). Driving side: {k['driving_side']}."]
    if k["novel_city"]:
        parts.append(f"City-level novel flags: {', '.join(k['novel_city'])}.")
    top = b["scenarios"][:3]
    if top:
        parts.append("Top scenarios: " + "; ".join(f"{s['rank']}. {s['title']} (priority {s['priority']:g})"
                                                   for s in top) + ".")
    parts.append("The assistant is unavailable right now, so this comes straight from the city briefing.")
    return " ".join(parts)


def _fallback(c: City, why: str, question: str = "") -> dict:
    log.warning("chat fallback for %s: %s", c.slug, why)
    return {"reply": fallback_reply(c, question), "actions": [], "model": "fallback", "fallback": True}


# --------------------------------------------------------------------------- turn
def respond(req: ChatRequest) -> dict:
    """One chat turn. Caller has already checked the slug is cached."""
    c = load_city(req.slug)
    question = req.messages[-1].text
    if req.messages[-1].role != "user":
        return _fallback(c, "last message is not from the user", question)
    if not gemini.configured():
        return _fallback(c, "Gemini not configured", question)
    deadline = time.monotonic() + TURN_BUDGET_S
    system = system_prompt(c, req.ui_state)
    contents = [types.Content(role=m.role, parts=[types.Part(text=m.text)]) for m in req.messages[-MAX_MESSAGES:]]
    actions: list[dict] = []
    text = ""
    try:
        for round_no in range(MAX_TOOL_ROUNDS + 1):
            remaining_ms = (deadline - time.monotonic()) * 1000
            if remaining_ms < 1000:
                return _fallback(c, "turn budget exhausted", question)
            resp = gemini.generate(contents, system=system, tools=TOOLS,
                                   force_text=round_no == MAX_TOOL_ROUNDS, timeout_ms=remaining_ms)
            calls = resp.function_calls or []
            if not calls:
                text = (resp.text or "").strip()
                break
            contents.append(resp.candidates[0].content)
            parts = []
            for call in calls:
                args = dict(call.args or {})
                try:
                    if call.name in UI_TOOLS:
                        action = validate_action(c, call.name, args)
                        if action not in actions and len(actions) < MAX_ACTIONS:
                            actions.append(action)
                        payload = {"result": "done; the app will show this"}
                    elif call.name in DATA_TOOLS:
                        payload = {"result": DATA_TOOLS[call.name](c, **args)}
                    else:
                        payload = {"error": f"unknown tool {call.name!r}"}
                except ToolError as exc:
                    payload = {"error": str(exc)}
                except TypeError as exc:
                    payload = {"error": f"bad arguments: {exc}"}
                parts.append(types.Part.from_function_response(name=call.name, response=payload))
            contents.append(types.Content(role="user", parts=parts))
    except Exception as exc:  # noqa: BLE001 - any Gemini failure becomes the deterministic reply
        return _fallback(c, f"{type(exc).__name__}: {str(exc)[:200]}", question)
    if not text:
        if not actions:
            return _fallback(c, "empty reply", question)
        text = "Done."
    return {"reply": text, "actions": actions, "model": gemini.model_name(), "fallback": False}


# --------------------------------------------------------------------------- grounding check
_H3_RE = re.compile(r"\b[0-9a-f]{15}\b")
_NUM_RE = re.compile(r"(?<![\w.])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.])-?\d+(?:\.\d+)?(?![\w])")


def numbers_in(text: str) -> list[str]:
    """Numbers a reader would see in text, ignoring h3 ids and hyphenated slugs."""
    text = _H3_RE.sub(" ", text)
    text = re.sub(r"\b[a-z]+(?:-[a-z0-9]+)+\b", " ", text)
    return [m.group(0).replace(",", "") for m in _NUM_RE.finditer(text)]


def data_numbers(*objs) -> list[float]:
    """Every number in the given JSON-like objects, including numbers inside strings."""
    out: list[float] = []

    def walk(o):
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            out.append(float(o))
        elif isinstance(o, str):
            out.extend(float(n) for n in numbers_in(o))
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
    for obj in objs:
        walk(obj)
    return out


def ungrounded(text: str, allowed: list[float]) -> list[str]:
    """Numbers in text that no data number rounds to (as given, or as a percentage of a 0-1 share)."""
    pool = set()
    for v in allowed:
        for x in (v, v * 100):
            for d in range(0, 4):
                pool.add(round(x, d))
    bad = []
    for n in numbers_in(text):
        value = float(n)
        if value.is_integer() and 0 <= value <= 20:
            continue  # counts and ordinals ("top 3", "5 cities")
        if value in pool or round(value, 3) in pool:
            continue
        bad.append(n)
    return bad
