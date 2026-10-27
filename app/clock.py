"""Explicit demonstration clock.

Availability is computed against this fixed instant, not the real system time,
so results are deterministic and reproducible in the demo and in tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class DemoClock:
    as_of: datetime        # timezone-aware
    timezone: ZoneInfo

    @property
    def tzname(self) -> str:
        return str(self.timezone)


def load_demo_clock(path: str | Path) -> DemoClock:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tz = ZoneInfo(data["timezone"])
    as_of = datetime.fromisoformat(data["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=tz)
    else:
        # Normalise to the configured zone so downstream comparisons are in IST.
        as_of = as_of.astimezone(tz)
    return DemoClock(as_of=as_of, timezone=tz)
