# Eligibility & grants — separated and sourced

This note separates three things that are easy to conflate. It is written only from
sources this project could actually read; items needing Discord or a partner login are
marked **unresolved** rather than asserted. We do **not** claim grant approval, prize
eligibility, or zero cost from an announcement.

Sources read (2026-10-28): Participant Guide
(https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details) and the event/submission
page. Discord message permalinks and the Baseten grant form are **not retrievable from
here** (login-gated) — fetch them from your own account; do not treat an announcement as a
grant.

## A. Model availability (where a model can run)
| Claim | Classification |
| --- | --- |
| Muse Spark Open is a Meta **open-weights** model, served on your own hardware or via partner inference (Baseten id `meta-models/muse-spark-open-1026`, Modal). | confirmed (Guide) |
| Hosted Meta Model API offers `muse-spark-1.3`, `muse-voice-transcribe-1.0` (base `https://api.meta.ai/v1`). | interpretation — user-reported from docs; re-verify in console |
| Muse Spark Open is a real Meta **open-weight** model (access: Meta, Hugging Face; Muse Model License) and is also in the OpenRouter catalogue — **not** Llama-only. | confirmed (Meta Model API console → Models, 2026-10-28; OpenRouter catalogue) |
| The partner open-weights id must **not** be used as a hosted Meta Model API model id. | confirmed (Guide — Baseten note) |

## B. General competition eligibility (entering and being judged)
| Item | Classification |
| --- | --- |
| Track/theme: **Indie Developer / Build for Your World** (existing application choice — keep). | confirmed (our choice) |
| Eligible if: public repo, new work built during the event, project incorporates Meta's models. | confirmed (Guide) |
| Judging weights: Impact 30 / Meta tooling 25 / Tech 20 / Demo 25. | confirmed (Guide) |
| Eligibility ≠ winning and ≠ any grant. | confirmed |

## C. Provider-specific bonus / grant eligibility (money, at partner discretion)
| Item | Classification |
| --- | --- |
| Meta: $150 Model API credits, claimed via the form by Nov 4. | confirmed (Guide) |
| A valid **card is required** on the Meta Model API account to make a call; a temporary pre-authorisation appears. | confirmed (Guide) |
| Grant conditions: credits are **not guaranteed**; distributed at each partner's sole discretion. | confirmed (Guide) |
| Baseten $100 + 2M TPM: up to 2,000 participants, reviewed by use case, selected applicants notified by email. | confirmed (Guide) — an application, not an approval |
| Modal $100 (first 1,000); Fireworks $25 (select teams). | confirmed (Guide) |
| "Best Build on Meta Open Weight Models" $10K bonus: project must run on an eligible open-weight model, verified by the infra partner. | confirmed (Guide) — bonus eligibility is separate from the credit grant |
| Data-use mode (training/retention on submitted prompts). | **unresolved** — not on pages read; check the provider's terms/console before sending real data |

## Account state observed in the Meta console (read-only, 2026-10-28)
- Real account context: your actual team/project (not the URL's placeholder `team_id=123`).
  (Specific numeric IDs are kept out of this repo — see the session report instead.)
- Models page shows **"Could not check model access"** — entitlement did not load; retry needed.
- Usage (Oct 22–28): **Spend ₹0.00**, 0 requests/tokens/tool-calls. **No applied-credit balance
  is displayed** on Dashboard or Usage — the $150 grant is **not confirmed** from what's visible.

## Unresolved / to retrieve from your account
- Full Discord message permalinks for announcements (Discord is login-gated in this session).
- The actual verified Baseten grant **form** link and its current conditions.
- The formal **Official Rules** document (must be accepted; see `RULES.md`).
- Confirm the **applied $150 credit** and model entitlement (retry the Models access check;
  find the billing/credits view).
