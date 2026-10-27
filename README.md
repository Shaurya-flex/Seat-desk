# Moodily Enquiry Assistant

A Hindi/English assistant that answers questions **only** from approved business
information, with source citations, and hands off to a human when it cannot.
Demonstrated first through a study library (Rasra Library & Study Point).

Built for the Meta Global AI Developer Hackathon (Oct–Nov 2026), Indie Developer track.

> Status: early build. The deterministic availability engine and its tests are
> working; the model-grounded answering workflow is in progress and is gated on
> live Meta Model API access. Synthetic data is labelled as such throughout.

## What was built during the hackathon vs reused

**Built new during the hackathon (Oct 27 – Nov 4, 2026):**

- The enquiry assistant application and its grounded-answering workflow (`/app`).
- The deterministic, timezone-aware availability engine (`app/availability.py`) and its tests.
- The approved-knowledge schema, grounding/citation rules, and human-handoff logic.
- The synthetic fixtures and the evaluation sets (`/fixtures`, `/eval`).
- The Meta model integration (added once live API access is confirmed).

**Pre-existing, not part of the build (reused only as noted):**

- Rasra Library's policy *content* — reused as knowledge data, not code. In this repo
  the real policy pack (`knowledge/policies.json`) is a template with every fact marked
  `unknown` until the operator confirms it; no real fees/timings/admission rules are
  invented here.
- Rasra's separate Google/Apps Script membership system — **not connected**. Availability
  here runs on synthetic fixtures, never on real member data.
- The `moodily.in` brand — name only, not modified.

## Data is kept separate from code

All business facts live in `/knowledge` (policy) and `/fixtures` (synthetic operational
data). `/app` holds only logic. See `docs/SCHEMA.md`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # fill in values; .env is gitignored

# run the availability engine demo (no network, no model):
python -m app.availability

# run tests:
python -m pytest -q
```

Set `KNOWLEDGE_PACK=knowledge/policies.sample.json` in `.env` to develop against the
synthetic demo policies; switch to `knowledge/policies.json` once real values are confirmed.

## Scope guardrails

Read-only. No booking writes, no payments, no changes to member records. Consequential
or unknown requests are handed off to a human. Safety bounds (retries, tool calls,
output tokens, request volume) are config in `.env.example`; billing alerts are
notifications, not hard spend caps.

## Layout

```
app/         application logic (clock, availability engine, workflow[WIP], model integration[WIP])
knowledge/   approved policy packs (real template + synthetic sample) — data, not code
fixtures/    synthetic seats, slots, memberships, occupancy, demo clock
eval/        development cases (the 15) + held-out cases (hinglish, follow-ups, overlaps, tool failures)
tests/       unit tests for the availability engine
docs/        schema reference
```
