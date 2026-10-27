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

from dataclasses import dataclass

# Retry limiting is declared but NOT yet enforced anywhere. Do not claim it is.
RETRY_ENFORCEMENT = "planned"


@dataclass(frozen=True)
class Limits:
    # enforced
    max_tool_calls_per_turn: int = 3
    max_requests_per_session: int = 50
    # provider generation parameter (passed to the model; not a truncator of our text)
    max_output_tokens: int = 512
    # display-only, character-based; never applied to verified answers
    max_display_chars: int = 2000
    # PLANNED — not enforced yet (see RETRY_ENFORCEMENT)
    max_retries: int = 2


class LimitExceeded(Exception):
    """Raised when a hard, enforced limit is hit."""


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
