#!/usr/bin/env python3
"""One real Hindi audio transcription through Muse Voice Transcribe, then an
explicit human confirmation step. Voice is NOT wired into the main text flow;
this demonstrates: audio file -> transcript -> speaker confirms/corrects ->
confirmed text is ready for the ordinary typed workflow.

Safety: --estimate validates the WAV and prices it with NO network call.
--run requires --i-approve-spend and MODEL_API_KEY (shell env, or ROOT/.env
loaded explicitly). One request, no retries, no fallback; evidence is
sanitised. Failed requests are not billed per the official pricing page.

Usage:
    python scripts/voice_once.py --estimate --audio path/to/enquiry.wav
    python scripts/voice_once.py --run --i-approve-spend --audio path/to/enquiry.wav
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.intake import confirm_transcript                      # noqa: E402
from app.voice import LiveTranscriber, validate_wav, PRICE_PER_HOUR_USD  # noqa: E402
from live_once import BASE_URL, KEY_VAR, git_commit, load_key, redact    # noqa: E402

MODEL = "muse-voice-transcribe-1.0"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--estimate", action="store_true")
    g.add_argument("--run", action="store_true")
    ap.add_argument("--i-approve-spend", action="store_true")
    ap.add_argument("--audio", required=True, help="WAV file: mono, 16-bit PCM, 16/24 kHz, <=10 min")
    a = ap.parse_args()

    tr = LiveTranscriber(BASE_URL, api_key=None, model=MODEL, verified=False,
                         keywords=["Rasra Library", "Seat Desk", "सीट"])
    info = validate_wav(a.audio)      # offline validation + duration pricing

    if a.estimate:
        print(json.dumps({
            "mode": "ESTIMATE ONLY -- no network call, no credits consumed",
            "provider": "Meta Model API", "model": MODEL,
            "endpoint": "POST /v1/asr/transcribe (multipart: request JSON + audio WAV)",
            "audio": info,
            "request_part": tr.request_part(),
            "pricing_basis": f"${PRICE_PER_HOUR_USD}/hour of audio, billed per whole second; "
                             "failed requests are not billed (official pricing page)",
            "note": "The transcript is NEVER used unconfirmed: the speaker confirms or "
                    "corrects it before it can enter the typed enquiry workflow.",
        }, ensure_ascii=False, indent=2))
        return 0

    if not a.i_approve_spend:
        print("REFUSED: --run is billed and requires --i-approve-spend.", file=sys.stderr)
        return 3
    key = load_key()
    if not key:
        print(f"ERROR: no API key found. Put {KEY_VAR}=... in your shell or {ROOT/'.env'}.",
              file=sys.stderr)
        return 2

    live = LiveTranscriber(BASE_URL, api_key=key, model=MODEL, verified=True,
                           keywords=tr.keywords)
    started = time.monotonic()
    error = None
    transcript = None
    try:
        transcript = live.transcribe_file(a.audio)       # exactly one request
    except Exception as e:
        error = {"type": type(e).__name__, "message": redact(str(e), key)}
    latency_ms = round((time.monotonic() - started) * 1000, 1)

    confirmed = None
    if transcript and sys.stdin.isatty():
        print(f"\nTRANSCRIPT (unconfirmed): {transcript.text}\n")
        ans = input("Press Enter to confirm, or type the corrected text: ").strip()
        confirmed = confirm_transcript(transcript, ans or None)

    record = {
        "result": "TRANSCRIBED" if transcript else "ERROR",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": git_commit(),
        "provider": "Meta Model API", "model": MODEL,
        "transport": live.transport, "latency_ms": latency_ms,
        "audio": info,
        "transcript_unconfirmed": transcript.text if transcript else None,
        "confirmed_text": confirmed.text if confirmed else None,
        "confirmation_state": ("confirmed" if confirmed else
                               "pending -- transcript must be confirmed before use"),
        "meta": live.last_meta, "error": error,
        "note": "Synthetic demo enquiry audio; not a real customer recording.",
    }
    out = ROOT / "evidence" / "voice_run.json"
    out.parent.mkdir(exist_ok=True)
    text = redact(json.dumps(record, ensure_ascii=False, indent=2), key)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSanitised evidence written to {out}", file=sys.stderr)
    return 0 if transcript else 1


if __name__ == "__main__":
    raise SystemExit(main())
