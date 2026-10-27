"""Cboe delayed-quotes options provider (free, no account, no API key).

Reads Cboe's public delayed-quote files, one JSON file per underlying:
    https://cdn.cboe.com/api/global/delayed_quotes/options/_NDX.json     (index options use a leading underscore)
    https://cdn.cboe.com/api/global/delayed_quotes/options/QQQ.json      (ETFs use the plain ticker)

The data is delayed (about 15 minutes). Open interest is the previous trading day's figure.

TIMES. The file has two clocks, and they are in DIFFERENT time zones (checked against the live files, Oct 2026):
  * data.last_trade_time  - when the index price was last observed, Eastern Time ("2026-10-26T16:14:59").
  * timestamp             - when Cboe WROTE the file, in UTC ("2026-10-27 00:45:01" = 8:45 PM ET). Cboe rewrites the
                            file all night, so this clock keeps moving even when the data is frozen at the close.
The SOURCE time is the older of the two, so a file rewritten at night is still labeled with the close it holds, and
nothing can be stamped in the future. If the file has no usable time it is labeled "no source time"; nothing is invented.

GAMMA. Cboe rounds gamma to 4 decimals. For NDX (~29,000) and SPX (~7,700) a real option's gamma is 0.0000-0.0010, so
the rounded figure is mostly rounding error (about 12-15% per contract, and it moved SPX total GEX by 30% on a live
file). Gamma is therefore left empty here and recomputed exactly from Cboe's implied volatility (Black-Scholes, the
same model the gamma flip uses). Delta, vega and theta are large enough that 4 decimals are fine and are kept.

EXPIRED CONTRACTS. Cboe keeps a day's expired options in the file (with greeks) until the next morning. They are
dropped once expired: 16:00 ET for PM-settled roots (NDXP, SPXW, ETFs), 09:30 ET for AM-settled monthlies (NDX, SPX).

NOTE: field names below follow what the file contained when this was written. Run diagnose.bat to confirm them on
your machine; it prints which fields are actually present. Check Cboe's terms for the data before sharing it.
"""
from __future__ import annotations
import logging
import re
from datetime import date, timedelta

import httpx

from ..config import Settings
from ..models import ChainSnapshot, OptionContract
from ..models import drop_expired
from ..timeutil import UTC, parse_et, to_et, utcnow
from .base import OptionsProvider, ProviderError
from .massive import content_hash, _num

log = logging.getLogger("provider.cboe")
OPT = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")
UA = {"User-Agent": "Mozilla/5.0 (personal analytics dashboard)", "Accept": "application/json"}


def normalize_option(o: dict) -> OptionContract | None:
    m = OPT.match(str(o.get("option", "")).strip())
    if not m:
        return None
    root, ymd, right, k = m.groups()
    try:
        expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6]))
    except ValueError:
        return None
    iv = _num(o.get("iv"))
    has_iv = iv is not None and iv > 0           # Cboe reports 0 when IV could not be computed
    g = lambda k: _num(o.get(k)) if has_iv else None
    return OptionContract(
        ticker=str(o["option"]).strip(), right=right, strike=int(k) / 1000, expiry=expiry, multiplier=100,
        bid=_num(o.get("bid")), ask=_num(o.get("ask")), last=_num(o.get("last_trade_price")), volume=_num(o.get("volume")),
        # gamma=None on purpose: Cboe's 4-decimal gamma is too coarse for index options; analytics recomputes it from iv
        oi=_num(o.get("open_interest")), iv=iv if has_iv else None, delta=g("delta"), gamma=None, theta=g("theta"), vega=g("vega"),
        quote_ts=None, trade_ts=parse_et(o.get("last_trade_time")))


SPOT_FIELDS = ("current_price", "price", "last_trade_price", "last")
FUTURE_SLACK = 300  # seconds; a source time further ahead of our clock than this is impossible and is rejected


def file_time(v, now):
    """Cboe's file 'timestamp' is UTC with no zone marker. If the UTC reading is impossible (in the future) but the
    Eastern reading is not, Cboe has gone back to Eastern and that reading is used instead."""
    if not v or not isinstance(v, str):
        return None
    et = parse_et(v)
    if et is None or "Z" in v or "+" in v:      # an explicit zone needs no guessing
        return et
    utc = to_et(et).replace(tzinfo=UTC)          # the same wall-clock reading, taken as UTC instead of Eastern
    for cand in (utc, et):
        if (cand - now).total_seconds() <= FUTURE_SLACK:
            return cand
    return None


def source_time(j, d, now):
    """The older of the index's last-trade time (Eastern) and the file-written time (UTC), never in the future."""
    ts = [t for t in (parse_et(d.get("last_trade_time")), file_time(j.get("timestamp"), now))
          if t is not None and (t - now).total_seconds() <= FUTURE_SLACK]
    return min(ts) if ts else None


def parity_spot(contracts):
    """Underlying price from option prices: strike + call mid - put mid at the strikes where they are closest (put-call parity)."""
    by = {}
    for c in contracts:
        if c.mid:
            by.setdefault(c.expiry, {}).setdefault(c.strike, {})[c.right] = c.mid
    for e in sorted(by):
        pairs = [(abs(v["C"] - v["P"]), k + v["C"] - v["P"]) for k, v in by[e].items() if "C" in v and "P" in v]
        if pairs:
            best = sorted(pairs)[:3]
            return sum(p[1] for p in best) / len(best)
    return None


class CboeProvider(OptionsProvider):
    name = "cboe"

    def __init__(self, settings: Settings, client: httpx.Client | None = None, today_fn=None, clock=utcnow):
        self.s = settings
        self.clock = clock
        self.today = today_fn or (lambda: to_et(self.clock()).date())
        self.client = client or httpx.Client(timeout=90.0, follow_redirects=True)

    def fetch_chain(self, underlying: str, *, max_dte: int, strike_window: float) -> ChainSnapshot:
        url = f"{self.s.cboe_base_url}/{underlying}.json"
        try:
            r = self.client.get(url, headers=UA)
        except httpx.HTTPError as e:
            raise ProviderError("network", f"Could not reach Cboe: {type(e).__name__}") from None
        if r.status_code == 404:
            raise ProviderError("not_found", f"Cboe has no file for {underlying}. Index options need a leading underscore (_NDX, _SPX).", 404)
        if r.status_code == 429:
            raise ProviderError("rate_limit", "Cboe asked us to slow down. Increase POLL_SECONDS.", 429)
        if r.status_code != 200:
            raise ProviderError("server", f"Cboe returned HTTP {r.status_code}.", r.status_code)
        try:
            j = r.json()
            d = j["data"]
            raw = d["options"]
        except (ValueError, KeyError, TypeError):
            raise ProviderError("schema", "Cboe's response did not have the expected data.options list.", 200) from None
        spot, note = None, None
        for f in SPOT_FIELDS:
            v = _num(d.get(f))
            if v and v > 0:
                spot, note = v, (None if f == "current_price" else f"underlying price taken from the file field '{f}'")
                break
        now = self.clock()
        ts = source_time(j, d, now)
        today = self.today()
        lim = today + timedelta(days=max_dte)
        dated = drop_expired([c for c in (normalize_option(o) for o in raw) if c is not None and today - timedelta(days=1) <= c.expiry <= lim], now)
        if not spot:
            spot = parity_spot(dated)
            note = "the file had no underlying price, so it was estimated from option prices (put-call parity)" if spot else None
        out = [c for c in dated if not spot or abs(c.strike / spot - 1) <= strike_window]
        log.info("cboe %s: %d options in file, %d kept (expiries to %s, strikes within %.0f%%), spot=%s, file time=%s",
                 underlying, len(raw), len(out), lim, strike_window * 100, spot, ts)
        if raw and not out:
            raise ProviderError("schema", f"Cboe's file for {underlying} had {len(raw)} options but none fell inside the filters "
                                          f"(expiry through {lim}, strikes within {strike_window:.0%} of the price). "
                                          "Raise MAX_DTE or STRIKE_WINDOW in .env, or run diagnose.bat.")
        snap = ChainSnapshot(self.name, underlying, now, spot, ts, out, content_hash(out))
        snap.spot_note = note
        return snap
