# Crypto & Securities Dashboard Release and Personal-Instance Routine

When a change is an app upgrade or the user asks to release/deploy it, complete this sequence before reporting completion:

1. Update the application version, release notes in `README.md`, and any affected documentation.
2. Run proportionate verification. For frontend changes, run `npm run build` in `frontend`; for Python changes, run at least `python -m py_compile` for the modified modules. Run `git diff --check`.
3. Commit all intended source and built-frontend artifacts, then push the commit to `origin/main`.
4. Create and publish a GitHub release tagged `v<APP_VERSION>` from that pushed commit, with concise user-facing release notes.
5. Upgrade the personal instance at `/home/jcavallarojr/crypto_alert_app` to that release. First inspect its worktree and preserve unrelated user changes; do not use a hard reset or forced checkout on a dirty worktree. Install required dependencies, rebuild the frontend, run applicable migrations, and restart `crypto-dashboard.service`.
6. Confirm deployment: the service is `active (running)`, the local app endpoint on port `5010` responds successfully, and the deployed checkout resolves to the release commit/tag. Report any verification limitation or unresolved warning.

The personal instance is a separate checkout from this source repository. Do not report an upgrade as complete until the release is published and the running personal instance has passed the checks above.
