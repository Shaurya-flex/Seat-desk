"""Acceptance checks for a LIVE run of the enquiry workflow.

Principle: the harness must not grade its own homework. The expected result is
re-derived here directly from the raw fixture JSON files with independent
interval logic (not via AvailabilityTool), and the response is additionally
re-verified by app.verify.verify_consistency, which recomputes availability
with a fresh tool and trusts nothing the producer attached.

A run is SUCCESS only when every substantive check passes: a completed request
with a wrong date, wrong slot interval, wrong counts, a wrong free-seat set,
an answer inconsistent with the deterministic result, a dishonestly truncated
seat list, a non-live transport, or a bad provider finish is NOT a success.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .verify import verify_consistency

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _minutes(hhmm: str) -> int:
    if not _HHMM.match(hhmm):
        raise ValueError(f"bad HH:MM: {hhmm!r}")
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def expected_from_fixtures(fixtures_dir: str | Path, date_str: str, slot_id: str) -> dict:
    """Independently derive the expected availability for date+slot from the raw
    fixture JSON, using its own overlap logic (half-open intervals [start,end))."""
    fx = Path(fixtures_dir)
    seats = json.loads((fx / "seats.json").read_text(encoding="utf-8"))["seats"]
    slots = json.loads((fx / "slots.json").read_text(encoding="utf-8"))["slots"]
    occ = json.loads((fx / "occupancy.json").read_text(encoding="utf-8"))

    slot = next(s for s in slots if s["slot_id"] == slot_id)
    q0, q1 = _minutes(slot["start"]), _minutes(slot["end"])

    cov = occ["coverage"]
    if not (cov["from"] <= date_str <= cov["to"]):
        raise ValueError(f"{date_str} outside fixture coverage {cov}")

    occupied: set[str] = set()
    for rec in occ["occupancy"]:
        if rec["date"] != date_str:
            continue
        r0, r1 = _minutes(rec["start"]), _minutes(rec["end"])
        if r0 < q1 and q0 < r1:                       # [r0,r1) overlaps [q0,q1)
            occupied.add(rec["seat_id"])

    all_ids = [s["seat_id"] for s in seats]
    free_ids = [i for i in all_ids if i not in occupied]
    labels = {s["seat_id"]: s["label"] for s in seats}
    return {
        "date": date_str, "slot": slot_id,
        "interval": (slot["start"], slot["end"]),
        "considered": len(all_ids),
        "available": len(free_ids),
        "free_ids": free_ids,
        "free_labels": [labels[i] for i in free_ids],
    }


def _display_honest(answer: str, free_labels: list[str]) -> bool:
    """The answer must either list every free seat or mark a partial list as
    examples ('e.g.' / 'जैसे'). No free seats -> nothing to list."""
    if not free_labels:
        return True
    listed = [lb for lb in free_labels if lb in answer]
    if len(listed) == len(free_labels):
        return True
    return ("e.g." in answer) or ("जैसे" in answer)


def evaluate_live_run(resp: dict | None, resolved_query: dict | None, meta: dict | None,
                      *, expected: dict, recheck_tool=None, pack=None,
                      error: dict | None = None,
                      require_live_transport: bool = True) -> dict:
    """Substantive pass/fail checks for one live run. Returns named checks plus
    workflow_successful = all of them."""
    resp = resp or {}
    resolved = resolved_query or {}
    meta = meta or {}
    usage = meta.get("usage") or {}
    av = resp.get("availability") or {}
    q = av.get("query") or {}
    summ = av.get("summary") or {}
    answer = resp.get("answer") or ""

    consistency = verify_consistency(resp, pack=pack, recheck_tool=recheck_tool)

    free_in_result = sorted(s["seat_id"] for s in av.get("seats", []) if s.get("available"))

    checks = {
        "request_completed": error is None,
        "lang_as_expected": resp.get("lang") == "hi",
        "route_availability": resp.get("route") == "availability",
        "date_correct": resolved.get("date") == expected["date"]
                        and q.get("date") == expected["date"],
        "slot_correct": resolved.get("slot") == expected["slot"],
        "interval_canonical": (q.get("start"), q.get("end")) == expected["interval"],
        "counts_match_fixture": summ.get("available") == expected["available"]
                                and summ.get("considered") == expected["considered"],
        "free_seats_match_fixture": free_in_result == sorted(expected["free_ids"]),
        "answer_states_count_and_date": bool(
            answer and expected["date"] in answer
            and re.search(rf"\b{expected['available']}\b", answer)),
        "seat_list_display_honest": _display_honest(answer, expected["free_labels"]),
        "answer_consistent_and_recomputed": consistency["ok"],
        "extraction_validated": bool(resp) and error is None,   # handle() only returns after validate_fields
        "model_not_simulated": resp.get("simulated") is False,
        "transport_live": (resp.get("transport") == "live-http") or not require_live_transport,
        "provider_finish_ok": meta.get("finish_reason") in ("stop", "tool_calls", None) and
                              (meta.get("finish_reason") == "stop" if require_live_transport else True),
        "usage_reported": (usage.get("prompt_tokens") is not None) if require_live_transport else True,
    }
    checks["workflow_successful"] = all(checks.values())
    return {"checks": checks, "consistency_issues": consistency["issues"]}
