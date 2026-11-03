"""Offline tests for the local desk interface logic (app/server.py DeskState).
No network, no key, no spend: live paths must fail closed, mock paths must
carry the full honest display payload."""
import wave

import pytest

from app.server import DeskState


@pytest.fixture()
def desk():
    return DeskState(key="")          # no key: live must refuse


def test_mock_availability_flow_payload(desk):
    r = desk.enquire("2026-10-28 को दोपहर में कौन सी सीटें खाली हैं?", "mock")
    assert "error" not in r
    assert r["route"] == "availability" and r["lang"] == "hi"
    assert r["availability"]["summary"]["available"] == 6
    assert r["resolved_query"]["date"] == "2026-10-28"
    assert r["simulated"] is True and r["transport"] == "builtin"
    # tool trace is labelled distinctly from citations
    assert r["citations"] == []
    assert "deterministic" in r["models"]["facts"]
    assert "no Meta call" in r["models"]["extraction"]


def test_mock_clarify_then_policy_citation(desk):
    r1 = desk.enquire("Are any seats free?", "mock")
    assert r1["route"] == "clarify" and r1["clarification"]
    r2 = desk.enquire("What is the monthly fee?", "mock")
    assert r2["route"] == "policy" and r2["citations"]


def test_mock_handoff_is_unsent(desk):
    r = desk.enquire("Can you refund my fee?", "mock")
    assert r["handoff"] and r["handoff"].get("delivered") is False


def test_live_without_key_fails_closed(desk):
    r = desk.enquire("hello", "live")
    assert r["error"]["type"] in ("RuntimeError",)
    assert "MODEL_API_KEY" in r["error"]["message"]


def test_live_app_cap_blocks_before_any_call():
    d = DeskState(key="k")            # key present, but cap exhausted
    d.live_extract_calls = 10**6
    r = d.enquire("x", "live")
    assert r["error"]["type"] == "AppSpendCap"


def test_transcribe_without_key_refuses(desk):
    assert desk.transcribe(b"RIFF....")["error"]["type"] == "NoKey"


def test_transcribe_rejects_bad_wav_before_upload(tmp_path):
    d = DeskState(key="k")
    assert d.transcribe(b"not a wav at all")["error"]["type"] == "TranscriptionError"


def test_input_bound_and_empty(desk):
    assert desk.enquire("", "mock")["error"]["type"] == "EmptyEnquiry"
    assert desk.enquire("x" * 2001, "mock")["error"]["type"] == "InputBound"


def test_reset_clears_multiturn_state(desk):
    desk.enquire("Are any seats free?", "mock")
    assert desk.assistant("mock").pending is not None
    desk.reset("mock")
    assert desk.assistant("mock").pending is None
