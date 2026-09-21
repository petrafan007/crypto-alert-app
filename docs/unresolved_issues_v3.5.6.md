# Unresolved Issues Found During the v3.5.6 Work

Date recorded: 2026-09-21

This document contains issues that were observed while repairing and validating the AI Copilot for v3.5.6 but were outside that release's Copilot scope. It does not repeat Copilot defects fixed in v3.5.6. Items are separated into confirmed application defects, dependency findings, and verification or operational limitations.

## 1. Live Webull orders with two-factor authentication fail before submission

- **Priority:** Critical if live Webull order placement is used with 2FA enabled
- **Status:** Confirmed application defect; unresolved
- **Affected code:** `routes/system.py`, in `api_webull_place_order`
- **Observed behavior:** Five Webull order tests returned HTTP 500 instead of reaching submission or returning the expected provider rejection. The affected cases covered equity cash-amount, option, futures, and Event Contract orders after a valid 2FA token.
- **Root cause:** The function contains an inner `import time` inside the replace-order branch. Python therefore treats `time` as a local variable throughout the entire function. Requests that use a previously verified 2FA token reach `time.time()` before that conditional import executes and raise `UnboundLocalError: cannot access local variable 'time' where it is not associated with a value`.
- **Impact:** Valid live orders protected by 2FA can fail with a generic server error. Paper-order handling and requests that do not enter this live 2FA path are separate.
- **Recommended fix:** Remove the inner `import time` and use the module-level import already present at the top of `routes/system.py`. Rerun `tests.test_webull_event_order_2fa` and the wider Webull order suite.

## 2. Frontend dependency audit reports seven vulnerable packages

- **Priority:** High for build/development environments; production exploitability requires separate path analysis
- **Status:** Confirmed dependency findings; unresolved
- **Observed behavior:** `npm audit --json` reported seven vulnerable installed packages: five high, one moderate, and one low. No critical advisory was reported.
- **Affected packages:**
  - `vite` — direct development/build dependency, high aggregate severity
  - `rollup` — transitive, high
  - `postcss` — transitive, high
  - `nanoid` — transitive, high
  - `browserslist` — transitive, high
  - `esbuild` — transitive, moderate
  - `@babel/core` — transitive, low
- **Practical boundary:** Most reported paths concern development servers, build tooling, source maps, or malicious build inputs. The deployed application serves prebuilt static files and does not expose Vite's development server. That reduces exposure but does not make the advisories resolved.
- **Recommended fix:** Upgrade Vite and its locked transitive dependencies in a dedicated dependency release, inspect the resulting major-version/build changes, rebuild the frontend, rerun the frontend and route tests, and repeat `npm audit`. Do not use a blind forced audit fix without reviewing the dependency changes.

## 3. Event AI configuration test depends on an encryption key that the test does not provide

- **Priority:** Medium for test reliability; production secret protection is operating as designed
- **Status:** Confirmed test-environment defect; unresolved
- **Affected test:** `tests/test_event_algo.py::EventAlgoTests::test_update_config_persists_ai_config`
- **Observed behavior:** The full test run failed when the test tried to persist `test-gemini-key` without `CREDENTIALS_ENCRYPTION_KEY` or a persisted test key.
- **Root cause:** `event_algo.update_config` correctly calls `credential_security.encrypt_secret`, which correctly rejects a credential write when no encryption key exists. The test does not establish an isolated Fernet key or mock encryption.
- **Impact:** A clean or isolated full-suite run can fail even when production behavior is correct. This weakens confidence in release-wide regression results and can hide new failures among expected environment failures.
- **Recommended fix:** Give this test an isolated temporary Fernet key and clear the credential-security key cache during setup/teardown. Keep the production fail-closed behavior unchanged.

## 4. Python UTC datetime APIs generate widespread deprecation warnings

- **Priority:** Medium maintenance risk
- **Status:** Confirmed technical debt; unresolved
- **Observed behavior:** The test run emitted repeated Python 3.13 deprecation warnings for `datetime.utcnow()` and `datetime.utcfromtimestamp()`.
- **Scope:** A repository search found approximately 280 calls across 46 files in services, routes, engine code, and tests.
- **Impact:** These APIs are scheduled for removal in a future Python version. The present code still runs, but a future runtime upgrade can turn the warning backlog into failures. Mixing naive UTC values with timezone-aware values also increases timestamp-comparison risk.
- **Recommended fix:** Migrate in controlled groups to timezone-aware UTC values such as `datetime.now(timezone.utc)` and `datetime.fromtimestamp(value, timezone.utc)`. Database columns and serialization must be reviewed per group so the migration does not create naive/aware comparison regressions.

## 5. Some tests leave SQLite connections open

- **Priority:** Low
- **Status:** Confirmed test-harness warning; unresolved
- **Observed behavior:** The full suite emitted `ResourceWarning: unclosed database` for temporary SQLite connections during portfolio/audit tests.
- **Impact:** This is primarily test-process resource leakage. In repeated or parallel CI runs it can cause noisy output, file-lock problems, or resource exhaustion and can obscure more important warnings.
- **Recommended fix:** Identify the fixtures creating temporary SQLAlchemy engines/application contexts and explicitly close sessions, dispose engines, and remove application contexts during teardown.

## 6. Full-suite coverage includes 123 skipped tests

- **Priority:** Medium verification limitation
- **Status:** Unresolved coverage gap
- **Observed behavior:** The repository-wide run executed 685 tests and skipped 123. Of the tests that ran, 679 passed and six produced the issues described above.
- **Impact:** A passing focused suite does not establish that every provider-backed, PostgreSQL-specific, network-dependent, or environment-dependent path has been exercised.
- **Recommended fix:** Categorize skip reasons, provision required isolated services and credentials where safe, and create a release CI profile that distinguishes intentional platform skips from missing prerequisites.

## 7. NewsAPI reliability remains deferred

- **Priority:** Medium operational limitation
- **Status:** Known integration issue; intentionally unchanged
- **Observed behavior:** NewsAPI has previously been unreliable or rate limited in this installation. v3.5.6 ensures the Copilot respects the web-search enable setting and can continue using stored context or other configured search sources, but it does not repair or replace NewsAPI.
- **Impact:** Fresh-news grounding can be incomplete when NewsAPI is unavailable. Search status and available alternative sources must be used to interpret an answer's freshness.
- **Recommended next step:** Diagnose the saved NewsAPI key, plan limits, request responses, cooldown behavior, and query eligibility separately. Retain graceful fallback and avoid making Copilot availability depend on NewsAPI alone.

## Verification record

- The focused Copilot/provider/audit set passed 75 tests with two intentional skips.
- The complete discovery run reported 685 tests: 679 passed, six failed, and 123 skipped.
- The production frontend build completed successfully.
- Python compilation, `git diff --check`, and tracked-file secret scanning passed for v3.5.6.
- The v3.5.6 dashboard and background worker were deployed and active; local and public endpoints returned HTTP 200.

