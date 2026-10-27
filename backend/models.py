"""Normalized data models. A field the provider did not supply stays None; we never fill it in."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date, datetime


@dataclass
class OptionContract:
    ticker: str
    right: str                 # "C" or "P"
    strike: float
    expiry: date
    multiplier: int = 100
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    oi: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    quote_ts: datetime | None = None
    trade_ts: datetime | None = None

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expiry"] = self.expiry.isoformat()
        d["quote_ts"] = self.quote_ts.isoformat() if self.quote_ts else None
        d["trade_ts"] = self.trade_ts.isoformat() if self.trade_ts else None
        d["mid"] = self.mid
        return d


# Roots whose standard (monthly) options are AM-settled: they stop trading the evening before and settle at the open.
AM_SETTLED_ROOTS = {"SPX", "NDX", "RUT"}


def expiry_cutoff(c: OptionContract) -> datetime:
    """When a contract stops existing: 09:30 ET for AM-settled index roots (SPX, NDX, RUT), 16:00 ET otherwise (SPXW, NDXP, ETFs)."""
    import re
    from datetime import time
    from .timeutil import ET
    m = re.match(r"(?:O:)?([A-Z]+)\d", c.ticker or "")
    root = m.group(1) if m else ""
    t = time(9, 30) if root in AM_SETTLED_ROOTS else time(16, 0)
    return datetime.combine(c.expiry, t, tzinfo=ET)


def drop_expired(contracts: list, now: datetime) -> list:
    """Remove contracts that have already expired. Providers keep listing a day's options for hours after they expire,
    with greeks still attached, and counting them would draw walls and GEX from contracts that no longer exist."""
    return [c for c in contracts if expiry_cutoff(c) > now]


@dataclass
class ChainSnapshot:
    provider: str
    underlying: str
    retrieved_at: datetime
    spot: float | None
    spot_ts: datetime | None
    contracts: list = field(default_factory=list)
    content_hash: str = ""
    snapshot_id: int | None = None
    from_database: bool = False
    spot_note: str | None = None      # set when the underlying price did not come straight from the provider

    @property
    def source_ts(self) -> datetime | None:
        """Newest provider-supplied timestamp in the snapshot (spot or any quote). None if none were supplied."""
        ts = [t for t in [self.spot_ts] + [c.quote_ts for c in self.contracts] if t]
        return max(ts) if ts else None
