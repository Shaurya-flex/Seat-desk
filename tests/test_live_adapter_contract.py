"""Mocked-HTTP contract tests for LiveModelAdapter — NO network, NO credentials.

Verifies request/parse against the assumed chat-completions schema (which must be
re-verified against official docs before real use), structured-extraction and
tool-call validation, classified retries, and that there is NO silent fallback.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.model import LiveModelAdapter, ExtractionError, ToolNotAllowed, Classification

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
