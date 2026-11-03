"""Mocked-HTTP contract tests for the Muse Voice Transcribe file adapter.
No network, no spend: these prove the request shape and the safety posture."""
import io
import json
import struct
import wave
from pathlib import Path

import pytest

from app.intake import confirm_transcript
from app.voice import LiveTranscriber, TranscriptionError, validate_wav

BASE = "https://api.meta.ai/v1"


def _wav(path: Path, seconds=1.0, rate=16000, channels=1, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(width); w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return path


class _Resp:
    status_code = 200
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class _Client:
    def __init__(self, payload): self._payload, self.sent = payload, None
    def post(self, url, headers=None, data=None, files=None):
        self.sent = {"url": url, "headers": headers, "data": data,
                     "files": dict(files or {})}
        return _Resp(self._payload)


def _adapter(client, **kw):
    return LiveTranscriber(BASE, "k", verified=True, http_client=client, **kw)


def test_refuses_unverified_and_bad_hosts(tmp_path):
    f = _wav(tmp_path / "a.wav")
    with pytest.raises(TranscriptionError):
        LiveTranscriber(BASE, "k", verified=False).transcribe_file(f)
    with pytest.raises(TranscriptionError):
        LiveTranscriber("https://evil.example/v1", "k", verified=True).transcribe_file(f)


def test_multipart_contract_and_unconfirmed_transcript(tmp_path):
    f = _wav(tmp_path / "a.wav")
    c = _Client({"transcript": "नमस्ते", "audioDurationMs": 1000, "turns": []})
    t = _adapter(c).transcribe_file(f)
    assert c.sent["url"].endswith("/v1/asr/transcribe")
    name, body, ctype = c.sent["files"]["request"]
    assert name is None and ctype == "application/json"   # docs: request part is JSON-typed
    req = json.loads(body)
    assert req["mode"] == "PUSH_TO_TALK" and req["model"] == "muse-voice-transcribe-1.0"
    assert req["audioEncoding"] == "WAV"                   # required by the file example
    assert "Hindi" in req["languageBias"]
    assert c.sent["files"]["audio"][0] == "a.wav"
    assert c.sent["data"] is None                          # nothing rides outside the two parts
    # a live transcript is NEVER confirmed automatically
    assert t.needs_confirmation and not t.mock and t.source == "live_audio"
    done = confirm_transcript(t, "नमस्ते जी")
    assert not done.needs_confirmation and done.text == "नमस्ते जी"


def test_rejects_wrong_format_wavs(tmp_path):
    with pytest.raises(TranscriptionError):   # stereo
        validate_wav(_wav(tmp_path / "s.wav", channels=2))
    with pytest.raises(TranscriptionError):   # 8 kHz
        validate_wav(_wav(tmp_path / "r.wav", rate=8000))
    with pytest.raises(TranscriptionError):   # not a wav
        p = tmp_path / "x.wav"; p.write_bytes(b"not audio"); validate_wav(p)


def test_empty_transcript_is_an_error_not_a_fallback(tmp_path):
    f = _wav(tmp_path / "a.wav")
    with pytest.raises(TranscriptionError):
        _adapter(_Client({"transcript": "", "turns": []})).transcribe_file(f)


def test_cost_estimate_from_duration(tmp_path):
    info = validate_wav(_wav(tmp_path / "a.wav", seconds=60))
    assert info["seconds"] == 60.0
    assert abs(info["estimated_cost_usd"] - 0.003) < 1e-9


class _BadResp:
    status_code = 400
    text = '{"error":"audioEncoding missing"}'
    def raise_for_status(self): raise AssertionError("should not be reached")
    def json(self): raise AssertionError("should not be reached")


class _BadClient:
    def post(self, url, headers=None, data=None, files=None): return _BadResp()


def test_provider_400_body_is_surfaced(tmp_path):
    f = _wav(tmp_path / "a.wav")
    with pytest.raises(TranscriptionError) as e:
        _adapter(_BadClient()).transcribe_file(f)
    assert "HTTP 400" in str(e.value) and "audioEncoding" in str(e.value)
