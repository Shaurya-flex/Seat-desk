"""Sanitised, read-only availability tool exposed to the workflow/model.

The tool returns ONLY the sanitised availability view (no member ids, no
membership details, no internal notes). It never writes anything.
"""
from __future__ import annotations

from pathlib import Path

from .availability import (
    query_availability, sanitise_availability,
    load_seats, load_memberships, load_occupancy, load_slots,
    load_operating_hours, load_coverage,
)
from .clock import load_demo_clock, DemoClock


class ToolError(Exception):
    """Raised when the tool cannot produce a result (e.g. datasource down)."""


class AvailabilityTool:
    name = "get_availability"

    def __init__(self, fixtures_dir: str | Path, *, fail: bool = False):
        fx = Path(fixtures_dir)
        self._seats = load_seats(fx / "seats.json")
        self._memberships = load_memberships(fx / "memberships.json")
        self._occupancy = load_occupancy(fx / "occupancy.json")
        self._slots = load_slots(fx / "slots.json")
        self._hours = load_operating_hours(fx / "operating_hours.json")
        self._coverage = load_coverage(fx / "occupancy.json")
        self._clock: DemoClock = load_demo_clock(fx / "demo_clock.json")
        self.fail = fail  # test hook to simulate a tool failure

    @property
    def clock(self) -> DemoClock:
        return self._clock

    def get_availability(self, request: dict) -> dict:
        """Return the SANITISED availability view. Read-only."""
        if self.fail:
            raise ToolError("availability datasource is unavailable")
        full = query_availability(
            request,
            seats=self._seats, occupancy=self._occupancy,
            memberships=self._memberships, slots=self._slots,
            operating_hours=self._hours, coverage=self._coverage,
            clock=self._clock,
        )
        return sanitise_availability(full)
