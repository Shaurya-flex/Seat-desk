"""Approved-policy retrieval, deterministic rendering, and citation/support checks.

Retrieval is deterministic keyword matching over the approved pack. Only items
with status == 'confirmed' may support an answer; 'unknown' items never do.

Answers for facts are rendered deterministically from approved text (not free
model prose). The citation validator then rejects ANY text that is not
accounted for by the cited approved sources, and rejects booking claims.
"""
from __future__ import annotations

import json
import re
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

# Phrases that assert a booking/reservation happened. An answer must never claim this.
BOOKING_CLAIMS = ["you are booked", "booked", "reserved for you", "reservation confirmed",
                  "बुक", "आरक्षित कर द"]


def load_pack(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["_by_id"] = {it["id"]: it for it in data.get("items", [])}
    return data


def topics_for(enquiry: str) -> list[str]:
    low = enquiry.lower()
    return [t for t, kws in TOPIC_KEYWORDS.items() if any(k.lower() in low for k in kws)]


def retrieve(enquiry: str, pack: dict, k: int = 3) -> list[dict]:
    """Rank items by item-level 'match' keyword hits (weight 2) + topic hit (1).

    Returns the best-scoring items first, so a payment-methods question beats the
    monthly-fee item that merely shares the 'fees' topic.
    """
    low = enquiry.lower()
    topics = set(topics_for(enquiry))
    scored: list[tuple[int, int, dict]] = []
    for idx, it in enumerate(pack.get("items", [])):
        score = sum(2 for kw in it.get("match", []) if kw.lower() in low)
        if it.get("topic") in topics:
            score += 1
        if score > 0:
            scored.append((score, idx, it))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [it for _, _, it in scored[:k]]


def confirmed_items(items: list[dict], lang: str) -> list[dict]:
    out = []
    for it in items:
        if it.get("status") == "confirmed" and (
            it.get(f"answer_{lang}") or it.get("answer_en") or it.get("answer_hi")
        ):
            out.append(it)
    return out


def _source_text(item: dict, lang: str) -> str:
    return (item.get(f"answer_{lang}") or item.get("answer_en") or item.get("answer_hi") or "").strip()


def render_policy(items: list[dict], lang: str) -> tuple[str, list[str]]:
    """Deterministic renderer: answer == concatenation of approved texts only."""
    parts, cites = [], []
    for it in items:
        txt = _source_text(it, lang)
        if txt:
            parts.append(txt)
            cites.append(it["id"])
    return (" ".join(parts), cites)


def validate_citation(answer_text: str, cited_ids: list[str], pack: dict, lang: str) -> dict:
    """Reject unsupported additions and booking claims.

    An answer passes only if (a) every cited id exists and is confirmed,
    (b) removing each cited approved span from the answer leaves nothing
    substantive (no added, unsupported text), and (c) it makes no booking claim.
    """
    by_id = pack.get("_by_id", {})
    reasons: list[str] = []
    unsupported: list[str] = []
    if not cited_ids:
        return {"ok": False, "reasons": ["no citation provided"], "unsupported": [], "residual": answer_text}

    residual = answer_text
    for cid in cited_ids:
        item = by_id.get(cid)
        if item is None:
            reasons.append(f"cited id '{cid}' not in pack")
            continue
        if item.get("status") != "confirmed":
            reasons.append(f"cited id '{cid}' is not confirmed (status={item.get('status')})")
            continue
        src = _source_text(item, lang)
        if src and src in residual:
            residual = residual.replace(src, "", 1)      # account for this supported span
        else:
            unsupported.append(cid)
            reasons.append(f"cited id '{cid}' does not support the answer text")

    # Anything left after removing all supported spans is an unsupported addition.
    leftover = re.sub(r"[\s।.,;:—\-|/()]+", "", residual)
    if leftover:
        reasons.append(f"unsupported added text: {residual.strip()[:80]!r}")

    low = answer_text.lower()
    if any(b in low for b in BOOKING_CLAIMS):
        reasons.append("answer claims a booking/reservation occurred")

    ok = not reasons and not unsupported
    return {"ok": ok, "reasons": reasons, "unsupported": unsupported, "residual": residual.strip()}
