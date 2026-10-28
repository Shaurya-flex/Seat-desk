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


class LiveModelAdapter:
    """Real provider adapter — NOT implemented. Refuses unverified endpoints."""

    simulated = False

    # Hosts we will never treat as a real endpoint (placeholders / examples).
    _ILLUSTRATIVE = ("example.com", "example-meta-models", "localhost", "your_", "placeholder")

    def __init__(self, base_url: str | None, model_id: str | None,
                 api_key: str | None, verified: bool = False,
                 retries: int = 2, timeout_s: float = 20.0):
        self.base_url = base_url
        self.model_id = model_id
        self._api_key = api_key
        self.verified = verified
        self.retries = retries
        self.timeout_s = timeout_s
        self.name = f"live:{model_id or 'unset'}"

    def _guarded(self, fn):
        from .limits import run_guarded
        return run_guarded(fn, retries=self.retries, timeout_s=self.timeout_s)

    def _guard(self) -> None:
        if not self.verified:
            raise RuntimeError(
                "LiveModelAdapter is not enabled: endpoint/model not verified against "
                "official docs. Set the real base URL + model id and verified=True first."
            )
        if not self.base_url or any(m in (self.base_url or "") for m in self._ILLUSTRATIVE):
            raise RuntimeError(
                f"refusing to call an illustrative/unverified endpoint: {self.base_url!r}"
            )
        if not self._api_key:
            raise RuntimeError("no API key configured")

    def _call(self):  # placeholder for the real HTTP request (not implemented)
        raise NotImplementedError("live model call not implemented yet")

    def classify(self, enquiry: str, history: list | None = None) -> Classification:
        self._guard()
        return self._guarded(self._call)        # retry/timeout enforced here

    def draft_answer(self, lang: str, items: list[dict]) -> tuple[str, list[str]]:
        self._guard()
        return self._guarded(self._call)        # retry/timeout enforced here
