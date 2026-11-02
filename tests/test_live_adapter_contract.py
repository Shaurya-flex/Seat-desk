"""Mocked-HTTP contract tests for LiveModelAdapter — NO network, NO credentials.

Verifies request/parse against the assumed chat-completions schema (which must be
re-verified against official docs before real use), structured-extraction and
tool-call validation, classified retries, and that there is NO silent fallback.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.model import (LiveModelAdapter, ExtractionError, ToolNotAllowed, Classification,
                       ExtractedFields, make_model, MockModelAdapter, validate_fields)

BASE = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", BASE + "/chat/completions")
            raise httpx.HTTPStatusError("err", request=req,
                                        response=httpx.Response(self.status_code, request=req))


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, json=None, headers=None):
        self.calls += 1
        self.last_url, self.last_json, self.last_headers = url, json, headers
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def close(self):
        pass


def _ok(lang="en", intent="availability", tool_calls=None):
    body = {"lang": lang, "intent": intent, "fields": {}}
    if tool_calls is not None:
        body["tool_calls"] = tool_calls
    return FakeResponse({"choices": [{"message": {"content": json.dumps(body)}}]})


def _adapter(outcomes, **kw):
    return LiveModelAdapter(BASE, MODEL, "testkey", verified=True,
                            http_client=FakeClient(outcomes), **kw)


# --- parsing / extraction ---
def test_classify_parses_valid():
    a = _adapter([_ok("hi", "policy")])
    c = a.classify("x")
    assert isinstance(c, Classification) and c.lang == "hi" and c.intent == "policy"


def test_invalid_intent_raises():
    a = _adapter([_ok("en", "book_and_charge")])
    with pytest.raises(ExtractionError):
        a.classify("x")


def test_non_json_content_raises():
    bad = FakeResponse({"choices": [{"message": {"content": "sure, here you go"}}]})
    a = _adapter([bad])
    with pytest.raises(ExtractionError):
        a.classify("x")


def test_invalid_lang_raises():
    with pytest.raises(ExtractionError):
        LiveModelAdapter.parse_classification(
            {"choices": [{"message": {"content": json.dumps({"lang": "fr", "intent": "policy"})}}]})


# --- tool-call allowlist ---
def test_tool_call_allowlist_rejects_write():
    with pytest.raises(ToolNotAllowed):
        LiveModelAdapter.validate_tool_call({"name": "book_seat"})


def test_tool_call_allowlist_accepts_readonly():
    assert LiveModelAdapter.validate_tool_call({"name": "get_availability"}) is True


def test_disallowed_tool_in_response_raises():
    a = _adapter([_ok(tool_calls=[{"name": "charge_card"}])])
    with pytest.raises(ToolNotAllowed):
        a.classify("x")


# --- retries (classified) ---
def test_retry_on_5xx_then_success():
    client = FakeClient([FakeResponse({}, 503), _ok("en", "availability")])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client)
    assert a.classify("x").intent == "availability"
    assert client.calls == 2


def test_no_retry_on_4xx():
    client = FakeClient([FakeResponse({}, 400), _ok()])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client, retries=3)
    with pytest.raises(httpx.HTTPStatusError):
        a.classify("x")
    assert client.calls == 1   # 4xx not retried


def test_timeout_is_retryable():
    client = FakeClient([httpx.TimeoutException("t"), _ok("en", "policy")])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client)
    assert a.classify("x").intent == "policy"
    assert client.calls == 2


def test_no_silent_fallback_on_persistent_error():
    client = FakeClient([FakeResponse({}, 500), FakeResponse({}, 500), FakeResponse({}, 500)])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client, retries=2)
    with pytest.raises(httpx.HTTPStatusError):   # raises, never returns a mock result
        a.classify("x")


# --- guards (no call without verification / real endpoint / key) ---
def test_unverified_refuses_before_any_call():
    client = FakeClient([_ok()])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=False, http_client=client)
    with pytest.raises(RuntimeError):
        a.classify("x")
    assert client.calls == 0


def test_illustrative_endpoint_refused():
    a = LiveModelAdapter("https://api.example-meta-models.com/v1", MODEL, "k",
                         verified=True, http_client=FakeClient([_ok()]))
    with pytest.raises(RuntimeError):
        a.classify("x")


def test_missing_key_refused():
    a = LiveModelAdapter(BASE, MODEL, None, verified=True, http_client=FakeClient([_ok()]))
    with pytest.raises(RuntimeError):
        a.classify("x")


# --- host allowlist + HTTPS (verified alone is insufficient) ---
def test_http_endpoint_refused():
    a = LiveModelAdapter("http://api.meta.ai/v1", MODEL, "k", verified=True, http_client=FakeClient([_ok()]))
    with pytest.raises(RuntimeError):
        a.classify("x")


def test_non_allowlisted_https_host_refused():
    a = LiveModelAdapter("https://evil.example.org/v1", MODEL, "k", verified=True, http_client=FakeClient([_ok()]))
    with pytest.raises(RuntimeError):
        a.classify("x")


# --- explicit output-token bound in the request ---
def test_payload_carries_output_token_limit():
    client = FakeClient([_ok()])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client, max_output_tokens=256)
    a.classify("x")
    assert client.last_json["max_completion_tokens"] == 256
    assert "max_tokens" not in client.last_json          # deprecated alias must not be sent


# --- typed extraction (parse_extraction) + validation ---
def test_parse_extraction_valid_fields():
    content = json.dumps({"lang": "hi", "intent": "availability",
                          "fields": {"date": "2026-10-28", "slot": "evening", "seat_id": "S01"}})
    f = LiveModelAdapter.parse_extraction({"choices": [{"message": {"content": content}}]})
    assert isinstance(f, ExtractedFields)
    assert f.date == "2026-10-28" and f.slot == "evening" and f.seat_id == "S01"


@pytest.mark.parametrize("fields", [
    {"date": "28-10-2026"},            # bad date format
    {"date": "2026-13-40"},            # impossible date
    {"start": "25:00", "end": "26:00"},# bad times
    {"start": "15:00", "end": "14:00"},# start >= end
    {"slot": "midnight"},              # bad slot
    {"seat_id": "XYZ"},                # bad seat
])
def test_parse_extraction_rejects_malformed(fields):
    content = json.dumps({"lang": "en", "intent": "availability", "fields": fields})
    with pytest.raises(ExtractionError):
        LiveModelAdapter.parse_extraction({"choices": [{"message": {"content": content}}]})


def test_validate_fields_rejects_non_string_date():
    with pytest.raises(ExtractionError):
        validate_fields(ExtractedFields(lang="en", intent="availability", date=20261028))


# --- fail-closed model factory (no silent fallback) ---
def test_make_model_mock():
    assert isinstance(make_model("mock"), MockModelAdapter)


def test_make_model_live_requires_config():
    with pytest.raises(ValueError):
        make_model("live", base_url=BASE)            # missing model_id/api_key


def test_make_model_unknown_mode_raises():
    with pytest.raises(ValueError):
        make_model("auto")


# --- extraction contract: field schema + reference clock + prior context in payload ---
from app.limits import OutstandingTracker, get_shared_tracker, LimitExceeded  # noqa: E402


def test_payload_includes_contract_and_reference_clock():
    client = FakeClient([_ok("hi", "availability")])
    a = LiveModelAdapter(BASE, MODEL, "k", verified=True, http_client=client)
    a.extract("कल शाम?", now_iso="2026-10-27T10:00:00+05:30",
              prior={"date": "2026-10-28", "slot": "evening"})
    sys_txt = " ".join(m["content"] for m in client.last_json["messages"] if m["role"] == "system")
    assert "YYYY-MM-DD" in sys_txt and "seat_id" in sys_txt      # explicit field contract
    assert "reference_datetime: 2026-10-27" in sys_txt and "Asia/Kolkata" in sys_txt
    assert "prior_query" in sys_txt
    assert client.last_json["max_completion_tokens"] == 512
    # Muse Spark always reasons; effort must be sent explicitly and never "none".
    assert client.last_json["reasoning_effort"] == "minimal"
    assert client.last_json["response_format"]["json_schema"]["strict"] is True


# --- shared process-scope limiter across adapter instances ---
def test_get_shared_tracker_same_key():
    t1 = get_shared_tracker("unit-prov|unit-proj", 2)
    assert get_shared_tracker("unit-prov|unit-proj", 9) is t1   # same key -> same instance
    assert get_shared_tracker("unit-prov|other", 2) is not t1


def test_shared_tracker_bounds_two_adapters():
    import threading
    tr = OutstandingTracker(1)
    ev = threading.Event()

    class Block:
        def post(self, url, json=None, headers=None):
            ev.wait(5)
            return _ok()
        def close(self):
            pass

    a1 = LiveModelAdapter(BASE, MODEL, "k", verified=True, tracker=tr, http_client=Block(), retries=0, timeout_s=0.2)
    a2 = LiveModelAdapter(BASE, MODEL, "k", verified=True, tracker=tr, http_client=FakeClient([_ok()]), retries=0, timeout_s=0.2)
    try:
        with pytest.raises(Exception):          # a1 times out holding the only shared slot
            a1.classify("x")
        with pytest.raises(LimitExceeded):      # a2 cannot overlap while a1's call may still run
            a2.classify("x")
    finally:
        ev.set()
