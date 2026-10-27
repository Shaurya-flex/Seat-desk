"""Seat Desk — one runnable enquiry flow.

Demonstrates the full read-only path end to end: it asks for missing
information, checks the intended interval, returns supported facts, and
produces an explicitly UNSENT handoff summary when needed. A persistent
"Synthetic data / Mock model" label is shown every turn.

Run: python -m app.seat_desk
"""
from __future__ import annotations

from pathlib import Path

from .workflow import build_default_assistant, Assistant


def run(turns: list[str], *, assistant: Assistant | None = None,
        pack_path: str | Path | None = None) -> list[dict]:
    """Drive a scripted conversation; return a transcript (for tests/demo)."""
    a = assistant or build_default_assistant(pack_path=pack_path)
    transcript: list[dict] = []
    for user in turns:
        r = a.handle(user)
        transcript.append({
            "user": user,
            "label": r["transparency"]["label"],
            "route": r["route"],
            "reply": r["answer"] or r["clarification"] or "",
            "citations": r["citations"],
            "availability_status": (r["availability"] or {}).get("status"),
            "handoff_delivered": (r["handoff"] or {}).get("delivered"),
            "handoff_text": (r["handoff"] or {}).get("text"),
        })
    return transcript


def _print(line: dict) -> None:
    print(f"[{line['label']}]")
    print(f"  You:   {line['user']}")
    print(f"  Desk:  {line['reply']}  ({line['route']}"
          + (f", cites {line['citations']}" if line["citations"] else "")
          + (f", availability={line['availability_status']}" if line["availability_status"] else "")
          + ")")
    if line["handoff_text"]:
        sent = "NOT sent" if line["handoff_delivered"] is False else "sent"
        print(f"  Handoff summary ({sent}, copy to a human):")
        for ln in line["handoff_text"].splitlines():
            print(f"    | {ln}")
    print()


if __name__ == "__main__":  # pragma: no cover
    demo = [
        "Are any seats free?",          # missing info -> asks
        "Tomorrow evening",             # supplies it -> checks interval, supported facts
        "What is the monthly fee?",     # grounded fact with citation
        "Can you refund my fee?",       # consequential -> unsent handoff summary
    ]
    print("=== Seat Desk (demo; synthetic data, mock model) ===\n")
    for line in run(demo):
        _print(line)
