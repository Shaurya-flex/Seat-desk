"""Round-3 regressions: multiple alternatives, completed-turn corrections,
seat follow-ups, explicit-interval retention; and the retry/timeout guard."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.workflow import build_default_assistant
from app.limits import run_guarded, TimeoutExceeded, OutstandingTracker, LimitExceeded

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


# --- anaphoric follow-up keeps the explicit interval and applies the seat filter ---
def test_anaphor_followup_preserves_interval_and_seat():
    a = _a()
    r1 = a.handle("Are seats free tomorrow 06:00-07:00?")
    assert r1["availability"]["query"]["start"] == "06:00"
    r2 = a.handle("Is seat S01 free in it?")
    assert r2["route"] == "availability"
    assert r2["availability"]["query"]["seat_id"] == "S01"
    assert r2["availability"]["query"]["start"] == "06:00"
    assert r2["availability"]["query"]["end"] == "07:00"
    assert r2["availability"]["query"]["date"] == "2026-10-28"


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
    import threading
    ev = threading.Event()
    try:
        with pytest.raises(TimeoutExceeded):
            run_guarded(lambda: ev.wait(5), retries=0, timeout_s=0.2)
    finally:
        ev.set()   # release the worker so it does not linger


def test_run_guarded_timeout_returns_promptly():
    """Regression for the ThreadPoolExecutor-wait bug: the guard must return in
    ~timeout_s, not wait for the slow worker to finish."""
    import threading
    ev = threading.Event()
    start = time.monotonic()
    try:
        with pytest.raises(TimeoutExceeded):
            run_guarded(lambda: ev.wait(5), retries=0, timeout_s=0.2)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"guard blocked on worker ({elapsed:.2f}s)"
    finally:
        ev.set()


def test_run_guarded_classified_retry_no_retry_on_4xx():
    calls = {"n": 0}
    class AuthError(Exception):
        pass
    def f():
        calls["n"] += 1
        raise AuthError("401")
    with pytest.raises(AuthError):
        run_guarded(f, retries=3, timeout_s=1.0, is_retryable=lambda e: not isinstance(e, AuthError))
    assert calls["n"] == 1   # not retried


def test_run_guarded_overall_deadline():
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        time.sleep(0.05)
        raise ValueError("transient")
    with pytest.raises((ValueError, TimeoutExceeded)):
        run_guarded(flaky, retries=100, timeout_s=1.0, deadline_s=0.2)
    assert calls["n"] < 100   # overall deadline cut the retry loop short


# --- bounded outstanding requests: no overlapping retry while one may still run ---
def test_outstanding_requests_bounded():
    import threading
    ev = threading.Event()
    tr = OutstandingTracker(max_outstanding=1)
    try:
        with pytest.raises(LimitExceeded):
            # 1st attempt times out holding the only slot; the retry's acquire fails
            run_guarded(lambda: ev.wait(5), retries=1, timeout_s=0.2, tracker=tr)
    finally:
        ev.set()
    # the abandoned worker releases its slot once it actually finishes
    for _ in range(100):
        if tr.outstanding == 0:
            break
        time.sleep(0.02)
    assert tr.outstanding == 0


def test_outstanding_allows_within_cap():
    tr = OutstandingTracker(max_outstanding=2)
    assert run_guarded(lambda: 7, retries=0, timeout_s=1.0, tracker=tr) == 7
    for _ in range(50):
        if tr.outstanding == 0:
            break
        time.sleep(0.01)
    assert tr.outstanding == 0
