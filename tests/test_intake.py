"""Tests for the mock intake scaffolding (clearly labelled unfinished)."""
from __future__ import annotations

from pathlib import Path

from app.intake import typed_transcript, MockTranscriber, confirm_transcript, staff_recheck
from app.tools import AvailabilityTool

FX = Path(__file__).resolve().parent.parent / "fixtures"


def test_typed_transcript_needs_no_confirmation():
    t = typed_transcript("लाइब्रेरी कब खुलती है?")
    assert t.needs_confirmation is False and t.mock is False and t.source == "typed"


def test_mock_transcriber_is_labelled_and_needs_confirmation():
    t = MockTranscriber().transcribe("audio-1.wav")
    assert t.mock is True and t.needs_confirmation is True
    assert "UNVERIFIED" in t.text


def test_confirm_transcript_applies_correction():
    t = MockTranscriber().transcribe("a.wav")
    c = confirm_transcript(t, "Are seats free tomorrow evening?")
    assert c.needs_confirmation is False and c.text == "Are seats free tomorrow evening?"


def test_staff_recheck_matches_direct_lookup():
    tool = AvailabilityTool(FX)
    q = {"date": "2026-10-28", "slot": "evening"}
    direct = tool.get_availability(q)
    rc = staff_recheck({"date": "2026-10-28", "slot": "evening",
                        "start": "18:00", "end": "22:00", "seat_id": None}, tool)
    assert rc["rechecked"] is True
    assert rc["status"] == direct["status"]
    assert rc["summary"] == direct["summary"]
