"""Write cache/{slug}/briefing.md + briefing.json for every city with a result.json (CR-018).

    python scripts/build_briefings.py                # deterministic briefings only, instant
    python scripts/build_briefings.py --ai-summary   # also generate missing ai_summary.md (Gemini)
    python scripts/build_briefings.py --ai-summary --force-ai   # regenerate every AI summary
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import cache, gemini  # noqa: E402
from app.briefing import write_briefing  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai-summary", action="store_true", help="generate ai_summary.md where missing")
    ap.add_argument("--force-ai", action="store_true", help="with --ai-summary: regenerate existing summaries")
    args = ap.parse_args()
    if args.ai_summary and not gemini.configured():
        print("error: --ai-summary needs GEMINI_API_KEY in backend/.env", file=sys.stderr)
        return 2
    from app import ai_summary

    failed = 0
    for result in sorted(cache.CACHE_ROOT.glob("*/result.json")):
        slug = result.parent.name
        t = time.perf_counter()
        write_briefing(slug)
        note = f"briefing {1000 * (time.perf_counter() - t):.0f} ms"
        if args.ai_summary and (args.force_ai or not (result.parent / "ai_summary.md").is_file()):
            t = time.perf_counter()
            try:
                saved = ai_summary.write(slug)
                note += f", AI summary {'saved' if saved else 'NOT saved (ungrounded numbers)'} ({time.perf_counter() - t:.1f}s)"
                failed += not saved
            except Exception as exc:  # noqa: BLE001
                failed += 1
                note += f", AI summary FAILED: {str(exc)[:160]}"
        print(f"{slug:24s} {note}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
