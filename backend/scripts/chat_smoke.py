"""Smoke-test POST /chat logic (CR-018) for New York, Miami and London.

    python scripts/chat_smoke.py            # table + full replies
    python scripts/chat_smoke.py --pause 4  # seconds between turns (free-tier rate limits)

Per turn: latency, fallback flag, actions (each re-validated), and any number in the reply that
does not appear in the city's data. Target: under 3 s per turn.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cache, chat, gemini  # noqa: E402

CITIES = ["new-york-ny-usa", "miami-fl-usa", "london-uk"]
PROMPTS = [
    "Summarize this city",
    "Why is the reddest area red?",
    "Show me the drawbridges",
    "Where do pedestrians die most?",
    "Open the scenarios",
    "Download the briefing",
    "Compare with San Francisco",
    "Does this train Waymo's models?",
]


def allowed_numbers(slug: str) -> list[float]:
    """Every number the assistant could legitimately quote for this city (and SF, for the comparison)."""
    out = []
    for s in (slug, "san-francisco-ca-usa"):
        c = chat.load_city(s)
        out += chat.data_numbers(c.result, c.briefing, cache.read_json(s, "city.json"), c.crashes or {})
        out += [float(v) for v in c.features.select_dtypes("number").to_numpy().ravel() if v == v]
        out += chat.data_numbers(chat.t_get_crash_summary(c)) if s == slug else []
    return out


def says_no(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in ("does not", "doesn't", "do not", "don't", "not train", "no,", "no.", "not used to train"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pause", type=float, default=0.0)
    args = ap.parse_args()
    print(f"model: {gemini.model_name() or 'not configured'}\n")
    rows, details, problems = [], [], 0
    for slug in CITIES:
        c = chat.load_city(slug)
        allowed = allowed_numbers(slug)
        for prompt in PROMPTS:
            req = chat.ChatRequest(slug=slug, messages=[{"role": "user", "text": prompt}])
            t = time.perf_counter()
            out = chat.respond(req)
            ms = (time.perf_counter() - t) * 1000
            bad_actions = []
            for a in out["actions"]:
                try:
                    chat.validate_action(c, a["type"], {k: v for k, v in a.items() if k != "type"})
                except chat.ToolError as exc:
                    bad_actions.append(f"{a['type']}: {exc}")
            bad_numbers = chat.ungrounded(out["reply"], allowed)
            flags = []
            if not out["reply"].strip():
                flags.append("EMPTY")
            if bad_actions:
                flags.append("BAD ACTION")
            if bad_numbers:
                flags.append("UNGROUNDED " + ",".join(bad_numbers))
            if prompt.startswith("Does this train") and not says_no(out["reply"]):
                flags.append("DID NOT SAY NO")
            if ms > 3000:
                flags.append("SLOW")
            problems += bool(set(flags) - {"SLOW"})
            acts = ", ".join(f"{a['type']}" + (f"({next(iter(v for k, v in a.items() if k != 'type'))})"
                                               if len(a) > 1 else "") for a in out["actions"]) or "-"
            rows.append(f"| {slug.split('-')[0]} | {prompt} | {ms:,.0f} | {out['fallback']} | {acts} | {' / '.join(flags) or 'ok'} |")
            details.append({"city": slug, "prompt": prompt, "ms": round(ms), **out})
            if args.pause:
                time.sleep(args.pause)
    print("| City | Prompt | ms | Fallback | Actions | Checks |")
    print("|---|---|---:|---|---|---|")
    print("\n".join(rows))
    lat = sorted(d["ms"] for d in details if not d["fallback"])
    if lat:
        print(f"\nlatency (non-fallback): median {lat[len(lat) // 2]:,} ms, max {lat[-1]:,} ms; "
              f"fallbacks {sum(d['fallback'] for d in details)} of {len(details)}")
    print("\n--- replies ---")
    for d in details:
        print(f"\n[{d['city']}] {d['prompt']}  ({d['ms']} ms, fallback={d['fallback']})\n{d['reply']}\n"
              f"actions: {json.dumps(d['actions'])}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
