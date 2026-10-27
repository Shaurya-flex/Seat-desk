"""Deterministic seat-availability lookup over synthetic data.

Read-only. This module never books, pays, or changes any record. It answers,
for a requested date and time interval: which seats are free, honouring
half-open intervals [start, end), overlapping occupancy records, membership
validity, and an explicit demonstration clock in Asia/Kolkata.

All business data comes from /fixtures (synthetic) — nothing is hard-coded here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .clock import DemoClock

IST = ZoneInfo("Asia/Kolkata")

__all__ = [
    "Seat", "Membership", "Occupancy",
    "load_seats", "load_memberships", "load_occupancy", "load_slots",
    "intervals_overlap", "membership_status", "seat_conflicts",
    "query_availability",
]


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Seat:
    seat_id: str
    label: str
    zone: str


@dataclass(frozen=True)
class Membership:
    member_id: str
    name: str
    valid_from: date
    valid_to: date
    status: str  # "active" | "suspended" | ...


@dataclass(frozen=True)
class Occupancy:
    seat_id: str
    on_date: date
    start: time
    end: time
    member_id: Optional[str] = None
    note: str = ""


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------
def _parse_date(s: str) -> date:
    return date.fromisoformat(s)


def _parse_time(s: str) -> time:
    return time.fromisoformat(s)


def _dt(d: date, t: time) -> datetime:
    """Combine a date and a wall-clock time into an aware datetime in IST."""
    return datetime.combine(d, t, tzinfo=IST)


def _load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_seats(path: str | Path) -> list[Seat]:
    raw = _load_json(path)["seats"]
    return [Seat(s["seat_id"], s["label"], s["zone"]) for s in raw]


def load_memberships(path: str | Path) -> list[Membership]:
    raw = _load_json(path)["memberships"]
    return [
        Membership(
            m["member_id"], m["name"],
            _parse_date(m["valid_from"]), _parse_date(m["valid_to"]),
            m["status"],
        )
        for m in raw
    ]


def load_occupancy(path: str | Path) -> list[Occupancy]:
    raw = _load_json(path)["occupancy"]
    return [
        Occupancy(
            o["seat_id"], _parse_date(o["date"]),
            _parse_time(o["start"]), _parse_time(o["end"]),
            o.get("member_id"), o.get("note", ""),
        )
        for o in raw
    ]


def load_slots(path: str | Path) -> dict[str, tuple[time, time]]:
    raw = _load_json(path)["slots"]
    return {s["slot_id"]: (_parse_time(s["start"]), _parse_time(s["end"])) for s in raw}


# --------------------------------------------------------------------------
# Core logic
# --------------------------------------------------------------------------
def intervals_overlap(a_start: datetime, a_end: datetime,
                      b_start: datetime, b_end: datetime) -> bool:
    """True if half-open intervals [a_start, a_end) and [b_start, b_end) overlap.

    Touching at a boundary (a_end == b_start) is NOT an overlap.
    """
    return a_start < b_end and b_start < a_end


def membership_status(member_id: str, on_date: date,
                      memberships: list[Membership]) -> dict:
    """Validity of a membership on a given date. Pure; no side effects."""
    match = next((m for m in memberships if m.member_id == member_id), None)
    if match is None:
        return {"member_id": member_id, "known": False, "valid": None,
                "reason": "unknown member id"}

    if match.status != "active":
        return {"member_id": member_id, "known": True, "valid": False,
                "reason": f"membership status is '{match.status}'"}
    if on_date < match.valid_from:
        return {"member_id": member_id, "known": True, "valid": False,
                "reason": f"not valid until {match.valid_from.isoformat()}"}
    if on_date > match.valid_to:
        return {"member_id": member_id, "known": True, "valid": False,
                "reason": f"expired on {match.valid_to.isoformat()}"}
    return {"member_id": member_id, "known": True, "valid": True, "reason": "valid"}


def seat_conflicts(seat_id: str, q_date: date, q_start: time, q_end: time,
                   occupancy: list[Occupancy]) -> list[Occupancy]:
    """Occupancy records on this seat/date that overlap the requested interval.

    Robust to occupancy records that overlap each other — each is tested
    independently against the query, so overlapping source data is fine.
    """
    qs, qe = _dt(q_date, q_start), _dt(q_date, q_end)
    hits = [
        o for o in occupancy
        if o.seat_id == seat_id and o.on_date == q_date
        and intervals_overlap(qs, qe, _dt(o.on_date, o.start), _dt(o.on_date, o.end))
    ]
    return sorted(hits, key=lambda o: (o.start, o.end))


def _conflict_view(o: Occupancy) -> dict:
    return {"start": o.start.strftime("%H:%M"), "end": o.end.strftime("%H:%M"),
            "member_id": o.member_id, "note": o.note}


def query_availability(
    request: dict,
    *,
    seats: list[Seat],
    occupancy: list[Occupancy],
    clock: DemoClock,
    memberships: Optional[list[Membership]] = None,
    slots: Optional[dict[str, tuple[time, time]]] = None,
) -> dict:
    """Answer a seat-availability question deterministically.

    request keys:
        date     "YYYY-MM-DD"            (required)
        start    "HH:MM"                 (required unless 'slot' given)
        end      "HH:MM"                 (required unless 'slot' given)
        slot     slot_id                 (optional; resolved via `slots`)
        seat_id  str                     (optional; restrict to one seat)
        member_id str                    (optional; report membership validity)

    Returns a JSON-serialisable dict. Never raises on bad input: problems are
    reported in `errors` with valid_request=False.
    """
    memberships = memberships or []
    errors: list[str] = []
    warnings: list[str] = []

    # --- resolve date ---
    q_date: Optional[date] = None
    try:
        q_date = _parse_date(request["date"])
    except (KeyError, ValueError):
        errors.append("missing or invalid 'date' (expected YYYY-MM-DD)")

    # --- resolve interval (slot or explicit start/end) ---
    q_start: Optional[time] = None
    q_end: Optional[time] = None
    if "slot" in request and request["slot"] is not None:
        if slots and request["slot"] in slots:
            q_start, q_end = slots[request["slot"]]
        else:
            errors.append(f"unknown slot '{request.get('slot')}'")
    else:
        try:
            q_start = _parse_time(request["start"])
            q_end = _parse_time(request["end"])
        except (KeyError, ValueError):
            errors.append("missing or invalid 'start'/'end' (expected HH:MM)")

    if q_start is not None and q_end is not None and q_start >= q_end:
        errors.append("'start' must be earlier than 'end'")

    # --- membership (independent of interval validity) ---
    membership = None
    if request.get("member_id"):
        on = q_date or clock.as_of.date()
        membership = membership_status(request["member_id"], on, memberships)

    base = {
        "as_of": clock.as_of.isoformat(),
        "timezone": clock.tzname,
        "query": {
            "date": request.get("date"),
            "start": q_start.strftime("%H:%M") if q_start else request.get("start"),
            "end": q_end.strftime("%H:%M") if q_end else request.get("end"),
            "slot": request.get("slot"),
            "seat_id": request.get("seat_id"),
            "member_id": request.get("member_id"),
        },
        "membership": membership,
        "errors": errors,
        "warnings": warnings,
    }

    if errors:
        return {**base, "valid_request": False, "seats": [],
                "summary": {"available": 0, "considered": 0}}

    # --- past-time flag (not an error; the clock is explicit) ---
    qs, qe = _dt(q_date, q_start), _dt(q_date, q_end)
    if qe <= clock.as_of:
        warnings.append("requested interval is entirely in the past relative to the demo clock")
    elif qs < clock.as_of:
        warnings.append("requested interval started before the demo clock 'now'")

    # --- which seats to consider ---
    if request.get("seat_id"):
        chosen = [s for s in seats if s.seat_id == request["seat_id"]]
        if not chosen:
            errors.append(f"unknown seat_id '{request['seat_id']}'")
            return {**base, "valid_request": False, "seats": [],
                    "summary": {"available": 0, "considered": 0}}
    else:
        chosen = sorted(seats, key=lambda s: s.seat_id)

    seat_rows = []
    for s in chosen:
        conflicts = seat_conflicts(s.seat_id, q_date, q_start, q_end, occupancy)
        available = len(conflicts) == 0
        seat_rows.append({
            "seat_id": s.seat_id,
            "label": s.label,
            "zone": s.zone,
            "available": available,
            "conflicts": [_conflict_view(c) for c in conflicts],
            "reason": "free for the requested interval" if available
                      else f"{len(conflicts)} overlapping reservation(s)",
        })

    available_count = sum(1 for r in seat_rows if r["available"])
    return {
        **base,
        "valid_request": True,
        "seats": seat_rows,
        "summary": {"available": available_count, "considered": len(seat_rows)},
    }


# --------------------------------------------------------------------------
# Tiny manual demo (no network, no model). Run: python -m app.availability
# --------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    base_dir = Path(__file__).resolve().parent.parent
    fx = base_dir / "fixtures"
    clk = __import__("app.clock", fromlist=["load_demo_clock"]).load_demo_clock(fx / "demo_clock.json")
    result = query_availability(
        {"date": "2026-10-27", "slot": "morning", "member_id": "M002"},
        seats=load_seats(fx / "seats.json"),
        occupancy=load_occupancy(fx / "occupancy.json"),
        memberships=load_memberships(fx / "memberships.json"),
        slots=load_slots(fx / "slots.json"),
        clock=clk,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
