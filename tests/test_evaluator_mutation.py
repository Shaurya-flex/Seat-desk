"""Mutation tests for the evaluator.

Take a correct response, corrupt each field (source, fee, date, interval/window,
count, privacy), and assert the evaluator catches it. If any mutation passed, the
evaluator would be rubber-stamping false answers.
"""
from __future__ import annotations

import copy
from pathlib import Path

from app.workflow import build_default_assistant
from app.verify import verify_consistency
from app.retrieval import load_pack, validate_citation

SAMPLE = Path(__file__).resolve().parent.parent / "knowledge" / "policies.sample.json"


def _good_availability():
    a = build_default_assistant(pack_path=SAMPLE)
    r = a.handle("Are any seats free tomorrow evening?")
    assert verify_consistency(r)["ok"], "baseline must be consistent"
    return r


def _good_policy():
    a = build_default_assistant(pack_path=SAMPLE)
    r = a.handle("What is the monthly fee?")
    assert verify_consistency(r)["ok"]
    return r


def test_mutate_count_is_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["summary"]["available"] = 99
    assert "count_mismatch" in verify_consistency(r)["issues"]


def test_mutate_date_is_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["query"]["date"] = "2020-01-01"
    assert "date_mismatch" in verify_consistency(r)["issues"]


def test_mutate_interval_window_is_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["query"]["slot"] = "morning"   # was evening
    assert "window_mismatch" in verify_consistency(r)["issues"]


def test_mutate_privacy_is_caught():
    r = copy.deepcopy(_good_availability())
    r["availability"]["seats"][0]["member_id"] = "M001"
    assert "privacy_leak" in verify_consistency(r)["issues"]


def test_mutate_answer_count_is_caught():
    r = copy.deepcopy(_good_availability())
    r["answer"] = "No seats information available."
    assert "answer_count_absent" in verify_consistency(r)["issues"]


def test_mutate_source_citation_is_caught():
    pack = load_pack(SAMPLE)
    good = _good_policy()
    # corrupt the cited source id
    res = validate_citation(good["answer"], ["not.a.real.id"], pack, "en")
    assert res["ok"] is False


def test_mutate_fee_text_is_caught():
    pack = load_pack(SAMPLE)
    good = _good_policy()
    # append an unsupported fabricated fee to the approved answer
    poisoned = good["answer"] + " The fee is actually 999 rupees."
    res = validate_citation(poisoned, good["citations"], pack, "en")
    assert res["ok"] is False


def test_policy_without_citation_is_caught():
    r = copy.deepcopy(_good_policy())
    r["citations"] = []
    assert "policy_without_citation" in verify_consistency(r)["issues"]
