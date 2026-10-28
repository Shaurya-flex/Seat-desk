"""Run the DEV eval cases through the workflow with content-level checks.

SIMULATED: MockModelAdapter + synthetic sample pack. This is not evidence of
Hindi quality or real Meta integration, and passing is NOT a claim of
hallucination-freedom. Exits non-zero if any REQUIRED check fails.

Usage: python eval/run_eval.py   ; echo $?
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.workflow import build_default_assistant  # noqa: E402
from app.verify import verify_consistency          # noqa: E402
from app.retrieval import load_pack                # noqa: E402
from app.tools import AvailabilityTool             # noqa: E402

PACK = load_pack(BASE / "knowledge" / "policies.sample.json")
RTOOL = AvailabilityTool(BASE / "fixtures")        # independent recompute tool

ROUTE_MAP = {"grounded": "policy", "tool": "availability",
             "handoff": "handoff", "no_answer": "no_answer", "injection": "injection"}
_BOOKING = ["booked", "reserved for you", "reservation confirmed"]


def check_case(case) -> tuple[str, list[tuple[str, bool, bool]]]:
    a = build_default_assistant(pack_path=BASE / "knowledge" / "policies.sample.json")
    r = a.handle(case["enquiry"])
    exp = ROUTE_MAP.get(case["route"], case["route"])
    checks: list[tuple[str, bool, bool]] = [("route", r["route"] == exp, True)]

    vc = verify_consistency(r, pack=PACK, recheck_tool=RTOOL)
    checks.append((f"consistency{'' if vc['ok'] else ':' + ','.join(vc['issues'])}", vc["ok"], True))

    ans = (r["answer"] or "").lower()
    checks.append(("no_booking_claim", not any(b in ans for b in _BOOKING), True))

    if case["route"] == "grounded":
        ok = bool(r["citation_check"]) and r["citation_check"]["ok"]
        checks.append(("citation_supported", ok, True))
        if "expected_source" in case:
            checks.append(("expected_source", case["expected_source"] in r["citations"], True))
    if case["route"] == "tool":
        av = r["availability"]
        checks.append(("availability_present", av is not None, True))
        checks.append(("sanitised_no_member", av is not None and "member_id" not in json.dumps(av), True))
    if case["route"] in ("handoff", "no_answer"):
        checks.append(("handoff_not_sent", r["handoff"] is not None and r["handoff"]["delivered"] is False, True))

    return r["route"], checks


def main() -> int:
    cases = json.loads((BASE / "eval" / "cases.json").read_text(encoding="utf-8"))["cases"]
    print("DEV eval — SIMULATED (mock model, synthetic data)\n")
    failed = 0
    for c in cases:
        if "turns" in c:
            continue
        actual, checks = check_case(c)
        bad = [n for (n, ok, req) in checks if req and not ok]
        failed += len(bad)
        mark = "ok " if not bad else "XX "
        detail = "" if not bad else f"  FAILED: {', '.join(bad)} (actual route={actual})"
        print(f"{mark} {c['id']} [{c['lang']}] {c['route']:<9}{detail}")

    print(f"\nrequired-check failures: {failed}")
    print("Note: in-question conflicting figures (e.g. '300 or 500?') are not yet detected "
          "(regression h08); answer nuance still needs the live model + human review.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
