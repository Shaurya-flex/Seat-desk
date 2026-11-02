# Evidence

Genuine live evidence is **only** a `live_run.json` in this directory whose
`transport` is `live-http` and `simulated` is `false`, produced by
`scripts/live_once.py --run`. It is sanitised: no keys, no bearer tokens, no
account identifiers.

Everything else in this repository that exercises the model path (unit tests,
eval runners, stubbed-transport acceptance tests) is offline and labelled
`builtin` or `mocked-http`. Mocked output proves wiring, not Meta integration.

Fixture availability is historical synthetic demo data computed against the
fixture clock (2026-10-27 IST). It is not current, real Rasra Library
availability, and no real member data exists anywhere in this project.
