"""Deterministic seat-availability lookup over synthetic data.

Read-only. This module never books, pays, or changes any record. It answers,
for a requested date and time interval: which seats are free, honouring
half-open intervals [start, end), overlapping occupancy records, approved
operating hours, explicit occupancy-coverage, membership *reporting* (kept
separate from physical availability), and an explicit demonstration clock in
Asia/Kolkata.

All business data comes from /fixtures (synthetic) — nothing is hard-coded here.

Result `status` is one of:
    "ok"                   valid, within hours and coverage; seats computed
    "invalid_request"      bad/missing arguments; see `errors`
    "closed"               interval outside approved operating hours
    "availability_unknown" date outside confirmed occupancy coverage

Use `sanitise_availability()` for anything shown to the model or the public:
it strips member ids, membership details, and internal notes.
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
    "load_operating_hours", "load_coverage",
    "intervals_overlap", "membership_status", "seat_conflicts",
    "query_availability", "sanitise_availability",
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


def load_operating_hours(path: str | Path) -> dict[int, tuple[time, time]]:
    """weekday index (Mon=0) -> (open, close)."""
    raw = _load_json(path)["weekly"]
    return {int(w["weekday"]): (_parse_time(w["open"]), _parse_time(w["close"])) for w in raw}


def load_coverage(path: str | Path) -> tuple[Optional[date], Optional[date]]:
    """Confirmed occupancy-coverage window (inclusive) from the occupancy file."""
    cov = _load_json(path).get("coverage")
    if not cov:
        return (None, None)
    return (_parse_date(cov["from"]), _parse_date(cov["to"]))


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
    """Validity of a membership on a given date. Pure; no side effects.

    This is advisory only. It never affects whether a seat is physically free.
    """
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
    # Full (internal) view. Member id / note are stripped by sanitise_availability.
    return {"start": o.start.strftime("%H:%M"), "end": o.end.strftime("%H:%M"),
            "member_id": o.member_id, "note": o.note}


def _require_str(request: dict, key: str, errors: list[str], required: bool) -> Optional[str]:
    if key not in request or request[key] is None:
        if required:
            errors.append(f"missing '{key}'")
        return None
    value = request[key]
    if not isinstance(value, str):
        errors.append(f"'{key}' must be a string (got {type(value).__name__})")
        return None
    return value


def query_availability(
    request: dict,
    *,
    seats: list[Seat],
    occupancy: list[Occupancy],
    clock: DemoClock,
    memberships: Optional[list[Membership]] = None,
    slots: Optional[dict[str, tuple[time, time]]] = None,
    operating_hours: Optional[dict[int, tuple[time, time]]] = None,
    coverage: tuple[Optional[date], Optional[date]] = (None, None),
) -> dict:
    """Answer a seat-availability question deterministically. Never raises on
    bad input: problems are reported in `errors` with status 'invalid_request'.
    """
    memberships = memberships or []
    errors: list[str] = []
    warnings: list[str] = []

    # --- argument types (fix 1) ---
    date_s = _require_str(request, "date", errors, required=True)
    slot_s = _require_str(request, "slot", errors, required=False) if request.get("slot") is not None else None
    seat_s = _require_str(request, "seat_id", errors, required=False) if request.get("seat_id") is not None else None
    member_s = _require_str(request, "member_id", errors, required=False) if request.get("member_id") is not None else None

    q_date: Optional[date] = None
    if date_s is not None:
        try:
            q_date = _parse_date(date_s)
        except ValueError:
            errors.append("invalid 'date' format (expected YYYY-MM-DD)")

    # --- interval: slot or explicit start/end ---
    q_start: Optional[time] = None
    q_end: Optional[time] = None
    if request.get("slot") is not None:
        # A slot was supplied. slot_s is the validated string (or None on type error).
        if slot_s is not None:
            if slots and slot_s in slots:
                q_start, q_end = slots[slot_s]
            else:
                errors.append(f"unknown slot '{slot_s}'")
    else:
        start_s = _require_str(request, "start", errors, required=True)
        end_s = _require_str(request, "end", errors, required=True)
        if start_s is not None:
            try:
                q_start = _parse_time(start_s)
            except ValueError:
                errors.append("invalid 'start' format (expected HH:MM)")
        if end_s is not None:
            try:
                q_end = _parse_time(end_s)
            except ValueError:
                errors.append("invalid 'end' format (expected HH:MM)")

    if q_start is not None and q_end is not None and q_start >= q_end:
        errors.append("'start' must be earlier than 'end'")

    # --- membership (advisory, independent of availability) ---
    membership = None
    if member_s is not None:
        on = q_date or clock.as_of.date()
        membership = membership_status(member_s, on, memberships)

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
        "operating_hours": None,
        "errors": errors,
        "warnings": warnings,
    }

    def _empty(status: str):
        return {**base, "valid_request": status != "invalid_request",
                "status": status, "seats": [], "inconsistencies": [],
                "summary": {"available": 0, "considered": 0}}

    if errors:
        return _empty("invalid_request")

    # --- operating hours (fix 2) ---
    oh_echo = None
    if operating_hours is not None:
        oh = operating_hours.get(q_date.weekday())
        if oh is None:
            warnings.append("no approved operating hours for this day")
            base["operating_hours"] = {"open": None, "close": None, "within": False}
            return _empty("closed")
        open_t, close_t = oh
        within = (q_start >= open_t) and (q_end <= close_t)
        oh_echo = {"open": open_t.strftime("%H:%M"), "close": close_t.strftime("%H:%M"), "within": within}
        base["operating_hours"] = oh_echo
        if not within:
            warnings.append(
                f"requested interval is outside operating hours "
                f"({open_t.strftime('%H:%M')}-{close_t.strftime('%H:%M')})"
            )
            return _empty("closed")

    # --- occupancy coverage (fix 3) ---
    cfrom, cto = coverage
    if cfrom is not None and cto is not None and not (cfrom <= q_date <= cto):
        warnings.append(
            f"date is outside confirmed occupancy coverage "
            f"({cfrom.isoformat()}..{cto.isoformat()}); availability is unknown"
        )
        return _empty("availability_unknown")

    # --- past-time flag (not an error; the clock is explicit) ---
    qs, qe = _dt(q_date, q_start), _dt(q_date, q_end)
    if qe <= clock.as_of:
        warnings.append("requested interval is entirely in the past relative to the demo clock")
    elif qs < clock.as_of:
        warnings.append("requested interval started before the demo clock 'now'")

    # --- which seats to consider ---
    if seat_s is not None:
        chosen = [s for s in seats if s.seat_id == seat_s]
        if not chosen:
            errors.append(f"unknown seat_id '{seat_s}'")
            return _empty("invalid_request")
    else:
        chosen = sorted(seats, key=lambda s: s.seat_id)

    # --- compute availability + flag membership/occupancy inconsistencies (fix 4) ---
    seat_rows = []
    inconsistencies: list[dict] = []
    for s in chosen:
        conflicts = seat_conflicts(s.seat_id, q_date, q_start, q_end, occupancy)
        for c in conflicts:
            if c.member_id is not None and memberships:
                ms = membership_status(c.member_id, q_date, memberships)
                if not ms["valid"]:  # False or None
                    # Physical seat stays occupied; we only FLAG this for review.
                    inconsistencies.append({
                        "seat_id": s.seat_id,
                        "start": c.start.strftime("%H:%M"),
                        "end": c.end.strftime("%H:%M"),
                        "member_id": c.member_id,
                        "issue": f"occupied by member with invalid membership ({ms['reason']})",
                    })
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
        "status": "ok",
        "seats": seat_rows,
        "inconsistencies": inconsistencies,
        "summary": {"available": available_count, "considered": len(seat_rows)},
    }


def sanitise_availability(result: dict) -> dict:
    """Public/model-facing view (fix 5).

    Strips member ids, membership details, internal notes, and the
    inconsistency review channel. Keeps busy time windows so an answer can say
    *when* a seat is taken, without saying *who* holds it.
    """
    return {
        "as_of": result["as_of"],
        "timezone": result["timezone"],
        "status": result["status"],
        "valid_request": result["valid_request"],
        "query": {k: result["query"].get(k) for k in ("date", "start", "end", "slot", "seat_id")},
        "operating_hours": result.get("operating_hours"),
        "errors": result["errors"],
        "warnings": result["warnings"],
        "summary": result["summary"],
        "seats": [
            {
                "seat_id": s["seat_id"], "label": s["label"], "zone": s["zone"],
                "available": s["available"],
                "busy": [{"start": c["start"], "end": c["end"]} for c in s["conflicts"]],
                "reason": s["reason"],
            }
            for s in result["seats"]
        ],
    }


# --------------------------------------------------------------------------
# Tiny manual demo (no network, no model). Run: python -m app.availability
# --------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    from .clock import load_demo_clock
    fx = Path(__file__).resolve().parent.parent / "fixtures"
    result = query_availability(
        {"date": "2026-10-27", "slot": "morning", "member_id": "M002"},
        seats=load_seats(fx / "seats.json"),
        occupancy=load_occupancy(fx / "occupancy.json"),
        memberships=load_memberships(fx / "memberships.json"),
        slots=load_slots(fx / "slots.json"),
        operating_hours=load_operating_hours(fx / "operating_hours.json"),
        coverage=load_coverage(fx / "occupancy.json"),
        clock=load_demo_clock(fx / "demo_clock.json"),
    )
    print("FULL (internal):")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\nSANITISED (model/public):")
    print(json.dumps(sanitise_availability(result), indent=2, ensure_ascii=False))
