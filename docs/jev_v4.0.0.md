# Jev Decision Engine — v4.6.16

Jev is the evaluator for portfolio/watchlist sentiment, Webull stock/ETF/crypto sentiment, and Event contract probabilities. These paths never fall back to generative providers. Written Copilot answers and quantitative audits retain their selected generative providers.

## Connection

Open **Settings → AI Providers & Models → Jev Decision Engine**. Enable Jev, select Vercel AI Gateway or OpenRouter, enter the corresponding key, save, and test the connection. Enable the main AI integration for scheduled sentiment and Event evaluation. Jev sentiment can be enabled or disabled; legacy shadow settings now resolve to Jev evaluations, and legacy generative-fallback flags cannot enable fallback.

OpenRouter uses its native [Decisions API](https://openrouter.ai/blog/insights/what-is-jev/) at `https://openrouter.ai/api/alpha/decisions`, with `typesafe/jev-1.13` and an OpenRouter key. Vercel uses its native [evaluation endpoint](https://vercel.com/docs/ai-gateway/modalities/evaluation), `typesafe-ai/jev`, and a Vercel key. Changing providers updates the endpoint and model. Saved custom Jev versions are preserved. OpenRouter Noul replies are normalized to the internal Boolean schema; actual model, confidence, usage and reported cost are retained.

Keys are encrypted and masked. Saving `********` preserves a saved key. Older versions could overwrite an OpenRouter key with the mask itself: re-enter the real key after upgrading if Test Connection reports a missing key. A placeholder cannot be recovered into a credential.

## Editable instructions

- **Settings → AI Prompts → Portfolio Sentiment Analysis**: sentiment search template and all typed evaluation questions and answer descriptions.
- **Settings → AI Prompts → Watchlist Sentiment Analysis**: separate watchlist search template and typed questions/descriptions.
- **Settings → Quantitative Strategy Engine → AI Configuration**: contract outcome and evidence-quality questions/descriptions, plus shared quantitative audit/evaluation instructions. Use **Save AI Configuration** to save modal edits.
- **Settings → AI Prompts → Shared workflow, Copilot and connection instructions**: formerly hidden shared search/synthesis, portfolio scope, Copilot scope and connection-test instructions.

Bundled reset defaults live in `config/ai_prompt_catalog.json`; runtime overrides are saved per user in `user_settings.ai_prompt_overrides`. Existing market/asset/Copilot prompts and module auditor mandates remain editable in their established UI. Runtime code assembles data and loads instructions; it does not append hidden instruction strings. Question IDs, types and response labels remain fixed so edits cannot change the application's response contract. Contract questions must include `{index}` and `{symbol}` to identify each batch member. Blank/malformed edits are rejected.

## Sentiment

Sentiment gathers timestamped news/search evidence and recorded price/volume context without using a generative search model. Jev evaluates direction, materiality, bullish probability, downside risk, evidence conflict and catalyst. Questions use the supplied forecast horizon and recommendation boundaries. Portfolio directions map to Buy Immediately / Consider Buying / Hold / Consider Selling / Sell Immediately; watchlist directions map to Definitely Buy / Consider Buying / Watch / Avoid. Stablecoins keep their deterministic shortcut.

Queue snapshots retain the exact questions and settings used for each evaluation. Future evidence is excluded. Missing current price or evidence, low confidence, conflicted evidence and malformed/unavailable replies abstain or report an error; they never fabricate a neutral recommendation or call another AI model. History links retain the actual Jev provider/model. Existing historical fallback observations remain visible as historical telemetry.

## Contract probabilities

Bounded Event batches evaluate each contract's exact condition/cutoff and supplied observations using typed YES/NO and evidence-quality questions. No generative research or synthesis call is made. Probability, confidence, evidence quality, actual served model, latency, usage/cost and answers are saved in Event metadata. Inadequate evidence or confidence yields zero entry confidence and prevents new paper entries. Existing eligibility, timing, risk, exposure, cooldown and hourly request limits remain binding; every actual transport attempt consumes a request allowance. Prompt/model/threshold changes invalidate cached forecasts without deleting history. Open positions retain ordinary management and confirmed settlement behavior.

Confidence measures answer-distribution concentration. It does not establish future forecasting accuracy or profitability; Event settlement calibration and fixed-horizon sentiment outcomes measure observed results. Optional crypto setup evaluations remain informational alongside deterministic strategy decisions.

## Migration

The upgrade adds `user_settings.ai_prompt_overrides` without removing existing prompts, credentials, observations or trading history. Startup migration is additive and repeatable. No destructive data migration is required.
