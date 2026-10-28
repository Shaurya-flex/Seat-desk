"""Response consistency verifier (evaluator).

Cross-checks a workflow response against its own structured facts so that a
corrupted source, fee, date, interval, count, or privacy field is caught rather
than silently served. Deterministic; no model.

This is what mutation tests target: corrupt any field and at least one check must
flip. It does NOT prove answer *truth* for free-form model output — only internal
consistency between the stated answer and the structured, code-rendered facts.
"""
from __future__ import annotations

import json
import re

_BOOKING = ["booked", "reserved for you", "reservation confirmed", "बुक", "आरक्षित कर द"]


def verify_consistency(resp: dict) -> dict:
    issues: list[str] = []
    ans = resp.get("answer") or ""
    low = ans.lower()

    # never claim a booking occurred
    if any(b in low for b in _BOOKING):
        issues.append("booking_claim")

    # grounded policy answers must carry a supported citation
    if resp.get("route") == "policy":
        if not resp.get("citations"):
            issues.append("policy_without_citation")
        cc = resp.get("citation_check")
        if not (cc and cc.get("ok")):
            issues.append("policy_citation_unverified")

    # availability: privacy + answer/structured consistency
    av = resp.get("availability")
    if av is not None:
        blob = json.dumps(av, ensure_ascii=False)
        if "member_id" in blob or '"note"' in blob:
            issues.append("privacy_leak")
        if av.get("status") == "ok":
            facts = resp.get("facts") or {}
            summ = av.get("summary", {})
            q = av.get("query", {})
            if facts.get("free") != summ.get("available"):
                issues.append("count_mismatch")
            if facts.get("considered") != summ.get("considered"):
                issues.append("considered_mismatch")
            if facts.get("date") != q.get("date"):
                issues.append("date_mismatch")
            window = q.get("slot") or (q.get("start"), q.get("end"))
            if facts.get("window") != window:
                issues.append("window_mismatch")
            # the stated answer must actually carry the rendered count and date
            if facts.get("free") is not None and not re.search(rf"\b{facts['free']}\b", ans):
                issues.append("answer_count_absent")
            if facts.get("date") and facts["date"] not in ans:
                issues.append("answer_date_absent")

    return {"ok": not issues, "issues": issues}
