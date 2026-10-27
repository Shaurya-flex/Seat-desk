"""Human-handoff summary.

Produces a copyable text block for a human to act on. It does NOT send
anything: delivery is not implemented, so `delivered` is always False and
`channel` is 'none'. Do not describe a handoff as sent.
"""
from __future__ import annotations


def build_handoff_summary(enquiry: str, lang: str, reason: str, pack: dict,
                          extra: str | None = None) -> dict:
    by_id = pack.get("_by_id", {})
    contact_item = by_id.get("contact.handoff")
    if contact_item and contact_item.get("status") == "confirmed":
        contact = contact_item.get(f"answer_{lang}") or contact_item.get("answer_en") or ""
    else:
        contact = "(handoff contact not configured — operator to follow up)"

    lines = [
        "HUMAN HANDOFF — draft summary (not sent)",
        f"Enquiry: {enquiry}",
        f"Language: {lang}",
        f"Reason for handoff: {reason}",
    ]
    if extra:
        lines.append(f"Details: {extra}")
    lines.append(f"Suggested contact: {contact}")
    text = "\n".join(lines)

    return {
        "channel": "none",
        "delivered": False,          # delivery is not implemented
        "reason": reason,
        "text": text,
    }
