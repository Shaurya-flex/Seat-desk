"""Enquiry workflow (skeleton), multi-turn aware.

One complete, read-only path:
  enquiry -> classify (lang + intent) -> (resume pending clarification) ->
  clarify if needed -> approved-policy retrieval OR sanitised availability ->
  citation+support check -> supported explanation OR honest no-answer ->
  optional human-handoff summary (copyable, NOT sent).

No booking writes, payments, or member-record changes. The model is injected;
with MockModelAdapter everything runs offline and deterministically.
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from .handoff import build_handoff_summary
from .limits import Limits, SessionBudget
from .model import MockModelAdapter, is_consequential
from .retrieval import load_pack, retrieve, confirmed_items, validate_citation, render_policy
from .tools import AvailabilityTool, ToolError

_SEAT_RE = re.compile(r"\b([Ss]\d{1,3})\b")
_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2})\s*(?:-|to|–|से)\s*(\d{1,2}:\d{2})")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SLOT_WORDS = {"morning": "सुबह", "afternoon": "दोपहर", "evening": "शाम"}


def _resolve_timeref(enquiry: str, clock) -> dict:
    """Extract availability fields explicitly present in THIS message."""
    low = enquiry.lower()
    out: dict = {}

    m = _ISO_DATE_RE.search(enquiry)
    if m:
        out["date"] = m.group(0)
    elif "tomorrow" in low or "कल" in enquiry:
        out["date"] = (clock.as_of.date() + timedelta(days=1)).isoformat()
    elif "today" in low or "आज" in enquiry:
        out["date"] = clock.as_of.date().isoformat()

    now_ref = ("right now" in low or "अभी" in enquiry or re.search(r"\bnow\b", low) is not None)

    for key, hi in _SLOT_WORDS.items():
        if key in low or hi in enquiry:
            out["slot"] = key
            break

    tr = _TIME_RANGE_RE.search(enquiry)
    if tr:
        out["start"], out["end"] = tr.group(1), tr.group(2)

    if now_ref and "date" not in out:
        out["date"] = clock.as_of.date().isoformat()
    if now_ref and "slot" not in out and "start" not in out:
        out["start"] = clock.as_of.strftime("%H:%M")
        out["end"] = (clock.as_of + timedelta(hours=1)).strftime("%H:%M")

    sm = _SEAT_RE.search(enquiry)
    if sm:
        out["seat_id"] = sm.group(1).upper()
    return out


def _has_anaphor(enquiry: str) -> bool:
    """Explicit reference to a previously mentioned slot/date (e.g. 'in it')."""
    low = enquiry.lower()
    if any(a in low for a in ("that slot", "same slot", "same", "that one")):
        return True
    if re.search(r"\bit\b", low):
        return True
    return any(a in enquiry for a in ("उसमें", "इसमें", "उसी"))


_CONT_CUES_EN = ("and ", "also", "what about", "how about", "instead", "actually",
                 "rather", "change", "no,", "no ")
_CONT_CUES_HI = ("और", "भी", "बल्कि", "नहीं", "बदल")


def _is_continuation(enquiry: str) -> bool:
    """A short follow-up/correction on a previous turn (e.g. 'and S02?', 'actually morning')."""
    low = enquiry.lower()
    return any(c in low for c in _CONT_CUES_EN) or any(c in enquiry for c in _CONT_CUES_HI)


def _alternatives(enquiry: str) -> dict:
    """Detect when the user offered MORE THAN ONE time/date option."""
    low = enquiry.lower()
    slots = [k for k, hi in _SLOT_WORDS.items() if k in low or hi in enquiry]
    dates: list[str] = []
    if "today" in low or "आज" in enquiry:
        dates.append("today")
    if "tomorrow" in low or "कल" in enquiry:
        dates.append("tomorrow")
    dates += _ISO_DATE_RE.findall(enquiry)
    ranges = _TIME_RANGE_RE.findall(enquiry)
    return {"slots": slots, "dates": list(dict.fromkeys(dates)), "ranges": ranges}


def _merge_availability(base: dict, new: dict) -> dict:
    """Merge a follow-up onto a prior query. A new interval TYPE replaces the old
    one (slot replaces explicit times and vice versa); date/seat override."""
    merged = dict(base)
    if "slot" in new:
        merged.pop("start", None); merged.pop("end", None)
        merged["slot"] = new["slot"]
    if "start" in new and "end" in new:
        merged.pop("slot", None)
        merged["start"], merged["end"] = new["start"], new["end"]
    for k in ("date", "seat_id"):
        if k in new:
            merged[k] = new[k]
    return merged


def _t(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en


class Assistant:
    def __init__(self, *, pack: dict, tool: AvailabilityTool,
                 model=None, limits: Limits | None = None):
        self.pack = pack
        self.tool = tool
        self.model = model or MockModelAdapter()
        self.limits = limits or Limits()
        self.budget = SessionBudget(self.limits)
        self.pending: dict | None = None     # explicit pending-request state
        self.ctx: dict = {"date": None, "slot": None}   # last-mentioned date/slot (for anaphora)
        self.last_availability: dict | None = None      # last completed availability query (follow-ups)

    # -- transparency (persistent demo label) -----------------------------
    def _transparency(self) -> dict:
        parts = ["Synthetic data"]                      # fixtures are synthetic
        if getattr(self.model, "simulated", False):
            parts.append("Mock model")
        return {"synthetic_data": True, "mock_model": getattr(self.model, "simulated", False),
                "label": " · ".join(parts)}

    def _base(self, route: str, lang: str) -> dict:
        return {
            "route": route, "lang": lang,
            "provider": self.model.name, "simulated": self.model.simulated,
            "transport": getattr(self.model, "transport", "builtin"),   # mocked-http | live-http | builtin
            "transparency": self._transparency(),
            "answer": None, "citations": [], "citation_check": None,
            "availability": None, "handoff": None, "clarification": None,
            "facts": None, "warnings": [],
        }

    # -- understanding (one model call per turn) --------------------------
    def _understand(self, enquiry: str) -> dict:
        """Resolve (lang, intent, ref) once per turn.

        A live model (one exposing extract()) returns VALIDATED fields; the mock
        uses classify() + keyword _resolve_timeref. For a live model the query
        fields come ONLY from the model's validated extraction — never a keyword
        fallback. (Follow-up/correction CUES are still text-based conversation
        control, but field VALUES come from the extractor / the prior query.)
        """
        if hasattr(self.model, "extract"):
            f = self.model.extract(
                enquiry,
                now_iso=self.tool.clock.as_of.isoformat(),   # same clock as the availability engine
                prior=self.last_availability,                 # context for follow-ups (data, not instructions)
            )
            ref = {k: getattr(f, k) for k in ("date", "start", "end", "slot", "seat_id")
                   if getattr(f, k) is not None}
            return {"lang": f.lang, "intent": f.intent, "ref": ref, "from_model": True}
        c = self.model.classify(enquiry)
        return {"lang": c.lang, "intent": c.intent,
                "ref": _resolve_timeref(enquiry, self.tool.clock), "from_model": False}

    # -- main entry -------------------------------------------------------
    def handle(self, enquiry: str) -> dict:
        self.budget.start_turn()
        u = self._understand(enquiry)
        lang, intent, ref, from_model = u["lang"], u["intent"], u["ref"], u["from_model"]

        # Deterministic guard: a consequential/personal request (refund, cancel,
        # booking, member-record change) always hands off, whatever intent the
        # model returned. Without this, a live model that labels "Can you refund
        # my fee?" as `policy` lets keyword retrieval cite fees.monthly — a wrong,
        # confidently-cited answer. Injection still wins (it is refused outright).
        model_intent = intent
        if intent != "injection" and is_consequential(enquiry):
            intent = "handoff"

        # Keyword-path anaphora context (mock only; live reuses the prior query).
        if not from_model:
            if "date" in ref:
                self.ctx["date"] = ref["date"]
            if "slot" in ref:
                self.ctx["slot"] = ref["slot"]

        # Resume a pending availability clarification if this message continues it.
        if self.pending and self.pending.get("intent") == "availability":
            fresh_intent = intent in ("injection", "handoff", "policy")
            supplies = any(k in ref for k in ("date", "slot", "start", "end", "seat_id"))
            if supplies and not fresh_intent:
                merged = _merge_availability(self.pending["fields"], ref)
                self.pending = None
                return self._availability_with_ref(enquiry, lang, merged,
                                                    self._base("availability", lang), from_model)
            self.pending = None                        # abandon obsolete pending

        # Completed-turn follow-up / correction / anaphor -> reuse the full prior query.
        if self.last_availability and (_is_continuation(enquiry) or _has_anaphor(enquiry)):
            if intent != "injection" and any(k in ref for k in ("date", "slot", "start", "end", "seat_id")):
                merged = _merge_availability(self.last_availability, ref)
                return self._availability_with_ref(enquiry, lang, merged,
                                                    self._base("availability", lang), from_model)

        if intent == "injection":
            resp = self._base("injection", lang)
            resp["answer"] = _t(lang,
                "I can only help with approved library information, so I can't do that.",
                "मैं केवल स्वीकृत लाइब्रेरी जानकारी में मदद कर सकता हूँ, यह नहीं कर सकता।")
            return resp

        if intent == "availability":
            return self._availability_with_ref(enquiry, lang, ref,
                                                self._base("availability", lang), from_model)

        if intent == "clarify":
            resp = self._base("clarify", lang)
            resp["clarification"] = _t(lang,
                "Could you give a bit more detail so I can help?",
                "कृपया थोड़ा और बताएं ताकि मैं मदद कर सकूँ?")
            return resp

        if intent == "policy":
            return self._policy(enquiry, lang)

        if intent == "handoff":
            resp = self._base("handoff", lang)
            if model_intent != "handoff":
                resp["warnings"].append(
                    f"consequential_guard: model intent {model_intent!r} overridden -> handoff")
            resp["handoff"] = build_handoff_summary(
                enquiry, lang, reason="consequential or personal request", pack=self.pack)
            resp["answer"] = _t(lang,
                "That needs a person. Here's a summary you can copy to the library desk (nothing was sent).",
                "इसके लिए व्यक्ति चाहिए। यह सारांश आप डेस्क को दे सकते हैं (कुछ भेजा नहीं गया)।")
            return resp

        return self._no_answer(enquiry, lang)

    # -- routes -----------------------------------------------------------
    def _no_answer(self, enquiry: str, lang: str) -> dict:
        resp = self._base("no_answer", lang)
        resp["answer"] = _t(lang,
            "I don't have that in my approved information, so I won't guess.",
            "यह मेरी स्वीकृत जानकारी में नहीं है, इसलिए मैं अनुमान नहीं लगाऊंगा।")
        resp["handoff"] = build_handoff_summary(
            enquiry, lang, reason="information not in approved knowledge base", pack=self.pack)
        return resp

    def _policy(self, enquiry: str, lang: str) -> dict:
        resp = self._base("policy", lang)
        items = retrieve(enquiry, self.pack)
        confirmed = confirmed_items(items, lang)
        if confirmed:
            best = [confirmed[0]]                               # most specific item only
            answer, cites = render_policy(best, lang)           # deterministic rendering
            check = validate_citation(answer, cites, self.pack, lang)
            resp["citation_check"] = check
            if check["ok"]:
                resp["answer"] = answer
                resp["citations"] = cites
                return resp
            resp["route"] = "handoff"
            resp["handoff"] = build_handoff_summary(
                enquiry, lang, reason="answer failed citation/support check", pack=self.pack)
            resp["answer"] = _t(lang,
                "I couldn't verify that against approved information. Here's a summary for a person (nothing was sent).",
                "मैं इसे स्वीकृत जानकारी से सत्यापित नहीं कर पाया। यह सारांश व्यक्ति के लिए है (कुछ भेजा नहीं गया)।")
            return resp

        if items:   # topic matched but fact not confirmed
            resp["route"] = "handoff"
            resp["handoff"] = build_handoff_summary(
                enquiry, lang, reason="policy exists but is not yet confirmed", pack=self.pack)
            resp["answer"] = _t(lang,
                "That isn't confirmed in my information yet. Here's a summary a person can act on (nothing was sent).",
                "यह अभी पुष्ट नहीं है। यह सारांश कोई व्यक्ति देख सकता है (कुछ भेजा नहीं गया)।")
            return resp

        return self._no_answer(enquiry, lang)

    def _availability_with_ref(self, enquiry: str, lang: str, ref: dict, resp: dict,
                               from_model: bool = False) -> dict:
        # Keyword text-scans (alternatives, anaphora ctx-fill) are the MOCK path only.
        # For a live model, ambiguity is signalled by the model (intent=clarify) and
        # anaphora is resolved via the prior query merge — field VALUES never come
        # from keyword parsing here.
        if not from_model:
            # --- multiple alternatives offered -> clarify, never silently pick one ---
            alts = _alternatives(enquiry)
            if len(alts["slots"]) > 1 or len(alts["dates"]) > 1 or len(alts["ranges"]) > 1:
                self.pending = {"intent": "availability", "fields": {}}
                if len(alts["dates"]) <= 1 and "date" in ref:
                    self.pending["fields"]["date"] = ref["date"]
                if "seat_id" in ref:
                    self.pending["fields"]["seat_id"] = ref["seat_id"]
                opts = " / ".join(alts["slots"]) if len(alts["slots"]) > 1 else " / ".join(map(str, alts["dates"]))
                resp["route"] = "clarify"
                resp["clarification"] = _t(lang,
                    f"You gave more than one option ({opts}). Which should I check?",
                    f"आपने एक से ज़्यादा विकल्प दिए ({opts})। मैं कौन सा देखूँ?")
                return resp

            # --- anaphora: 'in it' / 'उसमें' reuses the last-mentioned date/slot ---
            if _has_anaphor(enquiry):
                if self.ctx.get("date") and "date" not in ref:
                    ref["date"] = self.ctx["date"]
                if self.ctx.get("slot") and "slot" not in ref and "start" not in ref:
                    ref["slot"] = self.ctx["slot"]

        # --- conflict: a slot AND an explicit time range that disagree (fix 2) ---
        if "slot" in ref and "start" in ref and "end" in ref:
            sb = self.tool.slots.get(ref["slot"])
            sb_str = (sb[0].strftime("%H:%M"), sb[1].strftime("%H:%M")) if sb else None
            if sb_str != (ref["start"], ref["end"]):
                resp["route"] = "clarify"
                self.pending = {"intent": "availability",
                                "fields": {k: ref[k] for k in ("date", "seat_id") if k in ref}}
                resp["clarification"] = _t(lang,
                    f"You gave both the {ref['slot']} slot and {ref['start']}–{ref['end']}. "
                    f"Which should I check?",
                    f"आपने {ref['slot']} स्लॉट और {ref['start']}–{ref['end']} दोनों दिए। मैं कौन सा देखूँ?")
                return resp
            ref = {k: v for k, v in ref.items() if k not in ("start", "end")}  # equal: keep slot

        has_interval = ("slot" in ref) or ("start" in ref and "end" in ref)
        if "date" not in ref or not has_interval:
            # remember what we have; ask only for what's missing (fix 3 state)
            self.pending = {"intent": "availability",
                            "fields": {k: ref[k] for k in ("date", "slot", "start", "end", "seat_id") if k in ref}}
            resp["route"] = "clarify"
            missing = "date and slot" if "date" not in ref and not has_interval else (
                "date" if "date" not in ref else "slot or time")
            resp["clarification"] = _t(lang,
                f"For which {missing} should I check seats (morning/afternoon/evening)?",
                "मैं किस तारीख और स्लॉट (सुबह/दोपहर/शाम) के लिए सीटें देखूँ?")
            return resp

        request = {"date": ref["date"]}
        if "slot" in ref:
            request["slot"] = ref["slot"]
        else:
            request["start"], request["end"] = ref["start"], ref["end"]
        if "seat_id" in ref:
            request["seat_id"] = ref["seat_id"]

        self.last_availability = dict(request)   # remember for follow-ups/corrections

        try:
            self.budget.spend_tool_call()
            result = self.tool.get_availability(request)        # sanitised view
        except ToolError as e:
            resp["route"] = "handoff"
            resp["warnings"].append(f"tool_failure: {e}")
            resp["handoff"] = build_handoff_summary(
                enquiry, lang, reason="availability tool unavailable", pack=self.pack, extra=str(e))
            resp["answer"] = _t(lang,
                "I couldn't check availability just now. Here's a summary to hand to the desk (nothing was sent).",
                "मैं अभी उपलब्धता नहीं देख पाया। यह सारांश डेस्क को दें (कुछ भेजा नहीं गया)।")
            return resp

        resp["availability"] = result
        status = result["status"]
        if status == "ok":
            free = [s for s in result["seats"] if s["available"]]
            shown = free[:3]
            labels = ", ".join(s["label"] for s in shown)
            truncated = len(free) > len(shown)      # never present a partial list as the full list
            n, total = result["summary"]["available"], result["summary"]["considered"]
            en_sfx = (f" (e.g. {labels})." if truncated else f" ({labels})." ) if free else "."
            hi_sfx = (f" (जैसे {labels})।" if truncated else f" ({labels})।" ) if free else "।"
            resp["answer"] = _t(lang,
                f"{n} of {total} seats are free for {result['query']['date']}" + en_sfx,
                f"{result['query']['date']} के लिए {total} में से {n} सीटें खाली हैं" + hi_sfx)
            resp["facts"] = {"free": n, "considered": total, "date": result["query"]["date"],
                             "window": result["query"].get("slot")
                             or (result["query"].get("start"), result["query"].get("end"))}
        elif status == "closed":
            oh = result.get("operating_hours") or {}
            resp["answer"] = _t(lang,
                f"The library is closed then (open {oh.get('open')}–{oh.get('close')}).",
                f"उस समय लाइब्रेरी बंद है (खुली {oh.get('open')}–{oh.get('close')})।")
        elif status == "availability_unknown":
            resp["route"] = "handoff"
            resp["handoff"] = build_handoff_summary(
                enquiry, lang, reason="availability outside confirmed coverage", pack=self.pack)
            resp["answer"] = _t(lang,
                "I can't confirm seats for that date. Here's a summary for a person (nothing was sent).",
                "मैं उस तारीख के लिए सीटें पुष्ट नहीं कर सकता। यह सारांश व्यक्ति के लिए है (कुछ भेजा नहीं गया)।")
        else:  # invalid_request
            resp["route"] = "clarify"
            resp["clarification"] = _t(lang,
                "I couldn't read that date/time — please give a date and a slot.",
                "मैं वह तारीख/समय समझ नहीं पाया — कृपया तारीख और स्लॉट दें।")
        return resp


def build_default_assistant(base_dir: str | Path | None = None, *,
                            pack_path: str | Path | None = None,
                            limits: Limits | None = None,
                            tool_fail: bool = False) -> Assistant:
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
    pack = load_pack(pack_path or base / "knowledge" / "policies.sample.json")
    tool = AvailabilityTool(base / "fixtures", fail=tool_fail)
    return Assistant(pack=pack, tool=tool, model=MockModelAdapter(), limits=limits)
