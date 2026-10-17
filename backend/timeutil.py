"""Time helpers. Everything is stored in UTC and shown in Eastern Time."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_et(dt: datetime) -> datetime:
    return dt.astimezone(ET)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def parse_et(v) -> datetime | None:
    """Parse a timestamp string that is in Eastern Time without an offset, e.g. '2026-10-14 11:00:00'.
    Tolerates a trailing label such as ' ET (Delayed)'. Returns UTC. None if missing or unreadable (never invented)."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", s)
        if not m:
            return None
        try:
            dt = datetime(*(int(g) for g in m.groups(default="0")))
        except ValueError:
            return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=ET)).astimezone(UTC)


def parse_ts(v) -> datetime | None:
    """Parse a provider timestamp. Accepts epoch in ns/us/ms/s or an ISO string.

    Returns None when the value is missing or unreadable. We never invent a timestamp.
    Naive ISO strings are treated as UTC (documented assumption).
    """
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            x = float(v)
            if x <= 0:
                return None
            if x > 1e17:
                x /= 1e9
            elif x > 1e14:
                x /= 1e6
            elif x > 1e11:
                x /= 1e3
            return datetime.fromtimestamp(x, tz=UTC)
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (ValueError, OverflowError, OSError):
        return None
