"""US equity/ETF options market calendar (NYSE rules). Rules-based: weekends, holidays, early closes, DST via zoneinfo.

Limitation: special one-off closures (e.g. national days of mourning) are not predicted. Futures sessions
trade on a different schedule and are NOT modeled here.
"""
from __future__ import annotations
from datetime import date, datetime, time, timedelta

from ..timeutil import ET


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, m: int, weekday: int) -> date:
    d = date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(y, month, ((h + l - 7 * m + 114) % 31) + 1)


def _observed(d: date) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def holidays(y: int) -> dict:
    h = {}
    ny = date(y, 1, 1)
    if ny.weekday() != 5:  # NYSE does not observe a Saturday New Year's on the prior Friday
        h[_observed(ny)] = "New Year's Day"
    h[_nth_weekday(y, 1, 0, 3)] = "Martin Luther King Jr. Day"
    h[_nth_weekday(y, 2, 0, 3)] = "Presidents' Day"
    h[easter(y) - timedelta(days=2)] = "Good Friday"
    h[_last_weekday(y, 5, 0)] = "Memorial Day"
    h[_observed(date(y, 6, 19))] = "Juneteenth"
    h[_observed(date(y, 7, 4))] = "Independence Day"
    h[_nth_weekday(y, 9, 0, 1)] = "Labor Day"
    h[_nth_weekday(y, 11, 3, 4)] = "Thanksgiving"
    h[_observed(date(y, 12, 25))] = "Christmas"
    return h


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def early_close(d: date) -> bool:
    if not is_trading_day(d):
        return False
    if d == _nth_weekday(d.year, 11, 3, 4) + timedelta(days=1):
        return True
    if d.month == 12 and d.day == 24:
        return True
    return d.month == 7 and d.day == 3 and d.weekday() < 4


def session(d: date):
    """Regular session (open, close) as aware ET datetimes, or None if closed all day."""
    if not is_trading_day(d):
        return None
    close = time(13, 0) if early_close(d) else time(16, 0)
    return datetime.combine(d, time(9, 30), tzinfo=ET), datetime.combine(d, close, tzinfo=ET)


def market_state(now: datetime) -> str:
    """'open', 'premarket', 'afterhours' or 'closed' for the regular US options session."""
    n = now.astimezone(ET)
    s = session(n.date())
    if s is None:
        return "closed"
    if s[0] <= n < s[1]:
        return "open"
    if time(4, 0) <= n.time() < time(9, 30) and n < s[0]:
        return "premarket"
    if s[1] <= n < datetime.combine(n.date(), time(20, 0), tzinfo=ET):
        return "afterhours"
    return "closed"


def last_close(now: datetime) -> datetime:
    """Close time of the most recent regular session that has already ended."""
    n = now.astimezone(ET)
    d = n.date()
    for _ in range(10):
        s = session(d)
        if s and s[1] <= n:
            return s[1]
        d -= timedelta(days=1)
    raise RuntimeError("no session found")


def next_open(now: datetime) -> datetime:
    n = now.astimezone(ET)
    d = n.date()
    for _ in range(10):
        s = session(d)
        if s and s[0] > n:
            return s[0]
        d += timedelta(days=1)
    raise RuntimeError("no session found")
