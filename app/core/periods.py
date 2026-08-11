"""
Reporting periods for the dashboard.

Every KPI used to be an all-time total, which answers the wrong question: a shop
owner needs "how is this month against last month", not "how much have we ever
sold". These helpers turn a period name into the two ranges a comparison needs —
the current one and the one immediately before it.

Boundaries are computed at a fixed UTC offset (Uzbekistan is UTC+5 year-round,
no DST) rather than in UTC. Otherwise "today" would start at 05:00 local and
the evening's orders would land in the wrong day.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from app.core.config import settings

# period name -> label shown in the panel
PERIODS = {
    "today": "Bugun",
    "week": "Shu hafta",
    "month": "Shu oy",
    "all": "Butun davr",
}

DEFAULT_PERIOD = "month"


def _tz() -> timezone:
    return timezone(timedelta(hours=settings.TIMEZONE_OFFSET_HOURS))


def normalize(period: Optional[str]) -> str:
    return period if period in PERIODS else DEFAULT_PERIOD


def bounds(period: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[datetime]]:
    """Returns (start, prev_start, prev_end) as tz-aware datetimes.

    The current range is [start, now); the one before it is [prev_start, start),
    an equal-length window so the two are comparable. "all" returns all-None,
    meaning "apply no date filter and offer no comparison".
    """
    period = normalize(period)
    if period == "all":
        return None, None, None

    now = datetime.now(_tz())
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if period == "today":
        start = midnight
        prev_start = start - timedelta(days=1)
    elif period == "week":
        start = midnight - timedelta(days=midnight.weekday())   # Monday
        prev_start = start - timedelta(days=7)
    else:  # month
        start = midnight.replace(day=1)
        # Step one day back from the 1st to land in the previous month, whatever
        # its length, then snap to its 1st.
        prev_start = (start - timedelta(days=1)).replace(day=1)

    return start, prev_start, start


def growth(current: float, previous: float) -> Optional[float]:
    """Percent change, or None when there is no baseline to compare against.

    None is deliberate: rendering "+100%" against a zero previous period reads
    as real growth when it only means the metric is new.
    """
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)
