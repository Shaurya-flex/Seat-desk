"""Intended-query correctness + model-extracted fields driving the deterministic tool.

- Independently authored expected cases: the enquiry must produce the INTENDED
  query (date/interval/slot/seat) and the right deterministic result, checked
  against hand-computed expectations — not just self-consistency.
- A model-extracted Hindi date/time (via parse_extraction) actually drives the
  deterministic availability tool. The model never decides availability.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.workflow import build_default_assistant
from app.tools import AvailabilityTool
from app.model import LiveModelAdapter

BASE = Path(__file__).resolve().parent.parent
SAMPLE = BASE / "knowledge" / "policies.sample.json"
FX = BASE / "fixtures"
CASES = json.loads((BASE / "eval" / "expected_queries.json").read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_intended_query_matches_independent_expectation(case):
    a = build_default_assistant(pack_path=SAMPLE)
    r = a.handle(case["enquiry"])
    if case.get("clarify"):
        assert r["route"] == "clarify", f"{case['id']}: expected clarify, got {r['route']}"
        assert r["availability"] is None
        return
    av = r["availability"]
    assert av is not None, f"{case['id']}: no availability produced"
    # intended query fields
    for k, v in case["request"].items():
        assert av["query"].get(k) == v, f"{case['id']}: query[{k}]={av['query'].get(k)!r} != {v!r}"
    # intended deterministic result
    assert av["status"] == case["status"], f"{case['id']}: status {av['status']} != {case['status']}"
    if case["status"] == "ok":
        assert av["summary"]["available"] == case["available"]
        assert av["summary"]["considered"] == case["considered"]


def test_hindi_extracted_fields_drive_deterministic_tool():
    # What a live model would return for "कल शाम कौन सी सीटें खाली हैं?"
    content = json.dumps({"lang": "hi", "intent": "availability",
                          "fields": {"date": "2026-10-28", "slot": "evening"}})
    fields = LiveModelAdapter.parse_extraction({"choices": [{"message": {"content": content}}]})
    # the model's VALIDATED fields drive the deterministic tool; the model never
    # decides availability.
    tool = AvailabilityTool(FX)
    result = tool.get_availability({"date": fields.date, "slot": fields.slot})
    assert result["status"] == "ok"
    assert result["query"]["date"] == "2026-10-28" and result["query"]["slot"] == "evening"
    assert result["summary"]["available"] == 6
