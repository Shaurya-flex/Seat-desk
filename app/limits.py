"""Enforced safety bounds: retries, tool calls, output size, request volume.

These are hard guards in code (they raise / truncate), independent of any
provider billing alert. Billing alerts are notifications, not caps.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    max_retries: int = 2
    max_tool_calls_per_turn: int = 3
    max_output_tokens: int = 512
    max_requests_per_session: int = 50


class LimitExceeded(Exception):
    """Raised when a hard limit is hit."""


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


def cap_output(text: str, max_tokens: int) -> str:
    """Approximate output cap by whitespace tokens. Deterministic."""
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text
    return " ".join(tokens[:max_tokens]) + " … [truncated]"
