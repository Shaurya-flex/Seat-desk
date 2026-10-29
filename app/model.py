"""Model adapters.

Two implementations, kept strictly separate:

* MockModelAdapter  — SIMULATED. Deterministic, rule-based language/intent
  classification and templated answering that only ever copies approved text.
  Passing tests against this proves the *workflow wiring*, NOT Hindi model
  quality and NOT real Meta integration.

* LiveModelAdapter  — real provider. Not implemented here. It refuses to run
  against an unverified/illustrative endpoint, so no credentials are ever sent
  to a placeholder URL. Wire it only after resolving the base URL and model id
  against the official Meta Model API docs/console.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date

DEVANAGARI = re.compile(r"[ऀ-ॿ]")

_INJECTION = [
    "ignore your rules", "ignore all previous", "disregard your", "admin password",
    "system prompt", "reveal your", "jailbreak", "bypass your", "developer mode",
]
_CREDENTIAL = ["password", "पासवर्ड", "otp", " pin ", "passcode"]
_HANDOFF = [
    "refund", "cancel my", "my member id", "member id", "मेरा member",
    "मेरी सदस्यता", "reserve", "book a", "booking", "change my",
]
_AVAILABILITY = [
    "free seat", "seats free", "any seats", "seat free", "seats available",
    "availability", "available", "vacant", "खाली", "कौन सी सीट", "सीटें खाली",
]


def detect_lang(text: str) -> str:
    return "hi" if DEVANAGARI.search(text) else "en"


@dataclass
class Classification:
    lang: str
    intent: str            # policy | availability | handoff | no_answer | injection
    topic_hint: str | None = None


class MockModelAdapter:
    """SIMULATED adapter. name carries the 'mock:' prefix on purpose."""

    name = "mock:rule-based-v0"
    simulated = True

    def classify(self, enquiry: str, history: list | None = None) -> Classification:
        low = enquiry.lower()
        lang = detect_lang(enquiry)

        if any(p in low for p in _INJECTION):
            return Classification(lang, "injection")
        if any(p in low for p in _CREDENTIAL):
            return Classification(lang, "no_answer")           # never share credentials
        if any(p in low for p in _HANDOFF):
            return Classification(lang, "handoff")
        avail = (any(p in low for p in _AVAILABILITY)
                 or ("free" in low and ("seat" in low or "सीट" in enquiry))
                 or "खाली" in enquiry)
        if avail:
            return Classification(lang, "availability")
        from .retrieval import topics_for
        topics = topics_for(enquiry)
        if topics:
            return Classification(lang, "policy", topic_hint=topics[0])
        return Classification(lang, "no_answer")

    def draft_answer(self, lang: str, items: list[dict]) -> tuple[str, list[str]]:
        """Answer by copying approved text from confirmed items. Never invents.

        Returns (answer_text, cited_ids).
        """
        if not items:
            return ("", [])
        parts, cites = [], []
        for it in items:
            text = it.get(f"answer_{lang}") or it.get("answer_en") or it.get("answer_hi")
            if text:
                parts.append(text)
                cites.append(it["id"])
        return (" ".join(parts), cites)


ALLOWED_INTENTS = ("policy", "availability", "handoff", "no_answer", "injection", "clarify")
ALLOWED_TOOLS = ("get_availability",)   # read-only only; never book/pay/write


class ExtractionError(ValueError):
    """The provider response did not match the required structured schema."""


class ToolNotAllowed(ValueError):
    """The provider proposed a tool call not on the read-only allowlist."""


ALLOWED_SLOTS = ("morning", "afternoon", "evening")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SEAT_RE = re.compile(r"^S\d{1,3}$")


@dataclass
class ExtractedFields:
    """Typed, validated extraction from the model. Operational facts are NOT here —
    only the structured query inputs the deterministic tool/policy path consumes."""
    lang: str
    intent: str
    date: str | None = None
    start: str | None = None
    end: str | None = None
    slot: str | None = None
    seat_id: str | None = None


def validate_fields(f: "ExtractedFields") -> "ExtractedFields":
    """Reject malformed fields (types, allowed values, date, interval, seat) — never
    accept-and-pass. Returns the same object when valid."""
    if f.lang not in ("hi", "en"):
        raise ExtractionError(f"invalid lang: {f.lang!r}")
    if f.intent not in ALLOWED_INTENTS:
        raise ExtractionError(f"invalid intent: {f.intent!r}")
    if f.date is not None:
        if not isinstance(f.date, str) or not _DATE_RE.match(f.date):
            raise ExtractionError(f"bad date format: {f.date!r}")
        try:
            date.fromisoformat(f.date)
        except ValueError:
            raise ExtractionError(f"invalid date: {f.date!r}")
    for t in (f.start, f.end):
        if t is not None and (not isinstance(t, str) or not _TIME_RE.match(t)):
            raise ExtractionError(f"bad time format: {t!r}")
    if f.start and f.end and f.start >= f.end:
        raise ExtractionError(f"start >= end: {f.start} {f.end}")
    if f.slot is not None and f.slot not in ALLOWED_SLOTS:
        raise ExtractionError(f"invalid slot: {f.slot!r}")
    if f.seat_id is not None and (not isinstance(f.seat_id, str) or not _SEAT_RE.match(f.seat_id)):
        raise ExtractionError(f"invalid seat_id: {f.seat_id!r}")
    return f


class LiveModelAdapter:
    """Real provider adapter (chat-completions style).

    The request/response schema here is the hosted chat-completions convention and
    MUST be re-verified against the official Meta Model API docs before real use.
    It refuses unverified/illustrative endpoints, enforces a transport timeout plus
    bounded, classified retries, validates the structured extraction and any tool
    call, keeps operational facts OUT of the model (rendered in code), and NEVER
    falls back to the mock or another model on error — it raises.
    """

    simulated = False
    _ILLUSTRATIVE = ("example.com", "example-meta-models", "localhost", "your_", "placeholder")
    ALLOWED_HOSTS = ("api.meta.ai",)   # https + allowlisted host required; verified alone is insufficient
    _SYS = ('You are a library front-desk intent extractor. Return ONLY JSON: '
            '{"lang":"hi|en","intent":"policy|availability|handoff|no_answer|injection|clarify",'
            '"fields":{}}. Never invent facts; facts are looked up separately.')

    def __init__(self, base_url: str | None, model_id: str | None,
                 api_key: str | None, verified: bool = False,
                 retries: int = 2, timeout_s: float = 20.0, deadline_s: float = 45.0,
                 max_output_tokens: int = 512, max_outstanding: int = 2, http_client=None):
        from .limits import OutstandingTracker
        self.base_url = base_url
        self.model_id = model_id
        self._api_key = api_key
        self.verified = verified
        self.retries = retries
        self.timeout_s = timeout_s
        self.deadline_s = deadline_s
        self.max_output_tokens = max_output_tokens
        self._tracker = OutstandingTracker(max_outstanding)   # bounds concurrent + abandoned calls
        self._client = http_client          # injectable httpx-like client for contract tests
        self.name = f"live:{model_id or 'unset'}"

    def _guard(self) -> None:
        if not self.verified:
            raise RuntimeError(
                "LiveModelAdapter is not enabled: endpoint/model not verified against "
                "official docs. Set the real base URL + model id and verified=True first."
            )
        u = urllib.parse.urlparse(self.base_url or "")
        if u.scheme != "https":
            raise RuntimeError(f"endpoint must be HTTPS: {self.base_url!r}")
        if u.hostname not in self.ALLOWED_HOSTS:
            raise RuntimeError(f"host not allowlisted: {u.hostname!r}")
        if any(m in (self.base_url or "") for m in self._ILLUSTRATIVE):
            raise RuntimeError(f"refusing to call an illustrative/unverified endpoint: {self.base_url!r}")
        if not self._api_key:
            raise RuntimeError("no API key configured")

    @staticmethod
    def _is_retryable(e: Exception) -> bool:
        import httpx
        from .limits import TimeoutExceeded
        if isinstance(e, (TimeoutExceeded, httpx.TimeoutException, httpx.TransportError)):
            return True
        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code >= 500   # retry 5xx, never 4xx
        return False                                # never retry extraction/tool errors

    def _post(self, path: str, payload: dict) -> dict:
        import httpx
        client = self._client or httpx.Client(timeout=httpx.Timeout(self.timeout_s))
        try:
            resp = client.post(
                self.base_url.rstrip("/") + path, json=payload,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._client is None:
                client.close()

    def _classify_payload(self, enquiry: str) -> dict:
        return {"model": self.model_id, "temperature": 0,
                "max_tokens": self.max_output_tokens,     # explicit output bound
                "messages": [{"role": "system", "content": self._SYS},
                             {"role": "user", "content": enquiry}]}

    def classify(self, enquiry: str, history: list | None = None) -> Classification:
        self._guard()
        from .limits import run_guarded
        data = run_guarded(
            lambda: self._post("/chat/completions", self._classify_payload(enquiry)),
            retries=self.retries, timeout_s=self.timeout_s, deadline_s=self.deadline_s,
            is_retryable=self._is_retryable, tracker=self._tracker,
        )
        return self.parse_classification(data)

    @classmethod
    def parse_classification(cls, data: dict) -> Classification:
        try:
            content = data["choices"][0]["message"]["content"]
            obj = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ExtractionError(f"unparseable response: {e}")
        if not isinstance(obj, dict):
            raise ExtractionError("response JSON is not an object")
        lang, intent = obj.get("lang"), obj.get("intent")
        if lang not in ("hi", "en"):
            raise ExtractionError(f"invalid lang: {lang!r}")
        if intent not in ALLOWED_INTENTS:
            raise ExtractionError(f"invalid intent: {intent!r}")
        for tc in obj.get("tool_calls") or []:
            cls.validate_tool_call(tc)
        fields = obj.get("fields")
        hint = fields.get("topic") if isinstance(fields, dict) else None
        return Classification(lang, intent, topic_hint=hint)

    def extract(self, enquiry: str, history: list | None = None) -> "ExtractedFields":
        """Live extraction into a typed, validated ExtractedFields object."""
        self._guard()
        from .limits import run_guarded
        data = run_guarded(
            lambda: self._post("/chat/completions", self._classify_payload(enquiry)),
            retries=self.retries, timeout_s=self.timeout_s, deadline_s=self.deadline_s,
            is_retryable=self._is_retryable, tracker=self._tracker,
        )
        return self.parse_extraction(data)

    @classmethod
    def parse_extraction(cls, data: dict) -> "ExtractedFields":
        try:
            content = data["choices"][0]["message"]["content"]
            obj = json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise ExtractionError(f"unparseable response: {e}")
        if not isinstance(obj, dict):
            raise ExtractionError("response JSON is not an object")
        for tc in obj.get("tool_calls") or []:
            cls.validate_tool_call(tc)
        fld = obj.get("fields") or {}
        if not isinstance(fld, dict):
            raise ExtractionError("fields must be an object")
        return validate_fields(ExtractedFields(
            lang=obj.get("lang"), intent=obj.get("intent"),
            date=fld.get("date"), start=fld.get("start"), end=fld.get("end"),
            slot=fld.get("slot"), seat_id=fld.get("seat_id"),
        ))

    @staticmethod
    def validate_tool_call(tc: dict) -> bool:
        name = tc.get("name") if isinstance(tc, dict) else None
        if name not in ALLOWED_TOOLS:
            raise ToolNotAllowed(f"tool not allowed: {name!r}")
        return True

    def draft_answer(self, lang: str, items: list[dict]) -> tuple[str, list[str]]:
        # Operational facts are rendered deterministically in code, never by the
        # model. The live adapter is used for extraction/routing only.
        raise NotImplementedError("facts are code-rendered; live model is extraction-only")


def make_model(mode: str, **kw):
    """Fail-closed model factory. mode must be 'mock' or 'live'; an unknown mode
    raises. 'live' requires base_url, model_id and api_key — never silently
    downgrades to the mock."""
    if mode == "mock":
        return MockModelAdapter()
    if mode == "live":
        missing = [k for k in ("base_url", "model_id", "api_key") if not kw.get(k)]
        if missing:
            raise ValueError(f"live mode missing required config: {missing}")
        return LiveModelAdapter(**kw)
    raise ValueError(f"unknown model mode: {mode!r} (expected 'mock' or 'live')")
