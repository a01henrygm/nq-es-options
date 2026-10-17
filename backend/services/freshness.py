"""Data-freshness classification.

Freshness is judged ONLY from provider-supplied observation timestamps, never from when the browser refreshed.
Statuses:
  live              market open, observation age within the real-time threshold
  delayed           market open, plan is delayed and age is within the expected delay window
  closed_last_session  market closed and the observation comes from the most recent session
  stale             too old for the situation (the value is the last known one, not current)
  no_source_time    provider gave no timestamp; we do not invent one
  daily_snapshot    open interest style data that only updates once per day by design
  unavailable       nothing to show
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

from . import market

REALTIME_MAX_AGE = timedelta(seconds=120)
DELAYED_MAX_AGE = timedelta(minutes=20)       # 15 minute exchange delay + 5 minutes of slack
CLOSE_GRACE = timedelta(minutes=30)           # last prints may trail the close slightly


@dataclass
class Freshness:
    status: str
    age_seconds: float | None
    market_state: str
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify(source_ts: datetime | None, now: datetime, plan: str = "delayed", kind: str = "quote") -> Freshness:
    state = market.market_state(now)
    if source_ts is None:
        return Freshness("no_source_time", None, state, "The provider did not supply a timestamp for this data.")
    age = (now - source_ts).total_seconds()
    if age < -120:
        return Freshness("stale", age, state, "Source timestamp is in the future; treat this data as unreliable.")
    if kind == "open_interest":
        return Freshness("daily_snapshot", age, state,
                         "Open interest updates once per day (end of the previous trading day). It is not an intraday figure.")
    if state == "open":
        if plan == "realtime":
            ok, label = age <= REALTIME_MAX_AGE.total_seconds(), "live"
            limit = "2 minutes"
        else:
            ok, label = age <= DELAYED_MAX_AGE.total_seconds(), "delayed"
            limit = "20 minutes (15 minute delay plus slack)"
        if ok:
            return Freshness(label, age, state, f"Within the expected window for a {plan} plan.")
        return Freshness("stale", age, state, f"Market is open but the newest observation is older than {limit}.")
    # market closed / pre / after hours: the newest data should come from the latest session
    if source_ts >= market.last_close(now) - CLOSE_GRACE:
        return Freshness("closed_last_session", age, state, "Market is closed. This is the last session's data, not a live reading.")
    return Freshness("stale", age, state, "Observation is older than the most recent session.")
