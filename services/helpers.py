"""
services/helpers.py
-------------------
Lazy proxy that breaks the circular import between main_new.py / main.py
and the route blueprints.

All route blueprints that previously did:
    from main import some_helper, ...

should instead do:
    from services.helpers import some_helper, ...

This module defers the actual import until the first attribute access so that
Python's import machinery can fully initialise the main module before any
symbol is resolved.
"""

import importlib
import sys


def _get_main():
    """Return the already-loaded main module (main_new or main)."""
    for name in ("main_new", "main"):
        mod = sys.modules.get(name)
        if mod is not None:
            return mod
    # Fallback: import main (should already be loaded at app startup)
    return importlib.import_module("main")


class _LazyProxy:
    """Proxy that fetches attributes from the main module on demand."""

    def __getattr__(self, name):
        mod = _get_main()
        try:
            return getattr(mod, name)
        except AttributeError:
            raise AttributeError(
                f"'services.helpers' proxy: '{name}' not found in {mod.__name__}"
            )


_proxy = _LazyProxy()


# ---------------------------------------------------------------------------
# Re-export everything via module-level __getattr__ so that
#   from services.helpers import foo
# works without enumerating each symbol.
# ---------------------------------------------------------------------------

def __getattr__(name):  # noqa: N807  (module-level __getattr__)
    return getattr(_proxy, name)
