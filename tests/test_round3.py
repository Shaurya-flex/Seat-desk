"""Round-3 regressions: multiple alternatives, completed-turn corrections,
seat follow-ups, explicit-interval retention; and the retry/timeout guard."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.workflow import build_default_assistant
from app.limits import run_guarded, TimeoutExceeded

SAMPLE = Path(__file__).resolve().parent.parent / "knowledge" / "policies.sample.json"


def _a():
    return build_default_assistant(pack_path=SAMPLE)


# --- multiple alternatives -> clarify (no silent pick) ---
def test_multiple_slot_alternatives_clarifies():
    r = _a().handle("Are any seats free tomorrow morning or evening?")
    assert r["route"] == "clarify"


def test_multiple_date_alternatives_clarifies():
    r = _a().handle("Are seats free today or tomorrow evening?")
    assert r["route"] == "clarify"


# --- completed-turn correction retains date, changes slot ---
def test_completed_turn_correction():
    a = _a()
    a.handle("Are any seats free tomorrow evening?")
    r = a.handle("actually morning")
    assert r["route"] == "availability"
    assert r["availability"]["query"]["date"] == "2026-10-28"
    assert r["availability"]["query"]["slot"] == "morning"


# --- seat follow-up reuses prior date/slot ---
def test_seat_followup_reuses_context():
    a = _a()
    a.handle("Are any seats free tomorrow evening?")
    r = a.handle("what about seat S02?")
    assert r["route"] == "availability"
    assert r["availability"]["query"]["seat_id"] == "S02"
    assert r["availability"]["query"]["date"] == "2026-10-28"
    assert r["availability"]["query"]["slot"] == "evening"


# --- explicit interval retained through a follow-up ---
def test_explicit_interval_retained():
    a = _a()
    r1 = a.handle("Is a seat free tomorrow 14:00-15:00?")
    assert r1["availability"]["query"]["start"] == "14:00"
    assert r1["availability"]["query"]["end"] == "15:00"
    r2 = a.handle("and S03?")
    assert r2["availability"]["query"]["seat_id"] == "S03"
    assert r2["availability"]["query"]["start"] == "14:00"
    assert r2["availability"]["query"]["end"] == "15:00"


# --- retry/timeout guard ---
def test_run_guarded_returns():
    assert run_guarded(lambda: 5, retries=1, timeout_s=1.0) == 5


def test_run_guarded_retries_then_succeeds():
    calls = {"n": 0}
    def f():
        calls["n"] += 1
        if calls["n"] < 2:
            raise ValueError("transient")
        return "ok"
    assert run_guarded(f, retries=2, timeout_s=1.0) == "ok"
    assert calls["n"] == 2


def test_run_guarded_exhausts_retries():
    def boom():
        raise ValueError("boom")
    with pytest.raises(ValueError):
        run_guarded(boom, retries=1, timeout_s=1.0)


def test_run_guarded_timeout():
    with pytest.raises(TimeoutExceeded):
        run_guarded(lambda: time.sleep(2), retries=0, timeout_s=0.2)
