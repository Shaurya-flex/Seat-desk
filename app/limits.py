"""Safety bounds.

Two different things, kept separate:

* Provider generation limits — parameters we would pass to the model request
  (e.g. max_output_tokens). These bound what the PROVIDER generates. They are
  NOT used to chop our own already-verified answers.
* Display-length limit — a character budget for showing long, untrusted free
  text in a UI. It never touches a verified grounded answer (that would risk
  removing a qualification).

Enforced in code now: request volume per session, tool calls per turn.
Planned (not yet enforced in code): retry limiting — see RETRY_ENFORCEMENT.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

# Retry + timeout are enforced by run_guarded() (below), which the live adapter
# uses on every provider call. They are not exercised while the live adapter is
# disabled, but the mechanism is real and tested.
RETRY_ENFORCEMENT = "enforced_in_run_guarded"


@dataclass(frozen=True)
class Limits:
    # enforced per turn / session
    max_tool_calls_per_turn: int = 3
    max_requests_per_session: int = 50
    # enforced on provider calls via run_guarded()
    max_retries: int = 2
    max_timeout_s: float = 20.0
    # provider generation parameter (passed to the model; not a truncator of our text)
    max_output_tokens: int = 512
    # display-only, character-based; never applied to verified answers
    max_display_chars: int = 2000


class LimitExceeded(Exception):
    """Raised when a hard, enforced limit is hit."""


class TimeoutExceeded(LimitExceeded):
    """Raised when a guarded call exceeds its timeout."""


_T = TypeVar("_T")


def run_guarded(fn: Callable[[], _T], *, retries: int, timeout_s: float,
                on_retry: Optional[Callable[[int, Exception], None]] = None) -> _T:
    """Run fn() with a hard per-attempt timeout and a bounded number of retries.

    attempts = retries + 1. Raises TimeoutExceeded on timeout, or the last
    exception after retries are exhausted. Note: a timed-out worker thread cannot
    be force-killed, so fn must be side-effect-safe to abandon.
    """
    attempts = max(1, retries + 1)
    last: Exception = RuntimeError("run_guarded: no attempt made")
    for i in range(attempts):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(fn).result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            last = TimeoutExceeded(f"call exceeded {timeout_s}s")
        except Exception as e:  # noqa: BLE001 - bounded retry on any provider error
            last = e
        if on_retry and i < attempts - 1:
            on_retry(i, last)
    raise last


class SessionBudget:
    """Tracks request volume across a session and tool calls within a turn."""

    def __init__(self, limits: Limits):
        self.limits = limits
        self.requests = 0
        self._tool_calls_this_turn = 0

    def start_turn(self) -> None:
        if self.requests >= self.limits.max_requests_per_session:
            raise LimitExceeded(
                f"request volume limit reached ({self.limits.max_requests_per_session})"
            )
        self.requests += 1
        self._tool_calls_this_turn = 0

    def spend_tool_call(self) -> None:
        if self._tool_calls_this_turn >= self.limits.max_tool_calls_per_turn:
            raise LimitExceeded(
                f"tool-call limit reached ({self.limits.max_tool_calls_per_turn} per turn)"
            )
        self._tool_calls_this_turn += 1

    @property
    def tool_calls_this_turn(self) -> int:
        return self._tool_calls_this_turn


def clamp_display(text: str, max_chars: int) -> str:
    """Display-only character clamp for long, UNTRUSTED free text.

    Never call this on a verified grounded answer: clamping could drop a
    qualification. For display of long free text only.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " … [display-truncated]"
