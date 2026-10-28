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
from dataclasses import dataclass

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
    _SYS = ('You are a library front-desk intent extractor. Return ONLY JSON: '
            '{"lang":"hi|en","intent":"policy|availability|handoff|no_answer|injection|clarify",'
            '"fields":{}}. Never invent facts; facts are looked up separately.')

    def __init__(self, base_url: str | None, model_id: str | None,
                 api_key: str | None, verified: bool = False,
                 retries: int = 2, timeout_s: float = 20.0, deadline_s: float = 45.0,
                 http_client=None):
        self.base_url = base_url
        self.model_id = model_id
        self._api_key = api_key
        self.verified = verified
        self.retries = retries
        self.timeout_s = timeout_s
        self.deadline_s = deadline_s
        self._client = http_client          # injectable httpx-like client for contract tests
        self.name = f"live:{model_id or 'unset'}"

    def _guard(self) -> None:
        if not self.verified:
            raise RuntimeError(
                "LiveModelAdapter is not enabled: endpoint/model not verified against "
                "official docs. Set the real base URL + model id and verified=True first."
            )
        if not self.base_url or any(m in (self.base_url or "") for m in self._ILLUSTRATIVE):
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
                "messages": [{"role": "system", "content": self._SYS},
                             {"role": "user", "content": enquiry}]}

    def classify(self, enquiry: str, history: list | None = None) -> Classification:
        self._guard()
        from .limits import run_guarded
        data = run_guarded(
            lambda: self._post("/chat/completions", self._classify_payload(enquiry)),
            retries=self.retries, timeout_s=self.timeout_s, deadline_s=self.deadline_s,
            is_retryable=self._is_retryable,
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
