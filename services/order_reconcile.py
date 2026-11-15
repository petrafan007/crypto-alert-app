"""Decide whether a provider's copy of an order may replace the stored one.

Order lists from a provider arrive from different endpoints and caches, so an
older copy can arrive after a newer one. These rules keep the stored order
moving forward only:

* A confirmed final state (filled, cancelled, rejected, expired) is never
  replaced by an open-state copy.
* One final state replaces another, or an open state replaces an open state,
  only when the incoming copy is not older than the stored one.
* The filled quantity never decreases; fill price and fee come from the copy
  with the largest fill.

Nothing is invented: when the incoming copy is not accepted, the stored values
are kept unchanged.
"""

TERMINAL_STATUSES = {
    'FILLED', 'COMPLETED', 'CANCELLED', 'CANCELED', 'REJECTED', 'FAILED', 'EXPIRED', 'EXPIRED_IN_MATCH',
}


def normalise_status(value):
    return str(value or '').strip().upper() or None


def is_terminal(status):
    return normalise_status(status) in TERMINAL_STATUSES


def accept_status(stored_status, stored_updated_at, incoming_status, incoming_updated_at):
    """True if the incoming status may replace the stored one."""
    stored = normalise_status(stored_status)
    incoming = normalise_status(incoming_status)
    if incoming is None:
        return False
    if stored is None or stored == incoming:
        return True
    if is_terminal(stored) and not is_terminal(incoming):
        return False
    if stored_updated_at and incoming_updated_at and incoming_updated_at < stored_updated_at:
        return False
    return True


def fill_advances(stored_filled, incoming_filled, tolerance=1e-12):
    """True if the incoming filled quantity is at least the stored one."""
    if incoming_filled is None:
        return False
    return stored_filled is None or float(incoming_filled) + tolerance >= float(stored_filled)


def later(first, second):
    """The later of two optional datetimes."""
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)
