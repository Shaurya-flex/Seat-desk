"""Response consistency verifier (evaluator).

Design principle: the evaluator trusts NOTHING the producer attached to the
response. It re-derives the truth itself:

* policy answers are re-validated against the authoritative pack (the cached
  `citation_check` is ignored), so a fabricated fee + nonexistent citation fails
  even if the response claims it passed.
* availability answers are re-checked against an INDEPENDENT recomputation from
  the stated query (fresh tool), plus slot-boundary and answer/fact consistency,
  so a tampered interval/count/seat/date is caught.

Deterministic; no model. It proves internal + recomputed consistency, not the
truth of free-form model prose.
"""
from __future__ import annotations

import json
import re

from .retrieval import validate_citation

_BOOKING = ["booked", "reserved for you", "reservation confirmed", "बुक", "आरक्षित कर द"]


def _query_to_request(q: dict) -> dict:
    req: dict = {}
    if q.get("date"):
        req["date"] = q["date"]
    if q.get("seat_id"):
        req["seat_id"] = q["seat_id"]
    if q.get("slot"):
        req["slot"] = q["slot"]
    elif q.get("start") and q.get("end"):
        req["start"], req["end"] = q["start"], q["end"]
    return req


def _seat_map(av: dict) -> dict:
    return {s["seat_id"]: s["available"] for s in av.get("seats", [])}


def verify_consistency(resp: dict, pack: dict | None = None, recheck_tool=None) -> dict:
    issues: list[str] = []
    ans = resp.get("answer") or ""
    low = ans.lower()

    if any(b in low for b in _BOOKING):
        issues.append("booking_claim")

    # --- policy: re-validate against the pack; never trust cached citation_check ---
    if resp.get("route") == "policy":
        cites = resp.get("citations") or []
        if not cites:
            issues.append("policy_without_citation")
        elif pack is None:
            issues.append("policy_unverifiable_without_pack")
        else:
            res = validate_citation(ans, cites, pack, resp.get("lang", "en"))
            if not res["ok"]:
                issues.append("policy_citation_invalid")

    # --- availability ---
    av = resp.get("availability")
    if av is not None:
        blob = json.dumps(av, ensure_ascii=False)
        if "member_id" in blob or '"note"' in blob:
            issues.append("privacy_leak")

        q = av.get("query", {})
        summ = av.get("summary", {})
        facts = resp.get("facts") or {}

        if av.get("status") == "ok":
            if facts.get("free") != summ.get("available"):
                issues.append("count_mismatch")
            if facts.get("considered") != summ.get("considered"):
                issues.append("considered_mismatch")
            if facts.get("date") != q.get("date"):
                issues.append("date_mismatch")
            window = q.get("slot") or (q.get("start"), q.get("end"))
            if facts.get("window") != window:
                issues.append("window_mismatch")
            if facts.get("free") is not None and not re.search(rf"\b{facts['free']}\b", ans):
                issues.append("answer_count_absent")
            if facts.get("date") and facts["date"] not in ans:
                issues.append("answer_date_absent")

        if recheck_tool is not None:
            slots = getattr(recheck_tool, "slots", {}) or {}
            # slot boundary consistency: an echoed slot's start/end must equal the slot's bounds
            if q.get("slot") and q.get("start") and q.get("end"):
                sb = slots.get(q["slot"])
                if sb and (sb[0].strftime("%H:%M"), sb[1].strftime("%H:%M")) != (q["start"], q["end"]):
                    issues.append("slot_boundary_mismatch")
            # independent recomputation from the stated query
            recomputed = recheck_tool.get_availability(_query_to_request(q))
            if recomputed.get("status") != av.get("status"):
                issues.append("recompute_status_mismatch")
            if recomputed.get("summary") != summ:
                issues.append("recompute_summary_mismatch")
            if _seat_map(recomputed) != _seat_map(av):
                issues.append("recompute_seats_mismatch")

    return {"ok": not issues, "issues": issues}
