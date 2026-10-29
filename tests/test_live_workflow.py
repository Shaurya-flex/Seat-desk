"""Live-model-driven workflow via MOCKED HTTP (no network, no credentials).

Exercises the complete path: model extraction -> deterministic tool -> supported
response. Proves the live model's VALIDATED fields drive date/interval/slot/seat
(not a keyword parser), corrections work, and there is no silent fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.model import LiveModelAdapter
from app.tools import AvailabilityTool
from app.retrieval import load_pack
from app.workflow import Assistant

BASE = Path(__file__).resolve().parent.parent
SAMPLE = BASE / "knowledge" / "policies.sample.json"
FX = BASE / "fixtures"


class R:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            req = httpx.Request("POST", "https://api.meta.ai/v1/chat/completions")
            raise httpx.HTTPStatusError("err", request=req,
                                        response=httpx.Response(self.status_code, request=req))


class SeqClient:
    """Returns queued responses (or raises queued exceptions), one per POST."""
    def __init__(self, outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def post(self, url, json=None, headers=None):
        self.calls += 1
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    def close(self):
        pass


def ext(lang, intent, **fields):
    body = {"lang": lang, "intent": intent, "fields": fields}
    return R({"choices": [{"message": {"content": json.dumps(body)}}]})


def live_assistant(outcomes):
    model = LiveModelAdapter("https://api.meta.ai/v1", "muse-spark-1.3", "testkey",
                             verified=True, http_client=SeqClient(outcomes))
    return Assistant(pack=load_pack(SAMPLE), tool=AvailabilityTool(FX), model=model)


def test_live_full_path_extraction_to_response():
    a = live_assistant([ext("hi", "availability", date="2026-10-28", slot="evening")])
    r = a.handle("कल शाम कौन सी सीटें खाली हैं?")
    assert r["simulated"] is False
    assert r["route"] == "availability"
    assert r["availability"]["query"]["date"] == "2026-10-28"
    assert r["availability"]["query"]["slot"] == "evening"
    assert r["availability"]["summary"]["available"] == 6
    assert "6" in r["answer"]


def test_live_fields_win_over_keyword_text():
    # The TEXT says "tomorrow evening"; the model extracts MORNING. The model's
    # validated field must win — no hidden keyword parser.
    a = live_assistant([ext("en", "availability", date="2026-10-28", slot="morning")])
    r = a.handle("are seats free tomorrow evening?")
    assert r["availability"]["query"]["slot"] == "morning"   # not "evening"


def test_live_correction_keeps_date_changes_slot():
    a = live_assistant([
        ext("en", "availability", date="2026-10-28", slot="evening"),
        ext("en", "availability", slot="morning"),           # "actually morning"
    ])
    a.handle("are seats free tomorrow evening?")
    r = a.handle("actually morning")
    assert r["route"] == "availability"
    assert r["availability"]["query"]["date"] == "2026-10-28"
    assert r["availability"]["query"]["slot"] == "morning"


def test_live_seat_followup_keeps_interval():
    a = live_assistant([
        ext("en", "availability", date="2026-10-28", start="06:00", end="07:00"),
        ext("en", "availability", seat_id="S01"),            # "is S01 free in it?"
    ])
    a.handle("are seats free tomorrow 06:00-07:00?")
    r = a.handle("is seat S01 free in it?")
    assert r["availability"]["query"]["seat_id"] == "S01"
    assert r["availability"]["query"]["start"] == "06:00"
    assert r["availability"]["query"]["end"] == "07:00"


def test_live_missing_fields_clarify():
    a = live_assistant([ext("en", "availability")])          # no fields
    r = a.handle("are any seats free?")
    assert r["route"] == "clarify"


def test_live_model_intent_clarify():
    a = live_assistant([ext("en", "clarify")])
    r = a.handle("something vague")
    assert r["route"] == "clarify"


def test_live_no_silent_fallback_on_persistent_error():
    a = live_assistant([R({}, 500), R({}, 500), R({}, 500)])  # retries exhausted
    with pytest.raises(httpx.HTTPStatusError):                # raises, never a mock answer
        a.handle("are seats free tomorrow evening?")


def test_transport_marked_mocked_http():
    a = live_assistant([ext("en", "availability", date="2026-10-28", slot="evening")])
    r = a.handle("are seats free on 2026-10-28 evening?")
    assert r["transport"] == "mocked-http"       # distinguishable from a real provider response
    assert r["simulated"] is False


def test_transport_builtin_for_mock_model():
    from app.workflow import build_default_assistant
    r = build_default_assistant(pack_path=SAMPLE).handle("What is the monthly fee?")
    assert r["transport"] == "builtin"
