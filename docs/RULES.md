# Hackathon rules — sources and classification

Event: Meta Global AI Developer Hackathon (hosts Meta & Cerebral Valley).
Sources read (last checked 2026-10-28):

- Participant Guide: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details
- Event / submission page: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/hackathon/submit
- Event waiver: https://cerebralvalley.ai/e/meta-ai-developer-hackathon/waiver

Each item is classified **confirmed** (quoted/stated on an organizer page we read),
**interpretation** (our reading), or **unresolved** (not verified from a source we can access).

| Item | Detail | Classification |
| --- | --- | --- |
| Build window | Oct 27 – Nov 4, 2026 | confirmed (Guide) |
| Submission deadline / tz | Nov 4, 9:00 PM ET; one submission; late not considered | confirmed (Guide) |
| Repo visibility | Repositories must be public | confirmed (Guide) |
| Required Meta use | Project must incorporate Meta's models; stage-1 checks it | confirmed (Guide) |
| New work / reuse | Must be built during the event; existing code allowed only if new work is clearly identified | confirmed (Guide) |
| Demo length | 3-minute demo video of what you built | confirmed (Guide) |
| Submission fields | Public repo, video link, team members | confirmed (Guide) |
| Excluded / anti-projects | Includes "Basic RAG" and "simple AI for Education" chatbots | confirmed (Guide) |
| Judging | Stage 1 pass/fail; Stage 2 rubric Impact 30 / Meta tooling 25 / Tech 20 / Demo 25 | confirmed (Guide) |
| Hosted API base | https://api.meta.ai/v1 | interpretation (user-reported from docs 28 Oct; re-verify in console) |
| Hosted models | muse-spark-1.3, muse-voice-transcribe-1.0 | interpretation (user-reported; re-verify) |
| Partner open-weights | muse-spark-open-1026 is partner-served, not a hosted model | interpretation |
| Formal Official Rules doc | "will be published … must be accepted"; not a live link on pages we can read (likely Discord #announcements) | unresolved — read and accept before relying on the Guide alone |

Compliance posture: we build eligible NEW work during the window, keep the repo public,
use Meta models only through a verified endpoint, and clearly separate new vs reused work.
We do **not** claim final compliance until the formal Official Rules are read/accepted and a
genuine Meta round trip is demonstrated. We do not accept legal terms on the user's behalf.

## Discord-confirmed (organizer posts, read 2026-10-29)
Channels: #rules (Ivan, 26 Oct), #faqs (Cerebral Valley APP + Kai|CV + Maya, 26–27 Oct).
- Build period is officially **Oct 27 – Nov 4** (Kai|CV correction: "after the kickoff session"). — confirmed
- **Standalone repository**: the submitted repo must be a FRESH, standalone extract containing ONLY work
  done during the event; keep any existing codebase out of it. The 3-min demo must open with one line
  stating what was pre-existing vs built this week (Kai|CV, 26 Oct 18:12). — confirmed. Seat Desk already
  satisfies this (separate repo, not inside `moodily`).
- **$150 Meta Model API credits**: claimed individually by Nov 4 9 PM ET; the claim form is requested from
  @CV; submit the SAME email used to apply and the numeric team_id from the dev.meta.ai URL. See Hackathon
  Credit Terms §1–3; §3.8 covers open-weight use. — confirmed (#faqs)
- **A payment card is required** to use credits / make calls; a temporary pre-authorisation appears and
  releases in a few business days. "Don't assume a Spend Limit notification stops billing." — confirmed
- Partner credits: Baseten $100 + 2M TPM (≤2,000 participants, approval by use case; Baseten model id
  `meta-models/muse-spark-open-1026`); Modal $100 (first 1,000); Fireworks TBC. — confirmed (#faqs)
- Judging: fit a theme + meaningfully use Meta Model API and/or open-weight models; then Impact, Meta
  tooling, Technical depth, Demo; top 5 per track to finals. — confirmed
