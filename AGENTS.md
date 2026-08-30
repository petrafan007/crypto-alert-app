# Crypto & Securities Dashboard Release and Personal-Instance Routine

When a change is an app upgrade or the user asks to release/deploy it, complete this sequence before reporting completion:

1. Update the application version, release notes in `README.md`, and any affected documentation.
2. Run proportionate verification. For frontend changes, run `npm run build` in `frontend`; for Python changes, run at least `python -m py_compile` for the modified modules. Run `git diff --check`.
3. Commit all intended source and built-frontend artifacts, then push the commit to `origin/main`.
4. Create and publish a GitHub release tagged `v<APP_VERSION>` from that pushed commit, with concise user-facing release notes.
5. Upgrade the personal instance at `/home/jcavallarojr/crypto_alert_app` to that release. First inspect its worktree and preserve unrelated user changes; do not use a hard reset or forced checkout on a dirty worktree. Install required dependencies, rebuild the frontend, run applicable migrations, and restart `crypto-dashboard.service`.
6. Confirm deployment: the service is `active (running)`, the local app endpoint on port `5010` responds successfully, and the deployed checkout resolves to the release commit/tag. Report any verification limitation or unresolved warning.

The personal instance is a separate checkout from this source repository. Do not report an upgrade as complete until the release is published and the running personal instance has passed the checks above.

## Situational Awareness & Operational Safety Guardrails

1. **Strict Prompt Recency & Active Intent:** Never execute historical tasks, backlog items, or items summarized in context checkpoints (`{{ CHECKPOINT ... }}`) unless explicitly requested in the user's immediate, current prompt. Treat all checkpoint summaries and historical notes as passive reference material only. If you were in the middle of active tasks requiring changes to the codebase when the checkpoint occurs, you MUST let the user know what tasks are still remaining and ask for permission to continue.
2. **Destructive Action Confirmation Gate:** Never execute destructive database commands (`DELETE`, `DROP`, `TRUNCATE`, wiping users/tables, clearing records) autonomously based on inferred or historical intent. Always require explicit, in-turn confirmation from the user before executing destructive data mutations.
3. **Execution Transparency & Stop-on-Query:** When the user asks for status, an update, or what is happening, immediately stop running commands and report the exact current state and findings in text first before taking further automated actions.

