# Crypto Alert App: GitHub Development & Deployment Protocol

This document defines the mandatory workflow for all code changes, versioning, and deployment verification.

## 1. Development Environment
*   **Source of Truth**: All modifications **MUST** be performed in the `/home/jcavallarojr/crypto_alert_app_source` directory.
*   **Production Safety**: The personal production instance at `/home/jcavallarojr/crypto_alert_app` is **STRICTLY OFF-LIMITS**. Never modify files directly in that directory. All updates must flow through GitHub.

## 2. Versioning & Branching
*   **Increments**: Versions must be incremented by **0.1** for every release (e.g., from `1.03` to `1.1`, then `1.2`).
*   **Beta Status**: All new versions **MUST** maintain the "beta" suffix (e.g., `Version 1.1 Beta`) unless the user explicitly authorizes a stable release.
*   **Git Tags**: Every release must be formally tagged in git (e.g., `git tag -a v1.1-beta`) and pushed to GitHub.
*   **GitHub Releases**: Use `gh release create` to document changes. To ensure the new version is visible as the primary update, **ALWAYS** include the `--latest` flag (e.g., `gh release create v1.1-beta --title "Version 1.1 Beta" --notes "Release notes here" --latest`).
*   **Beta vs Stable**: New features always start as "beta". Even if marked "beta" in the title, use the `--latest` flag so the app's upgrade system can detect it as the most recent valid upgrade target.

## 3. Deployment Verification Process (Mandatory)
Before any change is considered "complete," it must be verified in the test environment:

1.  **Sync Test Repo**: Pull the latest code into `/home/jcavallarojr/crypto_alert_app_newusertest`.
2.  **Verify Upgrade**: 
    *   Start the app in the background on port 5016.
    *   Use a headless browser script (Puppeteer) to log in as `jcavallarojr`.
    *   Navigate to Settings and click the **"Upgrade App"** button.
    *   Confirm the app restarts and the frontend automatically reloads with the new version string in the footer.
    *   Confirm any new changes/fixed that can be tested in the front end work properly.
3.  **Cross-Platform Port Logic**: Ensure the "Intelligent Port Detection" preserves existing ports (5010 for production) and doesn't break connectivity.

## 4. Summary of Constraints
*   **NO** direct edits to production (`crypto_alert_app`).
*   **NO** skipping the automated browser verification step.
*   **NO** jumping version numbers beyond the 0.1 increment.
