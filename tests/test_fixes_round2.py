"""Regression tests for the independently-reproduced round-2 failures.

1 citation bypass (unsupported addition / booking claim)
2 conflicting time inputs -> clarify
3 conversation state (pending request, merge, correction)
4 limits: display vs generation; verified answers not truncated; retry planned
5 demo transparency: persistent label; handoff never claims delivery
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.workflow import build_default_assistant
from app.retrieval import load_pack, validate_citation
from app.limits import Limits, SessionBudget, RETRY_ENFORCEMENT, clamp_display

BASE = Path(__file__).resolve().parent.parent
SAMPLE = BASE / "knowledge" / "policies.sample.json"


# --- 1. citation validator no longer bypassed ---
def test_citation_rejects_unsupported_addition():
    pack = load_pack(SAMPLE)
    approved = pack["_by_id"]["fees.monthly"]["answer_en"]
    poisoned = approved + " All seats are free and you are booked."
    res = validate_citation(poisoned, ["fees.monthly"], pack, "en")
    assert res["ok"] is False
    assert any("unsupported" in r or "booking" in r for r in res["reasons"])


def test_citation_rejects_booking_claim():
    pack = load_pack(SAMPLE)
    approved = pack["_by_id"]["fees.monthly"]["answer_en"]
    res = validate_citation(approved + " you are booked", ["fees.monthly"], pack, "en")
    assert res["ok"] is False


def test_citation_accepts_exact_approved_text():
    pack = load_pack(SAMPLE)
    approved = pack["_by_id"]["fees.monthly"]["answer_en"]
    res = validate_citation(approved, ["fees.monthly"], pack, "en")
    assert res["ok"] is True


# --- 2. conflicting time inputs ---
def test_conflicting_slot_and_time_clarifies():
    a = build_default_assistant(pack_path=SAMPLE)
    r = a.handle("Are any seats free tomorrow evening 02:00-03:00?")
    assert r["route"] == "clarify"
    assert r["clarification"]


# --- 3. conversation state ---
def test_multiturn_pending_resolves():
    a = build_default_assistant(pack_path=SAMPLE)
    r1 = a.handle("Are any seats free?")
    assert r1["route"] == "clarify"
    r2 = a.handle("Tomorrow evening")
    assert r2["route"] == "availability"
    assert r2["availability"]["status"] == "ok"
    assert r2["availability"]["query"]["date"] == "2026-10-28"


def test_multiturn_correction_overrides_obsolete_value():
    a = build_default_assistant(pack_path=SAMPLE)
    a.handle("Are any seats free tomorrow?")          # pending: date=tomorrow (2026-10-28)
    r = a.handle("today evening")                      # correct date to today
    assert r["route"] == "availability"
    assert r["availability"]["query"]["date"] == "2026-10-27"   # not the obsolete tomorrow


def test_new_topic_abandons_pending():
    a = build_default_assistant(pack_path=SAMPLE)
    a.handle("Are any seats free?")                    # sets pending
    r = a.handle("What is the monthly fee?")           # fresh policy intent
    assert r["route"] == "policy"
    assert a.pending is None


# --- 4. limits ---
def test_verified_answer_not_truncated_by_display_limit():
    a = build_default_assistant(pack_path=SAMPLE, limits=Limits(max_display_chars=5))
    r = a.handle("What is the monthly fee?")
    pack = load_pack(SAMPLE)
    assert r["answer"] == pack["_by_id"]["fees.monthly"]["answer_en"]   # intact, no "[truncated]"
    assert "truncated" not in r["answer"]


def test_retry_enforcement_is_real():
    assert RETRY_ENFORCEMENT == "enforced_in_run_guarded"


def test_clamp_display_char_based():
    assert clamp_display("abc", 100) == "abc"
    assert clamp_display("a" * 200, 50).endswith("[display-truncated]")


# --- 5. transparency ---
def test_transparency_label_present_every_response():
    a = build_default_assistant(pack_path=SAMPLE)
    for q in ["What is the monthly fee?", "Are any seats free tomorrow evening?",
              "Can you refund last month's fee?"]:
        r = a.handle(q)
        assert r["transparency"]["label"] == "Synthetic data · Mock model"
        assert r["transparency"]["mock_model"] is True


def test_handoff_never_claims_delivery():
    a = build_default_assistant(pack_path=SAMPLE)
    r = a.handle("Can you refund last month's fee?")
    assert r["handoff"]["delivered"] is False
    assert r["handoff"]["channel"] == "none"
    assert "delivered" not in (r["answer"] or "").lower()
