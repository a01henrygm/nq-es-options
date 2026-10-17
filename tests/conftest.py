"""Shared TEST DATA. Everything here is synthetic and exists only so calculations can be checked in isolation."""
from __future__ import annotations
import math
from datetime import date, datetime, timedelta

import pytest

from backend.models import ChainSnapshot, OptionContract
from backend.services.analytics import bs_gamma, bs_delta, year_fraction
from backend.timeutil import UTC, ET

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)          # Wednesday, 11:00 ET, market open
EXPIRY = date(2026, 10, 16)


def make_chain(spot=500.0, n_strikes=21, step=5.0, iv=0.20, oi=1000, expiry=EXPIRY, now=NOW, ts=NOW):
    """Synthetic symmetric chain with Black-Scholes greeks. TEST DATA ONLY."""
    T = year_fraction(expiry, now)
    out = []
    for i in range(n_strikes):
        k = spot + (i - n_strikes // 2) * step
        for r in "CP":
            g = bs_gamma(spot, k, T, iv)
            d = bs_delta(spot, k, T, iv, r)
            mid = max(0.05, abs(spot - k) * (0.5 if (r == "C") == (spot > k) else 0) + spot * iv * math.sqrt(T) * 0.4 * math.exp(-0.5 * ((k - spot) / (spot * iv * math.sqrt(T))) ** 2))
            out.append(OptionContract(ticker=f"O:TEST{expiry:%y%m%d}{r}{int(k * 1000):08d}", right=r, strike=k, expiry=expiry,
                                      bid=round(mid * 0.98, 2), ask=round(mid * 1.02, 2), last=round(mid, 2), volume=100.0, oi=float(oi),
                                      iv=iv, delta=d, gamma=g, theta=-0.1, vega=0.2, quote_ts=ts))
    return out


@pytest.fixture
def chain():
    return make_chain()


@pytest.fixture
def snap(chain):
    return ChainSnapshot("test", "QQQ", NOW, 500.0, NOW, chain, "hash1")


def massive_item(strike=500.0, right="call", expiry="2026-10-16", ts_ns=1_760_454_000_000_000_000):
    """A response item shaped like the documented Massive chain snapshot. TEST DATA ONLY."""
    return {"details": {"ticker": f"O:QQQ261016{'C' if right == 'call' else 'P'}00500000", "contract_type": right,
                        "expiration_date": expiry, "strike_price": strike, "shares_per_contract": 100},
            "greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.1, "vega": 0.3}, "implied_volatility": 0.21, "open_interest": 1234,
            "last_quote": {"bid": 1.0, "ask": 1.2, "last_updated": ts_ns}, "last_trade": {"price": 1.1, "sip_timestamp": ts_ns},
            "day": {"volume": 77}, "underlying_asset": {"price": 500.12, "last_updated": ts_ns, "ticker": "QQQ"}}
