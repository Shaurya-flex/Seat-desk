"""The live-run acceptance must be substantive: a completed request with a wrong
slot, wrong count, wrong seat set, or an unsupported answer cannot be SUCCESS.

The base response here is produced by the REAL Assistant.handle() path with the
live adapter over a stubbed transport (deterministic, offline, no spend), then
each regression tampers one aspect and must fail evaluation.
"""
import copy
import json
from pathlib import Path

import pytest

from app.live_checks import evaluate_live_run, expected_from_fixtures
from app.model import make_model
from app.retrieval import load_pack
from app.tools import AvailabilityTool
from app.workflow import Assistant

ROOT = Path(__file__).resolve().parent.parent
ENQUIRY = "28 अक्टूबर 2026 को दोपहर में कौन सी सीटें खाली हैं?"
EXPECTED = expected_from_fixtures(ROOT / "fixtures", "2026-10-28", "afternoon")


class _Resp:
    status_code = 200
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class _Stub:
    """Exactly the shape of a correct muse-spark-1.3 strict-JSON reply."""
    def post(self, url, json=None, headers=None):
        content = __import__("json").dumps(
            {"lang": "hi", "intent": "availability",
             "fields": {"date": "2026-10-28", "start": None, "end": None,
                        "slot": "afternoon", "seat_id": None}})
        return _Resp({"id": "stub-1", "model": "muse-spark-1.3",
                      "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                      "usage": {"prompt_tokens": 640, "completion_tokens": 321,
                                "total_tokens": 961,
                                "completion_tokens_details": {"reasoning_tokens": 268}}})


def _run_once():
    model = make_model("live", base_url="https://api.meta.ai/v1", model_id="muse-spark-1.3",
                       api_key="stub", verified=True, retries=0, max_outstanding=1,
                       reasoning_effort="minimal", http_client=_Stub())
    a = Assistant(pack=load_pack(ROOT / "knowledge" / "policies.sample.json"),
                  tool=AvailabilityTool(ROOT / "fixtures"), model=model)
    resp = a.handle(ENQUIRY)
    return resp, dict(a.last_availability), model.last_meta


def _evaluate(resp, resolved, meta, **kw):
    return evaluate_live_run(
        resp, resolved, meta, expected=EXPECTED,
        recheck_tool=AvailabilityTool(ROOT / "fixtures"),
        pack=load_pack(ROOT / "knowledge" / "policies.sample.json"), **kw)


@pytest.fixture()
def base():
    resp, resolved, meta = _run_once()
    return resp, resolved, meta


def test_correct_run_passes_every_substantive_check(base):
    resp, resolved, meta = base
    # The stubbed transport is honestly reported as mocked-http; with the live
    # transport requirement relaxed, everything substantive must pass.
    out = _evaluate(resp, resolved, meta, require_live_transport=False)
    assert out["consistency_issues"] == []
    assert out["checks"]["workflow_successful"], out["checks"]


def test_mocked_transport_is_never_a_live_success(base):
    resp, resolved, meta = base
    out = _evaluate(resp, resolved, meta)            # live transport required
    assert resp["transport"] == "mocked-http"
    assert not out["checks"]["transport_live"]
    assert not out["checks"]["workflow_successful"]


def test_wrong_slot_interval_fails(base):
    resp, resolved, meta = base
    bad = copy.deepcopy(resp)
    bad["availability"]["query"]["start"] = "06:00"   # morning bounds smuggled in
    bad["availability"]["query"]["end"] = "12:00"
    out = _evaluate(bad, resolved, meta, require_live_transport=False)
    assert not out["checks"]["interval_canonical"]
    assert not out["checks"]["workflow_successful"]


def test_wrong_count_fails(base):
    resp, resolved, meta = base
    bad = copy.deepcopy(resp)
    bad["availability"]["summary"]["available"] = 5
    out = _evaluate(bad, resolved, meta, require_live_transport=False)
    assert not out["checks"]["counts_match_fixture"]
    # the independent recomputation catches the tamper as well
    assert "recompute_summary_mismatch" in out["consistency_issues"]
    assert not out["checks"]["workflow_successful"]


def test_wrong_free_seat_set_fails(base):
    resp, resolved, meta = base
    bad = copy.deepcopy(resp)
    bad["availability"]["seats"][0]["available"] = False
    out = _evaluate(bad, resolved, meta, require_live_transport=False)
    assert not out["checks"]["free_seats_match_fixture"]
    assert not out["checks"]["workflow_successful"]


def test_unsupported_answer_fails(base):
    resp, resolved, meta = base
    bad = copy.deepcopy(resp)
    bad["answer"] = "सभी सीटें खाली हैं, आ जाइए!"     # no count, no date, unsupported
    out = _evaluate(bad, resolved, meta, require_live_transport=False)
    assert not out["checks"]["answer_states_count_and_date"]
    assert not out["checks"]["answer_consistent_and_recomputed"]
    assert not out["checks"]["workflow_successful"]


def test_wrong_resolved_date_fails(base):
    resp, resolved, meta = base
    out = _evaluate(resp, {**resolved, "date": "2026-10-27"}, meta,
                    require_live_transport=False)
    assert not out["checks"]["date_correct"]
    assert not out["checks"]["workflow_successful"]


def test_truncated_seat_list_must_be_labelled(base):
    resp, resolved, meta = base
    # six seats free -> the answer shows three and must mark them as examples
    assert "जैसे" in resp["answer"] or "e.g." in resp["answer"]
    bad = copy.deepcopy(resp)
    bad["answer"] = bad["answer"].replace("जैसे ", "").replace("e.g. ", "")
    out = _evaluate(bad, resolved, meta, require_live_transport=False)
    assert not out["checks"]["seat_list_display_honest"]
    assert not out["checks"]["workflow_successful"]
