"""Seat Desk local web interface.

One small, local-only server (binds 127.0.0.1) over the EXISTING workflow:
typed or spoken enquiry -> (transcript explicitly confirmed by the person) ->
Assistant.handle() -> grounded answer with the resolved date/interval, the
deterministic availability trace, approved-policy citations, clarification,
and the explicitly UNSENT human handoff.

Honesty rules enforced here:
* The availability trace is a deterministic tool result and is labelled as
  such -- it is never presented as a policy citation.
* A transcript is NEVER auto-confirmed; the UI must send the confirmed text.
* Live calls are billed. This process keeps app-level counters and refuses
  past its caps; these are APPLICATION counters, not provider-enforced caps.
* The API key stays server-side (env / .env). It never reaches the page.

Run:  python -m app.server            then open  http://127.0.0.1:8777
Mode: mock (default, free, keyword understanding) or live (muse-spark-1.3
extraction; muse-voice-transcribe-1.0 for audio) when MODEL_API_KEY is set.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .model import make_model
from .retrieval import load_pack
from .tools import AvailabilityTool
from .voice import LiveTranscriber, TranscriptionError, validate_wav
from .workflow import Assistant

ROOT = Path(__file__).resolve().parent.parent
UI_PATH = Path(__file__).resolve().parent / "ui.html"

BASE_URL = "https://api.meta.ai/v1"
EXTRACT_MODEL = "muse-spark-1.3"
VOICE_MODEL = "muse-voice-transcribe-1.0"

# Application-level spending guards for one server process. These stop THIS
# process from making more billed calls; they are not provider-side caps.
LIVE_EXTRACT_CAP = int(os.environ.get("SEATDESK_LIVE_CAP", "25"))
TRANSCRIBE_CAP = int(os.environ.get("SEATDESK_VOICE_CAP", "10"))


def _load_key() -> str | None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass
    return os.environ.get("MODEL_API_KEY")


def _redact(text: str, key: str | None) -> str:
    if not text:
        return text
    if key:
        text = text.replace(key, "[REDACTED_KEY]")
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    return text


class DeskState:
    """All behaviour behind the HTTP layer, testable without sockets."""

    def __init__(self, key: str | None = None):
        self.key = key if key is not None else _load_key()
        self.lock = threading.Lock()
        self.live_extract_calls = 0
        self.transcribe_calls = 0
        self._assistants: dict[str, Assistant] = {}

    # -- assistants -------------------------------------------------------
    def _build(self, mode: str) -> Assistant:
        pack = load_pack(ROOT / "knowledge" / "policies.sample.json")
        tool = AvailabilityTool(ROOT / "fixtures")
        if mode == "live":
            model = make_model(
                "live", base_url=BASE_URL, model_id=EXTRACT_MODEL,
                api_key=self.key, verified=True, retries=0,
                timeout_s=20.0, deadline_s=25.0, max_output_tokens=2048,
                max_outstanding=1, reasoning_effort="minimal")
        else:
            model = make_model("mock")
        return Assistant(pack=pack, tool=tool, model=model)

    def assistant(self, mode: str) -> Assistant:
        if mode not in ("mock", "live"):
            raise ValueError(f"unknown mode: {mode!r}")
        if mode == "live" and not self.key:
            raise RuntimeError("live mode needs MODEL_API_KEY in the server environment / .env")
        if mode not in self._assistants:
            self._assistants[mode] = self._build(mode)
        return self._assistants[mode]

    def reset(self, mode: str) -> None:
        self._assistants.pop(mode, None)

    # -- API operations ---------------------------------------------------
    def status(self) -> dict:
        return {
            "live_available": bool(self.key),
            "extraction_model": EXTRACT_MODEL, "voice_model": VOICE_MODEL,
            "provider": "Meta Model API",
            "live_extract_calls": self.live_extract_calls, "live_extract_cap": LIVE_EXTRACT_CAP,
            "transcribe_calls": self.transcribe_calls, "transcribe_cap": TRANSCRIBE_CAP,
            "caps_note": "Application counters for this server process only -- not provider-enforced spending caps.",
            "data_note": "Historical synthetic demonstration data (fixture clock 2026-10-27 IST); not real Rasra Library records.",
        }

    def enquire(self, text: str, mode: str) -> dict:
        text = (text or "").strip()
        if not text:
            return {"error": {"type": "EmptyEnquiry", "message": "type or confirm an enquiry first"}}
        if len(text) > 2000:
            return {"error": {"type": "InputBound", "message": "enquiry exceeds the 2000-character bound"}}
        with self.lock:
            if mode == "live":
                if self.live_extract_calls >= LIVE_EXTRACT_CAP:
                    return {"error": {"type": "AppSpendCap",
                                      "message": f"app-level cap reached ({LIVE_EXTRACT_CAP} live extractions this run); restart the server to continue"}}
                self.live_extract_calls += 1
            try:
                a = self.assistant(mode)
                resp = a.handle(text)
            except Exception as e:
                return {"error": {"type": type(e).__name__, "message": _redact(str(e), self.key)}}
        model = a.model
        meta = getattr(model, "last_meta", None) if mode == "live" else None
        return {
            "mode": mode,
            "enquiry": text,
            "route": resp["route"], "lang": resp["lang"],
            "answer": resp["answer"], "clarification": resp["clarification"],
            "citations": resp["citations"],
            "availability": resp["availability"],
            "resolved_query": a.last_availability,
            "handoff": resp["handoff"],
            "warnings": resp["warnings"],
            "transparency": resp["transparency"],
            "provider": resp["provider"], "simulated": resp["simulated"],
            "transport": resp["transport"],
            "usage": (meta or {}).get("usage"),
            "models": {"extraction": (EXTRACT_MODEL if mode == "live" else "mock rule-based (no Meta call)"),
                       "facts": "deterministic code over synthetic fixtures (never a model)"},
        }

    def transcribe(self, wav_bytes: bytes) -> dict:
        if not self.key:
            return {"error": {"type": "NoKey", "message": "transcription needs MODEL_API_KEY server-side"}}
        with self.lock:
            if self.transcribe_calls >= TRANSCRIBE_CAP:
                return {"error": {"type": "AppSpendCap",
                                  "message": f"app-level cap reached ({TRANSCRIBE_CAP} transcriptions this run)"}}
            self.transcribe_calls += 1
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(wav_bytes); tmp.close()
            info = validate_wav(tmp.name)
            tr = LiveTranscriber(BASE_URL, api_key=self.key, model=VOICE_MODEL, verified=True,
                                 keywords=["Rasra Library", "Seat Desk", "सीट"])
            t = tr.transcribe_file(tmp.name)
            return {"transcript": t.text, "needs_confirmation": True,
                    "model": VOICE_MODEL, "audio": info, "meta": tr.last_meta,
                    "note": "UNCONFIRMED transcript -- confirm or correct it before it is used."}
        except TranscriptionError as e:
            return {"error": {"type": "TranscriptionError", "message": _redact(str(e), self.key)}}
        except Exception as e:
            return {"error": {"type": type(e).__name__, "message": _redact(str(e), self.key)}}
        finally:
            os.unlink(tmp.name)


def make_handler(state: DeskState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/index"):
                body = UI_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/status":
                self._json(state.status())
            else:
                self._json({"error": {"type": "NotFound", "message": self.path}}, 404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 40 * 1024 * 1024:
                self._json({"error": {"type": "TooLarge", "message": "body over 40 MB"}}, 413)
                return
            raw = self.rfile.read(n)
            if self.path == "/api/enquire":
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError:
                    self._json({"error": {"type": "BadJSON", "message": "invalid JSON"}}, 400)
                    return
                self._json(state.enquire(payload.get("text", ""), payload.get("mode", "mock")))
            elif self.path == "/api/transcribe":
                self._json(state.transcribe(raw))
            elif self.path == "/api/reset":
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except ValueError:
                    payload = {}
                state.reset(payload.get("mode", "mock"))
                self._json({"ok": True})
            else:
                self._json({"error": {"type": "NotFound", "message": self.path}}, 404)

    return Handler


def main(port: int = 8777):
    state = DeskState()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    live = "LIVE available (key found)" if state.key else "mock only (no MODEL_API_KEY)"
    print(f"Seat Desk running: http://127.0.0.1:{port}   [{live}]")
    print("Historical synthetic demonstration data; live calls are billed and counted.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
