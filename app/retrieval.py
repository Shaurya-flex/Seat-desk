"""Approved-policy retrieval and citation/support checking.

Retrieval is deterministic keyword matching over the approved pack. Only items
with status == 'confirmed' may support an answer; 'unknown' items never do.
"""
from __future__ import annotations

import json
from pathlib import Path

# topic -> trigger keywords (English + Hindi + common Hinglish)
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "hours":      ["hour", "open", "close", "timing", "time", "खुल", "समय", "बजे"],
    "fees":       ["fee", "fees", "cost", "price", "charge", "payment", "शुल्क", "फीस", "पैसे", "जमा"],
    "admission":  ["document", "documents", "join", "admission", "enrol", "enroll", "दस्तावेज", "जुड़", "दाखिल"],
    "slots":      ["slot", "shift", "स्लॉट", "पाली"],
    "seats":      ["seat", "seats", "सीट", "कुर्सी"],
    "membership": ["membership", "renew", "validity", "सदस्यता", "नवीकरण"],
    "facilities": ["wifi", "wi-fi", "facility", "facilities", "locker", "लॉकर", "सुविधा"],
    "rules":      ["rule", "rules", "conduct", "नियम"],
}


def load_pack(path: str | Path) -> dict:
    """Load a knowledge pack and index items by id."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["_by_id"] = {it["id"]: it for it in data.get("items", [])}
    return data


def topics_for(enquiry: str) -> list[str]:
    low = enquiry.lower()
    return [t for t, kws in TOPIC_KEYWORDS.items() if any(k.lower() in low for k in kws)]


def retrieve(enquiry: str, pack: dict, k: int = 3) -> list[dict]:
    """Return candidate policy items (any status) whose topic matches the enquiry."""
    topics = set(topics_for(enquiry))
    hits = [it for it in pack.get("items", []) if it.get("topic") in topics]
    return hits[:k]


def confirmed_items(items: list[dict], lang: str) -> list[dict]:
    """Items that are confirmed and have an answer in the requested language."""
    key = f"answer_{lang}"
    out = []
    for it in items:
        if it.get("status") == "confirmed" and (it.get(key) or it.get("answer_en") or it.get("answer_hi")):
            out.append(it)
    return out


def validate_citation(answer_text: str, cited_ids: list[str], pack: dict, lang: str) -> dict:
    """Check cited ids exist, are confirmed, AND that the cited text supports the answer.

    'Support' here is deterministic string containment, suitable for the mock
    adapter which answers by copying approved text. A real model would need a
    semantic support check (e.g. NLI); this mock result is NOT evidence of that.
    """
    by_id = pack.get("_by_id", {})
    reasons: list[str] = []
    unsupported: list[str] = []
    if not cited_ids:
        return {"ok": False, "reasons": ["no citation provided"], "unsupported": []}

    for cid in cited_ids:
        item = by_id.get(cid)
        if item is None:
            reasons.append(f"cited id '{cid}' not in pack")
            continue
        if item.get("status") != "confirmed":
            reasons.append(f"cited id '{cid}' is not confirmed (status={item.get('status')})")
            continue
        src = (item.get(f"answer_{lang}") or item.get("answer_en") or item.get("answer_hi") or "")
        if src and src.strip() and src.strip() in answer_text:
            continue
        unsupported.append(cid)
        reasons.append(f"cited id '{cid}' does not support the answer text")

    ok = not reasons and not unsupported
    return {"ok": ok, "reasons": reasons, "unsupported": unsupported}
