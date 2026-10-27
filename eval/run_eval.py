"""Run the dev eval cases through the workflow and report ACTUAL routing.

SIMULATED: this uses the MockModelAdapter and the synthetic sample pack. It
checks ROUTING only (grounded/tool/handoff/no_answer/injection), not answer
correctness, not Hindi quality, and it is NOT evidence of real Meta
integration or of any guaranteed absence of hallucination. Content correctness
(e.g. payment-method vs monthly-fee, or correcting a wrong figure) still needs
the live model and human review.

Usage: python eval/run_eval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.workflow import build_default_assistant  # noqa: E402

# expected (case file) route -> workflow route
ROUTE_MAP = {"grounded": "policy", "tool": "availability",
             "handoff": "handoff", "no_answer": "no_answer", "injection": "injection"}


def main() -> int:
    cases = json.loads((BASE / "eval" / "cases.json").read_text(encoding="utf-8"))["cases"]
    assistant = build_default_assistant(pack_path=BASE / "knowledge" / "policies.sample.json")

    print("SIMULATED mock run (routing only; not answer/quality/integration evidence)\n")
    passed = 0
    for c in cases:
        if "turns" in c:            # multi-turn cases live in heldout.json
            continue
        r = assistant.handle(c["enquiry"])
        expected = ROUTE_MAP.get(c["route"], c["route"])
        ok = r["route"] == expected
        passed += ok
        mark = "ok " if ok else "XX "
        print(f"{mark} {c['id']} [{c['lang']}] expected={c['route']:<9} actual={r['route']}")

    total = sum(1 for c in cases if "turns" not in c)
    print(f"\nrouting match: {passed}/{total}  (mock adapter)")
    print("Note: routing match is not answer correctness. d05/d13 need the live model to"
          " fully satisfy (payment-method detail; correcting a stated wrong figure).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
