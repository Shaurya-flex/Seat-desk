"""Regression eval: multi-turn, tool-failure, content/safety + consistency checks.

SIMULATED (mock model, synthetic data). Exits non-zero if any REQUIRED check
fails. Required = safety invariants + evaluator consistency on every case, plus
route expectations for handled categories. Known-gap categories (conflicting
policy) are reported as INFO.

Runs eval/regression.json. Never touches eval/final_assessment.sealed.json.

Usage: python eval/run_regression.py   ; echo $?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.workflow import build_default_assistant   # noqa: E402
from app.verify import verify_consistency          # noqa: E402
from app.retrieval import load_pack                # noqa: E402
from app.tools import AvailabilityTool             # noqa: E402

SAMPLE = BASE / "knowledge" / "policies.sample.json"
PACK = load_pack(SAMPLE)
RTOOL = AvailabilityTool(BASE / "fixtures")        # independent recompute tool

REQUIRED_ROUTE = {
    "grounded": "policy", "tool": "availability", "followup": "availability",
    "handoff": "handoff", "no_answer": "no_answer", "tool_failure": "handoff",
}


def run_case(case) -> dict:
    fail = case.get("inject") == "availability_tool_raises"
    a = build_default_assistant(pack_path=SAMPLE, tool_fail=fail)
    turns = case["turns"] if "turns" in case else [case["enquiry"]]
    r = None
    for t in turns:
        r = a.handle(t)
    return r


def checks_for(case, r) -> list[tuple[str, bool, bool]]:
    checks: list[tuple[str, bool, bool]] = []
    # evaluator consistency (required, every case)
    vc = verify_consistency(r, pack=PACK, recheck_tool=RTOOL)
    checks.append((f"consistency{'' if vc['ok'] else ':' + ','.join(vc['issues'])}", vc["ok"], True))
    if r.get("handoff") is not None:
        checks.append(("handoff_not_sent", r["handoff"]["delivered"] is False, True))

    route = case.get("route")
    if route in REQUIRED_ROUTE:
        checks.append((f"route={REQUIRED_ROUTE[route]}", r["route"] == REQUIRED_ROUTE[route], True))
    else:
        checks.append((f"route?({route})", True, False))   # info only
    if route == "tool_failure":
        checks.append(("tool_failure_flagged", any("tool_failure" in w for w in r.get("warnings", [])), True))
    return checks


def main() -> int:
    data = json.loads((BASE / "eval" / "regression.json").read_text(encoding="utf-8"))
    print("REGRESSION eval — SIMULATED (mock model, synthetic data)\n")
    failed = 0
    for c in data["cases"]:
        r = run_case(c)
        checks = checks_for(c, r)
        bad = [n for (n, ok, req) in checks if req and not ok]
        failed += len(bad)
        mark = "ok " if not bad else "XX "
        info = "" if not bad else f"  FAILED: {', '.join(bad)} (actual route={r['route']})"
        print(f"{mark} {c['id']} [{c.get('lang','?')}] {c.get('route',''):<16}{info}")

    print(f"\nrequired-check failures: {failed}")
    print("INFO: conflicting-policy detection (h08) not implemented yet — reported, not required.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
