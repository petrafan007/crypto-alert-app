# Session Progress Report: Crypto Alert App Cleanup & GitHub Deployment

**Date:** May 6, 2026
**Status:** Version 1.01 Beta Pushed to GitHub

## 1. Version 1.01 Beta Updates
*   **Branding Refresh:** Renamed "Crypto Dashboard" to "Crypto Alert App" across the entire UI (Login, Navigation).
*   **README Enhancement:** Added a comprehensive application description and corrected the production ports (defaulting to 5016).
*   **Help Page Audit:** Updated the Help page for accuracy, correcting AI provider lists (listing Perplexity Sonar instead of Anthropic).
*   **Robust Upgrade System:**
    *   Fixed `routes/system.py` to correctly resolve the `upgrade.sh` path in the root directory.
    *   Improved `upgrade.sh` to support both `.venv` and `venv` virtual environments.
    *   Added logic to `upgrade.sh` to automatically restart the manual Python process in test environments.
    *   Implemented seamless frontend polling in `Settings.jsx` that automatically reloads the page once the service comes back online after an upgrade.

## 2. Codebase Audit & Cleanup
*   **Legacy Data Purge:** Deleted >450MB of obsolete SQLite databases (`.db`), backups (`.bak`, `.backup`), and temporary logs.
*   **Circular Dependency Resolution:** Standardized all database operations to use `core.extensions.db`, eliminating 500 errors caused by multiple SQLAlchemy instances.

## Next Steps
- Continue testing all application features to ensure no regressions from the migration.
- Monitor the new auto-upgrade mechanism in production environments.
- Update `DATABASE_SCHEMA.md` to reflect the final PostgreSQL structure.

## Known Issues
- None. Service is stable and auto-upgrade is verified functional.
