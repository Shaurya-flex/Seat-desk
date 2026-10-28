"""Mutation tests for the evaluator — including the ACTUAL runner/checker path.

Take a correct response, corrupt a field, and assert the evaluator catches it.
The evaluator must NOT trust the response's own attestations: it re-validates
policy citations against the pack and independently recomputes availability.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from app.workflow import build_default_assistant
from app.verify import verify_consistency
from app.retrieval import load_pack, validate_citation
from app.tools import AvailabilityTool

BASE = Path(__file__).resolve().parent.parent
SAMPLE = BASE / "knowledge" / "policies.sample.json"
PACK = load_pack(SAMPLE)
TOOL = AvailabilityTool(BASE / "fixtures")

# load the real regression runner module to test its checker, not just helpers
_spec = importlib.util.spec_from_file_location("run_regression", BASE / "eval" / "run_regression.py")
run_regression = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_regression)


def V(r):
    return verify_consistency(r, pack=PACK, recheck_tool=TOOL)


def _good_availability():
    r = build_default_assistant(pack_path=SAMPLE).handle("Are any seats free tomorrow evening?")
    assert V(r)["ok"], f"baseline not consistent: {V(r)}"
    return r


def _good_policy():
    r = build_default_assistant(pack_path=SAMPLE).handle("What is the monthly fee?")
    assert V(r)["ok"]
    return r


# --- failure 1: cached self-attestation must not be trusted ---
def test_cached_citation_attestation_not_trusted():
    r = copy.deepcopy(_good_policy())
    r["answer"] = "The fee is 999 rupees."
    r["citations"] = ["nonexistent.id"]
    r["citation_check"] = {"ok": True}        # stale attestation says it's fine
    assert "policy_citation_invalid" in V(r)["issues"]


def test_fabricated_addition_to_real_citation_caught():
    r = copy.deepcopy(_good_policy())
    r["answer"] = r["answer"] + " Also all seats are free and you are booked."
    r["citation_check"] = {"ok": True}
    assert not V(r)["ok"]


# --- failure 2: tampered interval / count / seats via independent recompute ---
def test_tampered_slot_interval_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["query"]["start"] = "02:00"
    r["availability"]["query"]["end"] = "03:00"
    assert "slot_boundary_mismatch" in V(r)["issues"]


def test_tampered_count_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["summary"]["available"] = 99
    iss = V(r)["issues"]
    assert "count_mismatch" in iss or "recompute_summary_mismatch" in iss


def test_tampered_seat_availability_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["seats"][0]["available"] = not r["availability"]["seats"][0]["available"]
    assert "recompute_seats_mismatch" in V(r)["issues"]


def test_tampered_date_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["query"]["date"] = "2020-01-01"
    iss = V(r)["issues"]
    assert "date_mismatch" in iss or "recompute_status_mismatch" in iss or "recompute_summary_mismatch" in iss


def test_privacy_leak_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["seats"][0]["member_id"] = "M001"
    assert "privacy_leak" in V(r)["issues"]


def test_answer_count_tamper_caught():
    r = copy.deepcopy(_good_availability())
    r["answer"] = "No seats information available."
    assert "answer_count_absent" in V(r)["issues"]


# --- direct citation checks (source/fee) ---
def test_source_citation_mutation_caught():
    good = _good_policy()
    assert validate_citation(good["answer"], ["not.a.real.id"], PACK, "en")["ok"] is False


def test_fee_text_mutation_caught():
    good = _good_policy()
    poisoned = good["answer"] + " The fee is actually 999 rupees."
    assert validate_citation(poisoned, good["citations"], PACK, "en")["ok"] is False


# --- the ACTUAL runner checker path flags mutations ---
def test_runner_checker_flags_interval_tamper():
    r = copy.deepcopy(_good_availability())
    r["availability"]["query"]["start"] = "02:00"
    r["availability"]["query"]["end"] = "03:00"
    checks = run_regression.checks_for({"id": "x", "route": "tool"}, r)
    bad = [n for (n, ok, req) in checks if req and not ok]
    assert bad, "runner checker must flag the tampered interval"


def test_runner_checker_flags_policy_citation_tamper():
    r = copy.deepcopy(_good_policy())
    r["answer"] = "The fee is 999 rupees."
    r["citations"] = ["nonexistent.id"]
    r["citation_check"] = {"ok": True}
    checks = run_regression.checks_for({"id": "y", "route": "grounded"}, r)
    bad = [n for (n, ok, req) in checks if req and not ok]
    assert bad, "runner checker must flag the fabricated policy answer"
