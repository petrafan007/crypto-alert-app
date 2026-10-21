# Decision Engine Revamp — Implementation Plan

**Goal:** Replace the "Jev" decision layer with a provider-neutral **Decision Engine** that
uses **SubQ (`subq-snap-preview`)** as the primary decision provider and **Inception Mercury
Decide (`mercury-decide`)** as the fallback. Remove every Jev reference. Move the Decision
Engine out of shadow mode so it actively influences decisions in both the main crypto app
and the Quantitative Strategy Engine.

## Current state (verified)

| Item | Finding |
|---|---|
| `services/jev_*.py` | 969 lines across 7 files, all Jev-branded |
| `user_settings` | 10 `jev_*` columns |
| `credentials` | `subq_api_key` exists; `inception_key` already exists (used for chat completions) |
| Transports | `vercel` (typesafe jev), `openrouter` (typesafe jev-1.13), `subq` |
| SubQ endpoint | `https://api.subq.ai/v1/systemone`, model `subq-snap-preview` |
| Shadow mode | `jev_quant_shadow_enabled` gates the quant overlay; `jev_sentiment_mode` has `shadow` |
| Jev contracts | `boolean` question type is translated to `noul` on the wire for openrouter/subq |
| Quant gate | `services/jev_settings.py` **raises** if `jev_quant_paper_gate_enabled` is set |

## Mercury Decide API (from vendor docs)

```
POST https://api.inceptionlabs.ai/v1/decisions
Authorization: Bearer $INCEPTION_API_KEY
{
  "model": "mercury-decide",
  "state": {...},
  "questions": {
    "name": {"type": "noul" | "choice" | "score" | "extract", ...}
  }
}
```

Responses: `answers[name].noul` (0-1 probability), `answers[name].choice` + `probabilities` +
`confidence` (choice), `answers[name].score` + `legend` + `probabilities` + `confidence` (score),
`answers[name].spans` (extract). No `/v1/chat/completions`, no streaming, no tools.
Only input tokens are billed.

**Key compatibility finding:** Mercury's `noul` type is *identical* to SubQ's `noul`. The existing
SubQ response-normalisation path already converts `noul` → the internal `boolean` type. Mercury
can reuse that exact normalisation.

## Plan

### Phase A — Decision Engine core (new names, provider-neutral)

1. `services/decision_engine.py` — provider-neutral client supporting `subq` and `inception`
   transports. Retains the existing `boolean`/`choice`/`score` internal contract so every
   consumer keeps working, and normalises both `noul` wire formats identically.
2. `services/decision_settings.py` — replaces `jev_settings.py`. New column names
   `decision_*`. Transports: `subq`, `inception`. Endpoint allowlist includes the Inception
   Decisions endpoint.
3. `services/decision_contracts.py` — replaces `jev_contracts.py`.
4. `services/decision_evaluations.py`, `decision_outcomes.py`, `decision_sentiment.py`,
   `decision_event.py`, `decision_quant.py` — renamed equivalents.

### Phase B — Mercury wiring

5. Add `mercury-decide` to the Decisions model catalog and the provider catalog in the frontend.
6. Store the Inception Decisions key. Reuse `inception_key` if a separate one is not needed;
   otherwise add `inception_decisions_key`.
7. Transport fallback order: `subq` primary → `inception` fallback. A decision request that
   fails on SubQ retries on Mercury before giving up.

### Phase C — Active (not shadow) decisions

8. Remove the `paper gate unavailable` restriction so the Decision Engine can gate paper entries.
9. Quant overlay: the Decision Engine result becomes an **entry veto/confirm** on the crypto
   module, not a silent observation. A decision that says "do not enter" blocks the entry and
   is recorded with its reason.
10. Sentiment: `shadow` mode removed; the decision engine is either `off` or `first`.

### Phase D — Schema migration

11. Rename `jev_*` columns to `decision_*` in `user_settings`. Additive migration in
    `database.py` plus a data migration preserving the user's existing selection.
12. Rename the `jev_evaluations` table to `decision_evaluations` (or keep the table and change
    the ORM). Prefer keeping the table for audit continuity and renaming the ORM only.

### Phase E — Test failures

13. `test_event_market_timing` / `test_portfolio_event_handoff` — mocks out of date with the
    current strategy-service call signature.
14. `test_jev_settings` — asserts `jev_generative_fallback_enabled` is cleared; the setting is
    being removed entirely.
15. `test_synthetic_order_lifecycle` — the ladder replacement path does not verify that the
    replacement targets the same symbol. **This is a real bug**: a replacement for a different
    symbol would cancel the wrong order.
16. `test_webull_persistence` — `manual_webull_activities` is referenced but never defined in
    `routes/portfolio.py`. **This is a real production bug**: the Webull tax report raises
    `NameError` for every manual Webull activity.
17. `test_ollama_credentials` — needs a live provider; mark it as requiring explicit opt-in.

## Sequencing constraint

The Decision Engine rename touches the database schema. The bankroll reset (generation 3) is
already live, so the migration must be additive and must not disturb the generation-2 history.
