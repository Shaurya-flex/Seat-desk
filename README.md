# Moodily Enquiry Assistant

A Hindi/English assistant that answers questions **only** from approved business
information, with source citations, and hands off to a human when it cannot.
Demonstrated first through a study library (Rasra Library & Study Point).

Built for the Meta Global AI Developer Hackathon (Oct–Nov 2026), Indie Developer track.

## Status (honest)

| Part | State |
| --- | --- |
| Deterministic availability engine + tests | **implemented & tested** (offline) |
| Workflow skeleton (retrieval, routing, clarification, citation+support checks, sanitised tool, handoff summary, limits) | **implemented & tested against a MOCK model** (offline, deterministic) |
| Mock model adapter | implemented, clearly labelled `simulated` |
| Real Meta model integration | **adapter implemented; request contract verified against official docs (2 Nov 2026)**; one-shot live harness ready (`scripts/live_once.py`); **no billed call made yet** |
| Hindi answer quality | **unproven** — the mock copies approved text; it is not a language-quality signal |
| Human handoff delivery | **not implemented** — handoff produces a copyable summary only; nothing is sent |
| Voice (Hindi audio) | **adapter + one-shot harness implemented; contract + Hindi support verified from official docs (2 Nov 2026)**; transcript requires explicit confirmation; **not wired into the main flow; no live transcription made yet** |

Account access exists (hackathon credits + pay-as-you-go key), but **no paid call has been made**: usage shows zero requests. The live harness makes exactly one call, only when run explicitly with `--run --i-approve-spend`.

### Simulated vs live

Passing the test suite and the dev eval exercises the **wiring** with a mock
adapter on synthetic data. It is **not** evidence of Hindi model quality or of
real Meta integration. Those require `LiveModelAdapter` against a base URL and
model id verified from the official Meta Model API docs. The live adapter
refuses to call an unverified or illustrative endpoint, so no credentials are
sent to a placeholder.

## What was built during the hackathon vs reused

**Built new during the hackathon (from Oct 27, 2026):** the availability engine,
the workflow skeleton and its modules (`/app`), the approved-knowledge schema and
grounding/citation rules, the synthetic fixtures, and the evaluation sets.

**Pre-existing, reused only as noted:** Rasra's policy *content* (as knowledge
data; the real pack `knowledge/policies.json` keeps every fact `unknown` until the
operator confirms it — no real fees/timings/admission invented); Rasra's separate
Google/Apps Script membership system (**not connected**); the `moodily.in` brand
(name only).

## Data is kept separate from code

Business facts live in `/knowledge` (policy) and `/fixtures` (synthetic). `/app`
holds only logic. See `docs/SCHEMA.md`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # fill real values; .env is gitignored

python -m app.availability      # availability engine demo (no network/model)
python -m app.seat_desk         # runnable Seat Desk enquiry flow (MOCK adapter)
python eval/run_eval.py         # dev-set checks (mock); non-zero on required failure
python eval/run_regression.py   # regression: multi-turn, tool-failure, consistency checks
python -m pytest -q             # full test suite (CI runs this offline, no secrets)
```

## Reproduce the core typed workflow (for judges)

Everything below is offline and deterministic — no key, no network, no cost:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m app.seat_desk
python eval/run_eval.py
python eval/run_regression.py
```

`python -m app.seat_desk` walks the four core behaviours in one scripted
conversation: a clarification for missing information, a deterministic
availability answer, an approved fact with its citation, and an explicitly
**unsent** human-handoff summary. Every turn carries the persistent
"Synthetic data · Mock model" label.

The one genuine Meta call (billed, requires a key in `.env` or the shell):

```bash
python scripts/live_once.py --estimate
python scripts/live_once.py --run --i-approve-spend
```

`--estimate` prints the exact payload and a cost estimate without touching the
network. `--run` makes a single request (retries=0, one outstanding request,
explicit timeout and output cap) through the real `Assistant.handle()` path and
writes sanitised evidence to `evidence/live_run.json`. Acceptance is
substantive (`app/live_checks.py`): the expected interval, counts and free-seat
set are re-derived independently from the raw fixtures, and a completed request
with a wrong date, slot, count, seat set or an unsupported answer is recorded
as `COMPLETED_BUT_INCORRECT`, never `SUCCESS`. Fixture availability is
**historical synthetic demo data** (fixture clock 2026-10-27 IST), not current
real library availability.

Evidence separation: anything produced by mock or stubbed transports stays in
tests/eval output and is labelled `mocked-http`/`builtin`; only
`evidence/live_run.json` with `"transport": "live-http"` counts as genuine Meta
evidence.


Set `KNOWLEDGE_PACK=knowledge/policies.sample.json` to develop against synthetic
demo policies; switch to `knowledge/policies.json` once real values are confirmed.

## Scope guardrails

Read-only. No booking writes, no payments, no changes to member records.
Consequential or unknown requests are handed off (summary only, not sent). Hard
limits on retries, tool calls, output size, and request volume are enforced in
`app/limits.py`; billing alerts are notifications, not caps.

## Layout

```
app/
  clock.py         explicit demonstration clock (Asia/Kolkata)
  availability.py  deterministic availability engine + response sanitiser
  retrieval.py     approved-policy retrieval + citation/support checks
  model.py         MockModelAdapter (simulated) + LiveModelAdapter (refuses unverified)
  tools.py         sanitised, read-only availability tool
  handoff.py       copyable human-handoff summary (not sent)
  limits.py        tool-call/request limits + run_guarded (retry + per-call timeout, enforced)
  verify.py        evaluator: response/structured consistency, privacy + booking guards
  workflow.py      routing, multi-turn state, anaphora, corrections, follow-ups, transparency
  seat_desk.py     runnable end-to-end enquiry flow
knowledge/         approved policy packs (real template + synthetic sample)
fixtures/          synthetic seats, slots, memberships, occupancy, operating hours, demo clock
eval/              cases.json (dev), regression.json (tuned → regression), run_eval.py,
                   run_regression.py, final_assessment.sealed.json (blind, untouched, not run)
tests/             unit tests (availability, workflow, round-2/3 fixes, mutation, seat desk)
docs/              SCHEMA.md, RULES.md (rules sources + classification), LIMITATIONS.md
.github/workflows/ ci.yml (offline tests + eval; no secrets, no paid calls)
```

See `docs/RULES.md` (rules sources), `docs/ELIGIBILITY.md` (model availability vs competition
vs grant eligibility), and `docs/LIMITATIONS.md` (proven vs not). The real `LiveModelAdapter`
is implemented with **mocked-HTTP contract tests** (transport timeout, classified retries,
structured-extraction + read-only tool-call validation, no silent fallback) and its request
contract (endpoint, `max_completion_tokens`, mandatory reasoning, strict JSON-schema
output) was verified against the official docs on 2 Nov 2026 — **no live call has
been made yet**; `scripts/live_once.py` performs the first one explicitly.
`app/intake.py` holds clearly-labelled **mock** audio/transcript/staff-recheck scaffolding,
not wired into the finished text flow. Mock tests prove wiring only, not Meta integration.

> Project description for publishing: use **"Meta integration in progress"** until a genuine
> live round trip exists — do not describe mock behaviour as live/Meta-powered.

Limits: request-volume and tool-call limits are enforced in code. `max_output_tokens`
is a provider generation parameter (not used to truncate our verified answers);
`max_display_chars` is a display-only clamp for untrusted free text. Retry limiting is
declared but **not yet enforced** (`RETRY_ENFORCEMENT = "planned"`). Every response
carries a persistent `transparency` label ("Synthetic data · Mock model"); handoffs are
copyable summaries and are never sent (`delivered: false`).
