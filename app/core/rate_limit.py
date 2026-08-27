"""
Lightweight in-process rate limiting for the AI message path and file upload.

Not DB-backed on purpose — unlike login throttling (app/core/security.py),
which must survive a distributed attacker hopping across IPs, this exists to
blunt a single runaway chat or script hammering the AI/import path within one
process. Spread across several workers it narrows the limit rather than
closing it completely, the same tradeoff app/api/bot_webhook.py already
accepts for its update-dedup window — and the alternative (a DB round-trip on
every incoming message) is exactly the per-request cost this project fought
to remove (see app/db/base.py).
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

_windows: Dict[str, Deque[float]] = defaultdict(deque)

# Once the number of distinct keys we're tracking gets large, sweep out the
# ones whose window has gone fully idle rather than growing forever.
_PRUNE_ABOVE = 20_000


def allow(key: str, max_calls: int, window_seconds: float) -> bool:
    """True if this call is within (key, max_calls, window_seconds); records it if so."""
    now = time.monotonic()
    dq = _windows[key]
    cutoff = now - window_seconds
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= max_calls:
        return False
    dq.append(now)
    if len(_windows) > _PRUNE_ABOVE:
        _prune()
    return True


def _prune() -> None:
    for k in [k for k, dq in _windows.items() if not dq]:
        del _windows[k]
