"""UNFINISHED / MOCK scaffolding: audio intake, transcript confirmation, staff re-check.

This is deliberately not wired into the primary text flow. No real speech model is
called. It exists so the audio path, the confirm-before-use step, and the
staff-proposal re-check have a shape to fill in once `muse-voice-transcribe` is
integrated via a verified LiveModelAdapter-style HTTP call. Every piece is labelled
mock/unfinished so nothing here is mistaken for working transcription.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Transcript:
    text: str
    source: str            # "typed" | "mock_audio"
    needs_confirmation: bool
    mock: bool


def typed_transcript(text: str) -> Transcript:
    """The primary, finished path: typed Hindi/English/Hinglish needs no transcription."""
    return Transcript(text=text, source="typed", needs_confirmation=False, mock=False)


class MockTranscriber:
    """MOCK — does NOT decode audio or call a speech model. Placeholder only."""

    name = "mock:transcriber-v0"
    mock = True

    def transcribe(self, audio_ref: str) -> Transcript:
        # Never fabricate words as 'heard'; return a marker requiring confirmation.
        return Transcript(
            text=f"[mock transcript of {audio_ref} — UNVERIFIED, confirm before use]",
            source="mock_audio", needs_confirmation=True, mock=True,
        )


def confirm_transcript(transcript: Transcript, confirmed_text: str | None = None) -> Transcript:
    """Customer/staff confirms or corrects the transcript before it is used."""
    text = confirmed_text if confirmed_text is not None else transcript.text
    return Transcript(text=text, source=transcript.source, needs_confirmation=False, mock=transcript.mock)


def staff_recheck(query: dict, tool) -> dict:
    """Staff-proposal re-check: independently re-run availability right before a human
    proposal, so a stale answer is caught. Read-only."""
    from .verify import _query_to_request
    fresh = tool.get_availability(_query_to_request(query))
    return {"rechecked": True, "status": fresh.get("status"), "summary": fresh.get("summary")}
