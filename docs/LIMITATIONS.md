# Limitations and honest scope

What works (offline, deterministic, tested):

- Availability engine: half-open overlaps, operating hours, occupancy coverage,
  membership kept separate from physical availability, sanitised output. 30+ tests.
- Workflow skeleton against a MOCK model: routing, clarification, multi-turn pending
  state, anaphora, completed-turn corrections, seat follow-ups, interval retention.
- Evaluator: citation-id + source-support checks, response/structured consistency,
  privacy-leak and booking-claim guards; mutation-tested.
- Enforced limits: per-turn tool calls, per-session requests; retry + per-call timeout
  via `run_guarded` (wired into the live adapter).

What is NOT done / not proven:

- Real Meta integration. The live adapter is disabled and refuses unverified/illustrative
  endpoints. No live call has been made. Mock tests prove wiring only — NOT Hindi/Hinglish
  model quality and NOT real provider behaviour.
- Audio transcription is a labelled mock; no real speech model is called.
- In-question conflicting-figure detection ("300 or 500?") is reported, not implemented.
- Retrieval is keyword scoring, not semantic.
- Real business facts: `knowledge/policies.json` keeps all facts `unknown` until the
  operator confirms them. No real fees/timings/admission are invented. Demo uses the
  clearly-labelled synthetic sample pack and 6-seat synthetic fixtures.

Safety/positioning:

- Read-only: no booking writes, payments, or member-record changes.
- Handoffs are copyable summaries, never sent (`delivered: false`).
- Every response carries a persistent "Synthetic data · Mock model" transparency label.
