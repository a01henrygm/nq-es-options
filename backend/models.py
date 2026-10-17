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
