"""Test the runnable Seat Desk flow: ask -> check interval -> supported facts
-> explicitly unsent handoff. Persistent transparency label every turn."""
from __future__ import annotations

from pathlib import Path

from app.seat_desk import run

SAMPLE = Path(__file__).resolve().parent.parent / "knowledge" / "policies.sample.json"


def test_seat_desk_full_flow():
    turns = ["Are any seats free?", "Tomorrow evening",
             "What is the monthly fee?", "Can you refund my fee?"]
    t = run(turns, pack_path=SAMPLE)

    assert [x["route"] for x in t] == ["clarify", "availability", "policy", "handoff"]

    # persistent transparency label every turn
    assert all(x["label"] == "Synthetic data · Mock model" for x in t)

    # turn 1 asks for missing info
    assert t[0]["reply"]

    # turn 2 checks the intended interval and returns a supported fact
    assert t[1]["availability_status"] == "ok"
    assert "2026-10-28" in t[1]["reply"]

    # turn 3 is grounded with a citation
    assert t[2]["citations"] == ["fees.monthly"]

    # turn 4 produces an explicitly UNSENT handoff summary
    assert t[3]["handoff_delivered"] is False
    assert "not sent" in (t[3]["handoff_text"] or "").lower()


def test_seat_desk_checks_intended_interval_not_silent_default():
    # A slot+time conflict must clarify, not silently pick one.
    t = run(["Are any seats free tomorrow evening 02:00-03:00?"], pack_path=SAMPLE)
    assert t[0]["route"] == "clarify"
