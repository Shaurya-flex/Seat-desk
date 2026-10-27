"""Tests for the deterministic availability engine.

Run: python -m pytest -q   (from the project root)
Covers: half-open overlap, boundary touch, partial/containment overlap,
multiple overlapping records on one seat, empty days, seat filtering,
slot resolution, membership validity (valid/expired/not-yet/suspended/unknown),
invalid intervals, past-time warnings, timezone, and determinism.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.availability import (
    intervals_overlap, membership_status, query_availability,
    load_seats, load_memberships, load_occupancy, load_slots,
)
from app.clock import load_demo_clock

FX = Path(__file__).resolve().parent.parent / "fixtures"
IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture(scope="module")
def data():
    return {
        "seats": load_seats(FX / "seats.json"),
        "occupancy": load_occupancy(FX / "occupancy.json"),
        "memberships": load_memberships(FX / "memberships.json"),
        "slots": load_slots(FX / "slots.json"),
        "clock": load_demo_clock(FX / "demo_clock.json"),
    }


def _q(request, data, **kw):
    return query_availability(
        request, seats=data["seats"], occupancy=data["occupancy"],
        memberships=data["memberships"], slots=data["slots"],
        clock=data["clock"], **kw,
    )


def _seat(result, seat_id):
    return next(s for s in result["seats"] if s["seat_id"] == seat_id)


# --- pure overlap function ---
def test_intervals_overlap_pure():
    d = lambda h, m=0: datetime(2026, 10, 27, h, m, tzinfo=IST)
    assert intervals_overlap(d(10), d(12), d(11), d(13)) is True   # partial
    assert intervals_overlap(d(10), d(14), d(11), d(12)) is True   # containment
    assert intervals_overlap(d(10), d(12), d(12), d(13)) is False  # touch at boundary
    assert intervals_overlap(d(12), d(13), d(10), d(12)) is False  # touch, reversed


# --- overlap behaviour through the query ---
def test_boundary_touch_is_available(data):
    # S02 occupied 12:00-14:00; query 10:00-12:00 touches boundary -> free.
    r = _q({"date": "2026-10-27", "start": "10:00", "end": "12:00", "seat_id": "S02"}, data)
    assert _seat(r, "S02")["available"] is True


def test_partial_overlap_blocks(data):
    r = _q({"date": "2026-10-27", "start": "11:00", "end": "12:30", "seat_id": "S02"}, data)
    assert _seat(r, "S02")["available"] is False


def test_multiple_overlapping_records_on_one_seat(data):
    # S01 has two overlapping records: 09:00-11:00 and 10:30-12:30.
    only_first = _seat(_q({"date": "2026-10-27", "start": "09:00", "end": "09:30", "seat_id": "S01"}, data), "S01")
    only_second = _seat(_q({"date": "2026-10-27", "start": "11:30", "end": "12:00", "seat_id": "S01"}, data), "S01")
    both = _seat(_q({"date": "2026-10-27", "start": "10:30", "end": "11:00", "seat_id": "S01"}, data), "S01")
    assert len(only_first["conflicts"]) == 1
    assert len(only_second["conflicts"]) == 1
    assert len(both["conflicts"]) == 2


def test_empty_day_all_free(data):
    r = _q({"date": "2026-10-29", "start": "09:00", "end": "11:00"}, data)
    assert r["summary"]["available"] == r["summary"]["considered"] == len(data["seats"])


def test_occupancy_is_date_scoped(data):
    # S04 is occupied only on 2026-10-28, so it is free on 2026-10-27.
    r = _q({"date": "2026-10-27", "start": "09:00", "end": "11:00", "seat_id": "S04"}, data)
    assert _seat(r, "S04")["available"] is True


def test_unknown_seat_is_error(data):
    r = _q({"date": "2026-10-27", "start": "09:00", "end": "11:00", "seat_id": "S99"}, data)
    assert r["valid_request"] is False
    assert any("unknown seat" in e for e in r["errors"])


def test_slot_resolution(data):
    r = _q({"date": "2026-10-27", "slot": "evening"}, data)   # 18:00-22:00
    assert r["valid_request"] is True
    # S03 is occupied 18:00-20:00 -> blocked in the evening slot.
    assert _seat(r, "S03")["available"] is False
    assert r["query"]["start"] == "18:00" and r["query"]["end"] == "22:00"


def test_unknown_slot_is_error(data):
    r = _q({"date": "2026-10-27", "slot": "midnight"}, data)
    assert r["valid_request"] is False
    assert any("unknown slot" in e for e in r["errors"])


# --- membership validity ---
def test_membership_valid(data):
    assert membership_status("M001", __import__("datetime").date(2026, 10, 27), data["memberships"])["valid"] is True


def test_membership_expired(data):
    s = membership_status("M002", __import__("datetime").date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "expired" in s["reason"]


def test_membership_not_yet_valid(data):
    s = membership_status("M003", __import__("datetime").date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "not valid until" in s["reason"]


def test_membership_suspended(data):
    s = membership_status("M004", __import__("datetime").date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "suspended" in s["reason"]


def test_membership_unknown(data):
    s = membership_status("M999", __import__("datetime").date(2026, 10, 27), data["memberships"])
    assert s["known"] is False and s["valid"] is None


def test_membership_reported_in_query(data):
    r = _q({"date": "2026-10-27", "slot": "morning", "member_id": "M002"}, data)
    assert r["membership"]["valid"] is False


# --- request validation ---
def test_invalid_interval(data):
    r = _q({"date": "2026-10-27", "start": "12:00", "end": "11:00"}, data)
    assert r["valid_request"] is False
    assert any("earlier than" in e for e in r["errors"])


def test_missing_fields(data):
    r = _q({"date": "2026-10-27"}, data)
    assert r["valid_request"] is False


# --- demo clock / timezone ---
def test_past_interval_warns(data):
    # Demo clock is 2026-10-27 10:00 IST; 06:00-08:00 is in the past.
    r = _q({"date": "2026-10-27", "start": "06:00", "end": "08:00"}, data)
    assert r["valid_request"] is True
    assert any("past" in w for w in r["warnings"])


def test_as_of_is_ist(data):
    r = _q({"date": "2026-10-27", "start": "14:00", "end": "15:00"}, data)
    assert r["as_of"].endswith("+05:30")
    assert r["timezone"] == "Asia/Kolkata"


def test_determinism(data):
    req = {"date": "2026-10-27", "slot": "afternoon", "member_id": "M001"}
    assert _q(req, data) == _q(req, data)
