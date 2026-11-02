"""Live speech-to-text adapter for Muse Voice Transcribe (file endpoint).

Contract verified against the official docs (dev.meta.ai/docs/speech-to-text,
2 Nov 2026):

* POST {base}/asr/transcribe, Authorization: Bearer <key>
* multipart/form-data: part "request" = JSON settings, part "audio" = WAV file
* WAV must be RIFF/WAVE, mono, 16-bit integer PCM, 16 kHz or 24 kHz
* limits: body <= 32 MB (413), audio <= 10 minutes (400)
* response JSON: transcript, audioDurationMs, turns[{turnId,startMs,endMs,
  transcript,speaker}]
* languageBias / keywords steer recognition (set per request, not forced)
* pricing: $0.18 per hour of audio processed; failed requests are not billed
* Hindi is among the 25 supported languages (code-switching supported)

Same safety posture as LiveModelAdapter: refuses unverified endpoints, never
falls back silently, one explicit transport timeout, and a transcript is NEVER
treated as confirmed input -- it goes through intake.confirm_transcript first.
"""
from __future__ import annotations

import io
import json
import struct
import urllib.parse
import wave
from pathlib import Path

from .intake import Transcript

MAX_BODY_BYTES = 32 * 1024 * 1024          # 413 past this
MAX_AUDIO_SECONDS = 10 * 60                # 400 past this
ALLOWED_RATES = (16000, 24000)
PRICE_PER_HOUR_USD = 0.18


class TranscriptionError(RuntimeError):
    pass


def validate_wav(path: str | Path) -> dict:
    """Check the file against the documented constraints BEFORE any upload."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_BODY_BYTES:
        raise TranscriptionError(f"file is {size} bytes; the endpoint rejects bodies over 32 MB")
    try:
        with wave.open(str(p), "rb") as w:
            ch, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError, struct.error) as e:
        raise TranscriptionError(f"not a readable RIFF/WAVE file: {e}")
    duration_s = frames / float(rate or 1)
    problems = []
    if ch != 1:
        problems.append(f"channels={ch} (needs mono)")
    if width != 2:
        problems.append(f"sample width={width*8}-bit (needs 16-bit integer PCM)")
    if rate not in ALLOWED_RATES:
        problems.append(f"rate={rate} Hz (needs 16000 or 24000)")
    if duration_s > MAX_AUDIO_SECONDS:
        problems.append(f"duration={duration_s:.0f}s (max 600s)")
    if problems:
        raise TranscriptionError(
            "WAV does not meet the documented contract: " + "; ".join(problems)
            + ". Convert first, e.g. ffmpeg -i in.m4a -ac 1 -ar 16000 -sample_fmt s16 out.wav")
    return {"bytes": size, "seconds": round(duration_s, 2), "rate": rate,
            "estimated_cost_usd": round(duration_s / 3600 * PRICE_PER_HOUR_USD, 6)}


class LiveTranscriber:
    """One-shot, read-only file transcription. No retries, no fallback."""

    simulated = False
    mock = False
    ALLOWED_HOSTS = ("api.meta.ai",)

    def __init__(self, base_url: str | None, api_key: str | None,
                 model: str = "muse-voice-transcribe-1.0", *, verified: bool = False,
                 timeout_s: float = 60.0, language_bias: list[str] | None = None,
                 keywords: list[str] | None = None, http_client=None):
        self.base_url = base_url
        self._api_key = api_key
        self.model = model
        self.verified = verified
        self.timeout_s = timeout_s
        self.language_bias = language_bias or ["Hindi", "English"]
        self.keywords = keywords or []
        self._client = http_client
        self.transport = "mocked-http" if http_client is not None else "live-http"
        self.name = f"live:{model}"
        self.last_meta: dict | None = None

    def _guard(self) -> None:
        if not self.verified:
            raise TranscriptionError("LiveTranscriber not enabled: endpoint/model not re-verified")
        u = urllib.parse.urlparse(self.base_url or "")
        if u.scheme != "https" or u.hostname not in self.ALLOWED_HOSTS:
            raise TranscriptionError(f"refusing endpoint: {self.base_url!r}")
        if not self._api_key:
            raise TranscriptionError("no API key configured")

    def request_part(self) -> dict:
        """The 'request' JSON part. mode/model verified from the docs; PUSH_TO_TALK
        is the non-diarized file mode (turns come back empty, transcript is full)."""
        part: dict = {"mode": "PUSH_TO_TALK", "model": self.model}
        if self.language_bias:
            part["languageBias"] = self.language_bias
        if self.keywords:
            part["keywords"] = self.keywords
        return part

    def transcribe_file(self, path: str | Path) -> Transcript:
        self._guard()
        info = validate_wav(path)
        import httpx
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout_s))
        try:
            with open(path, "rb") as fh:
                resp = client.post(
                    self.base_url.rstrip("/") + "/asr/transcribe",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    data={"request": json.dumps(self.request_part())},
                    files={"audio": (Path(path).name, fh, "audio/wav")},
                )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                client.close()
        text = data.get("transcript")
        if not isinstance(text, str) or not text.strip():
            raise TranscriptionError("response carried no transcript text")
        self.last_meta = {
            "audio": info,
            "audio_duration_ms": data.get("audioDurationMs"),
            "turns": len(data.get("turns") or []),
            "billed_estimate_usd": info["estimated_cost_usd"],
        }
        # NEVER confirmed automatically: the speaker must confirm/correct it
        # (intake.confirm_transcript) before the text enters the enquiry workflow.
        return Transcript(text=text, source="live_audio",
                          needs_confirmation=True, mock=False)
