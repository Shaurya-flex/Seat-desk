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
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

# Retry + a bounded wall-clock deadline are enforced by run_guarded(). The REAL
# cancellation of a hung network call must come from the transport timeout
# (httpx.Timeout) in the live adapter: run_guarded cannot kill a worker thread,
# so a timed-out call may STILL BE RUNNING and may be billed. We never imply it
# was cancelled or free.
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
    """Raised when a guarded call exceeds its timeout/deadline.

    The underlying worker/request may still be running and may be billed — this
    is a wall-clock guard, not a cancellation.
    """


class OutstandingTracker:
    """Bounds concurrent + still-running (abandoned-after-timeout) requests.

    A timed-out worker thread cannot be killed, so it keeps its slot until it
    actually finishes (released via a done-callback). A retry therefore cannot
    launch an overlapping request once the cap is reached — acquire() raises.
    """

    def __init__(self, max_outstanding: int):
        self.max = max_outstanding
        self._n = 0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            if self._n >= self.max:
                raise LimitExceeded(
                    f"max outstanding requests ({self.max}) reached; a previous call may still be running")
            self._n += 1

    def release(self) -> None:
        with self._lock:
            self._n = max(0, self._n - 1)

    @property
    def outstanding(self) -> int:
        with self._lock:
            return self._n


_T = TypeVar("_T")


def run_guarded(fn: Callable[[], _T], *, retries: int, timeout_s: float,
                deadline_s: Optional[float] = None,
                is_retryable: Optional[Callable[[Exception], bool]] = None,
                on_retry: Optional[Callable[[int, Exception], None]] = None,
                tracker: Optional[OutstandingTracker] = None) -> _T:
    """Run fn() with a per-attempt wall-clock bound, an optional overall deadline,
    and classified retries.

    attempts = retries + 1. Returns within ~timeout_s even if fn keeps running: we
    do NOT block on executor shutdown. We also cannot kill the worker thread, so a
    timed-out fn may still execute to completion (and may be billed). The real fix
    for network hangs is a transport-level timeout in fn itself.

    is_retryable(e): if provided and returns False, the exception is raised
    immediately (e.g. do not retry a 4xx/auth error). Timeouts are always retryable
    up to the attempt/deadline budget.
    """
    attempts = max(1, retries + 1)
    start = time.monotonic()
    last: Exception = RuntimeError("run_guarded: no attempt made")
    for i in range(attempts):
        if deadline_s is not None:
            remaining = deadline_s - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutExceeded(f"overall deadline {deadline_s}s exceeded")
            per = min(timeout_s, remaining)
        else:
            per = timeout_s

        if tracker is not None:
            tracker.acquire()                      # raises LimitExceeded if over cap (incl. abandoned)
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        fut = ex.submit(fn)
        if tracker is not None:
            fut.add_done_callback(lambda f: tracker.release())   # releases even if abandoned-then-finished
        try:
            result = fut.result(timeout=per)
            ex.shutdown(wait=False)
            return result
        except concurrent.futures.TimeoutError:
            ex.shutdown(wait=False, cancel_futures=True)   # do not block; worker may still run
            last = TimeoutExceeded(
                f"call exceeded {per:.3f}s; the request may still be running and may be billed")
        except Exception as e:  # noqa: BLE001
            ex.shutdown(wait=False)
            last = e
            if is_retryable is not None and not is_retryable(e):
                raise
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
