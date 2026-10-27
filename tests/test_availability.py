"""Tests for the deterministic availability engine.

Run: python -m pytest -q   (from the project root)
Covers: half-open overlap, boundary touch, partial/containment overlap,
multiple overlapping records on one seat, seat filtering, slot resolution,
membership validity, argument-type validation, operating-hours enforcement,
occupancy coverage, membership/occupancy separation, response sanitisation,
timezone, and determinism.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import json
import pytest

from app.availability import (
    intervals_overlap, membership_status, query_availability, sanitise_availability,
    load_seats, load_memberships, load_occupancy, load_slots,
    load_operating_hours, load_coverage,
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
        "operating_hours": load_operating_hours(FX / "operating_hours.json"),
        "coverage": load_coverage(FX / "occupancy.json"),
        "clock": load_demo_clock(FX / "demo_clock.json"),
    }


def _q(request, data):
    return query_availability(
        request, seats=data["seats"], occupancy=data["occupancy"],
        memberships=data["memberships"], slots=data["slots"],
        operating_hours=data["operating_hours"], coverage=data["coverage"],
        clock=data["clock"],
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
    r = _q({"date": "2026-10-27", "start": "10:00", "end": "12:00", "seat_id": "S02"}, data)
    assert r["status"] == "ok"
    assert _seat(r, "S02")["available"] is True


def test_partial_overlap_blocks(data):
    r = _q({"date": "2026-10-27", "start": "11:00", "end": "12:30", "seat_id": "S02"}, data)
    assert _seat(r, "S02")["available"] is False


def test_multiple_overlapping_records_on_one_seat(data):
    only_first = _seat(_q({"date": "2026-10-27", "start": "09:00", "end": "09:30", "seat_id": "S01"}, data), "S01")
    only_second = _seat(_q({"date": "2026-10-27", "start": "11:30", "end": "12:00", "seat_id": "S01"}, data), "S01")
    both = _seat(_q({"date": "2026-10-27", "start": "10:30", "end": "11:00", "seat_id": "S01"}, data), "S01")
    assert len(only_first["conflicts"]) == 1
    assert len(only_second["conflicts"]) == 1
    assert len(both["conflicts"]) == 2


def test_in_coverage_empty_window_all_free(data):
    # 2026-10-27 16:00-17:00 is within coverage and hours, and has no occupancy.
    r = _q({"date": "2026-10-27", "start": "16:00", "end": "17:00"}, data)
    assert r["status"] == "ok"
    assert r["summary"]["available"] == r["summary"]["considered"] == len(data["seats"])


def test_occupancy_is_date_scoped(data):
    r = _q({"date": "2026-10-27", "start": "09:00", "end": "11:00", "seat_id": "S04"}, data)
    assert _seat(r, "S04")["available"] is True


def test_unknown_seat_is_error(data):
    r = _q({"date": "2026-10-27", "start": "09:00", "end": "11:00", "seat_id": "S99"}, data)
    assert r["valid_request"] is False and r["status"] == "invalid_request"
    assert any("unknown seat" in e for e in r["errors"])


def test_slot_resolution(data):
    r = _q({"date": "2026-10-27", "slot": "evening"}, data)   # 18:00-22:00
    assert r["status"] == "ok"
    assert _seat(r, "S03")["available"] is False
    assert r["query"]["start"] == "18:00" and r["query"]["end"] == "22:00"


def test_unknown_slot_is_error(data):
    r = _q({"date": "2026-10-27", "slot": "midnight"}, data)
    assert r["valid_request"] is False
    assert any("unknown slot" in e for e in r["errors"])


# --- FIX 1: argument-type validation (null / wrong type -> structured error) ---
def test_null_date_is_validation_error(data):
    r = _q({"date": None, "start": "09:00", "end": "11:00"}, data)
    assert r["valid_request"] is False and r["status"] == "invalid_request"
    assert any("date" in e for e in r["errors"])


def test_null_time_is_validation_error(data):
    r = _q({"date": "2026-10-27", "start": None, "end": None}, data)
    assert r["valid_request"] is False and r["status"] == "invalid_request"


def test_non_string_date_is_validation_error(data):
    r = _q({"date": 20261027, "start": "09:00", "end": "11:00"}, data)
    assert r["valid_request"] is False
    assert any("must be a string" in e for e in r["errors"])


def test_bad_date_format_is_validation_error(data):
    r = _q({"date": "27-10-2026", "start": "09:00", "end": "11:00"}, data)
    assert r["valid_request"] is False
    assert any("date" in e for e in r["errors"])


# --- FIX 2: operating-hours enforcement ---
def test_outside_operating_hours_is_closed(data):
    r = _q({"date": "2026-10-27", "start": "02:00", "end": "03:00"}, data)
    assert r["status"] == "closed"
    assert r["seats"] == []
    assert r["operating_hours"]["within"] is False


def test_within_operating_hours_ok(data):
    r = _q({"date": "2026-10-27", "start": "09:00", "end": "11:00"}, data)
    assert r["status"] == "ok"
    assert r["operating_hours"]["within"] is True


# --- FIX 3: occupancy coverage -> availability_unknown ---
def test_date_outside_coverage_is_unknown(data):
    r = _q({"date": "2026-10-29", "start": "09:00", "end": "11:00"}, data)
    assert r["status"] == "availability_unknown"
    assert r["seats"] == []
    assert any("coverage" in w for w in r["warnings"])


def test_date_inside_coverage_is_ok(data):
    r = _q({"date": "2026-10-28", "start": "12:00", "end": "13:00"}, data)
    assert r["status"] == "ok"


# --- FIX 4: physical availability separate from membership eligibility ---
def test_expired_member_occupancy_not_removed_but_flagged(data):
    # S05 is occupied 14:00-16:00 by M004 (suspended). Seat must stay occupied.
    r = _q({"date": "2026-10-27", "start": "14:30", "end": "15:00", "seat_id": "S05"}, data)
    assert _seat(r, "S05")["available"] is False          # not removed
    assert any(i["seat_id"] == "S05" for i in r["inconsistencies"])  # flagged for review


def test_requester_membership_does_not_change_seats(data):
    # An expired requesting member does not change physical availability.
    free = _q({"date": "2026-10-27", "start": "16:00", "end": "17:00", "seat_id": "S02"}, data)
    free_expired = _q({"date": "2026-10-27", "start": "16:00", "end": "17:00", "seat_id": "S02", "member_id": "M002"}, data)
    assert free["seats"][0]["available"] == free_expired["seats"][0]["available"] is True
    assert free_expired["membership"]["valid"] is False   # reported, not enforced


# --- FIX 5: sanitised response hides member details ---
def test_sanitise_hides_member_details(data):
    full = _q({"date": "2026-10-27", "start": "14:30", "end": "15:00", "seat_id": "S05", "member_id": "M002"}, data)
    clean = sanitise_availability(full)
    blob = json.dumps(clean)
    assert "member_id" not in blob
    assert "M002" not in blob and "M004" not in blob
    assert "membership" not in clean and "inconsistencies" not in clean
    assert "note" not in blob
    # busy windows are preserved (when not available) without the holder.
    assert clean["seats"][0]["busy"] == [{"start": "14:00", "end": "16:00"}]


# --- membership validity (advisory) ---
def test_membership_valid(data):
    assert membership_status("M001", date(2026, 10, 27), data["memberships"])["valid"] is True


def test_membership_expired(data):
    s = membership_status("M002", date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "expired" in s["reason"]


def test_membership_not_yet_valid(data):
    s = membership_status("M003", date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "not valid until" in s["reason"]


def test_membership_suspended(data):
    s = membership_status("M004", date(2026, 10, 27), data["memberships"])
    assert s["valid"] is False and "suspended" in s["reason"]


def test_membership_unknown(data):
    s = membership_status("M999", date(2026, 10, 27), data["memberships"])
    assert s["known"] is False and s["valid"] is None


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
    r = _q({"date": "2026-10-27", "start": "06:00", "end": "08:00"}, data)
    assert r["status"] == "ok"
    assert any("past" in w for w in r["warnings"])


def test_as_of_is_ist(data):
    r = _q({"date": "2026-10-27", "start": "14:00", "end": "15:00", "seat_id": "S01"}, data)
    assert r["as_of"].endswith("+05:30")
    assert r["timezone"] == "Asia/Kolkata"


def test_determinism(data):
    req = {"date": "2026-10-27", "slot": "afternoon", "member_id": "M001"}
    assert _q(req, data) == _q(req, data)
