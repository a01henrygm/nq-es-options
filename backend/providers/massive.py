"""Massive (formerly Polygon.io) options provider.

Endpoint used: GET /v3/snapshot/options/{underlyingAsset}  (option chain snapshot).
Per Massive's documentation this endpoint is NOT included in the free Options Basic plan; it needs a paid
Options plan (15-minute delayed or real-time). Open interest is the end-of-previous-trading-day figure.
Index options need the "I:" prefix (for example I:NDX) or greeks and IV come back empty.

The API key is sent in an Authorization header, never in a URL, so it cannot leak into logs or next_url links.
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta

import httpx

from ..config import Settings
from ..models import ChainSnapshot, OptionContract
from ..timeutil import parse_ts, utcnow
from .base import OptionsProvider, ProviderError

log = logging.getLogger("provider.massive")


class RateLimiter:
    """Keeps requests under N per minute (spacing them out evenly)."""

    def __init__(self, rpm: int, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep, self.last = 60.0 / rpm, clock, sleep, None

    def wait(self):
        now = self.clock()
        if self.last is not None and now - self.last < self.interval:
            self.sleep(self.interval - (now - self.last))
        self.last = self.clock()


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize_contract(item: dict) -> OptionContract | None:
    d = item.get("details") or {}
    try:
        strike = float(d["strike_price"])
        expiry = date.fromisoformat(d["expiration_date"])
        right = {"call": "C", "put": "P"}[d["contract_type"]]
    except (KeyError, ValueError, TypeError):
        return None
    g, q, t, day = (item.get(k) or {} for k in ("greeks", "last_quote", "last_trade", "day"))
    bid, ask = _num(q.get("bid")), _num(q.get("ask"))
    return OptionContract(
        ticker=d.get("ticker", ""), right=right, strike=strike, expiry=expiry,
        multiplier=int(d.get("shares_per_contract") or 100),
        bid=bid, ask=ask, last=_num(t.get("price")), volume=_num(day.get("volume")),
        oi=_num(item.get("open_interest")), iv=_num(item.get("implied_volatility")),
        delta=_num(g.get("delta")), gamma=_num(g.get("gamma")), theta=_num(g.get("theta")), vega=_num(g.get("vega")),
        quote_ts=parse_ts(q.get("last_updated")),
        trade_ts=parse_ts(t.get("sip_timestamp") or t.get("participant_timestamp")),
    )


def content_hash(contracts: list) -> str:
    rows = sorted((c.ticker, c.bid, c.ask, c.last, c.volume, c.oi, c.iv) for c in contracts)
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


class MassiveProvider(OptionsProvider):
    name = "massive"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, limiter: RateLimiter | None = None,
                 sleep=time.sleep):
        self.s = settings
        self.client = client or httpx.Client(timeout=20.0)
        self.limiter = limiter or RateLimiter(settings.max_rpm)
        self.sleep = sleep

    # -- low level -------------------------------------------------------------------------
    def _get(self, url: str, params: dict | None = None) -> dict:
        if not self.s.key_configured:
            raise ProviderError("auth", "No API key configured. Add MASSIVE_API_KEY to your .env file.")
        headers = {"Authorization": f"Bearer {self.s.api_key}"}
        for attempt in range(4):
            self.limiter.wait()
            try:
                r = self.client.get(url, params=params, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 3:
                    raise ProviderError("network", f"Could not reach the provider: {type(e).__name__}") from None
                self.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    raise ProviderError("schema", "Provider returned a response that was not JSON.", 200) from None
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                if attempt == 3:
                    raise ProviderError("rate_limit", "Provider rate limit hit repeatedly.", 429)
                self.sleep(min(wait, 60))
                continue
            if r.status_code in (401, 403):
                msg = self._message(r)
                kind = "plan" if r.status_code == 403 else "auth"
                raise ProviderError(kind, f"{msg} Check that the key is valid and that your plan includes options snapshots.", r.status_code)
            if r.status_code == 404:
                raise ProviderError("not_found", self._message(r), 404)
            if r.status_code >= 500 and attempt < 3:
                self.sleep(2 ** attempt)
                continue
            raise ProviderError("server", f"Provider error {r.status_code}: {self._message(r)}", r.status_code)
        raise ProviderError("network", "Provider did not respond.")

    @staticmethod
    def _message(r: httpx.Response) -> str:
        try:
            j = r.json()
            return str(j.get("message") or j.get("error") or j.get("status") or "")[:200]
        except ValueError:
            return r.text[:120]

    # -- chain -----------------------------------------------------------------------------
    def _spot(self, underlying: str):
        j = self._get(f"{self.s.base_url}/v3/snapshot/options/{underlying}", {"limit": 1})
        res = j.get("results") or []
        u = (res[0].get("underlying_asset") if res else None) or {}
        price = _num(u.get("price")) or _num(u.get("value"))
        return price, parse_ts(u.get("last_updated"))

    def fetch_chain(self, underlying: str, *, max_dte: int, strike_window: float) -> ChainSnapshot:
        spot, spot_ts = self._spot(underlying)
        params = {"limit": 250, "sort": "expiration_date", "order": "asc",
                  "expiration_date.lte": (date.today() + timedelta(days=max_dte)).isoformat()}
        if spot:
            params["strike_price.gte"] = round(spot * (1 - strike_window), 2)
            params["strike_price.lte"] = round(spot * (1 + strike_window), 2)
        url, contracts, pages = f"{self.s.base_url}/v3/snapshot/options/{underlying}", [], 0
        while url and pages < 60:
            j = self._get(url, params if pages == 0 else None)
            for item in j.get("results") or []:
                c = normalize_contract(item)
                if c:
                    contracts.append(c)
                u = item.get("underlying_asset") or {}
                if not spot:
                    spot, spot_ts = _num(u.get("price")) or _num(u.get("value")), parse_ts(u.get("last_updated"))
            url, pages = j.get("next_url"), pages + 1
        return ChainSnapshot(self.name, underlying, utcnow(), spot, spot_ts, contracts, content_hash(contracts))
