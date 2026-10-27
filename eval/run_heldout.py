"""Extended held-out eval: multi-turn, tool-failure, and content/safety checks.

SIMULATED (mock model, synthetic data). Exits non-zero if any REQUIRED check
fails. Required = safety invariants on every case + route expectations for the
categories we claim to handle. Known-gap categories (overlap nuance,
conflicting-policy detection) are reported as INFO, not required.

This runs eval/heldout.json. It never touches eval/final_assessment.sealed.json.

Usage: python eval/run_heldout.py   ; echo $?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.workflow import build_default_assistant  # noqa: E402

SAMPLE = BASE / "knowledge" / "policies.sample.json"
_BOOKING = ["booked", "reserved for you", "reservation confirmed"]

# category/route -> required expected workflow route
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
    blob = json.dumps(r.get("availability") or {})
    # safety invariants (required, every case)
    if r.get("availability") is not None:
        checks.append(("sanitised_no_member", "member_id" not in blob and "note" not in blob, True))
    if r.get("handoff") is not None:
        checks.append(("handoff_not_sent", r["handoff"]["delivered"] is False, True))
    ans = (r.get("answer") or "").lower()
    checks.append(("no_booking_claim", not any(b in ans for b in _BOOKING), True))

    # route expectation (required for handled categories, else informational)
    route = case.get("route")
    if route in REQUIRED_ROUTE:
        checks.append((f"route={REQUIRED_ROUTE[route]}", r["route"] == REQUIRED_ROUTE[route], True))
    else:
        checks.append((f"route?({route})", True, False))  # info only
    if route == "tool_failure":
        checks.append(("tool_failure_flagged", any("tool_failure" in w for w in r.get("warnings", [])), True))
    return checks


def main() -> int:
    data = json.loads((BASE / "eval" / "heldout.json").read_text(encoding="utf-8"))
    print("HELD-OUT eval — SIMULATED (mock model, synthetic data)\n")
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
