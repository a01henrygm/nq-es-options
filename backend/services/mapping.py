"""ETF / index option levels -> futures price estimates.

QQQ and SPY are ETFs; NQ and ES are futures. Their prices are related but NOT interchangeable, so a level is
converted using a contemporaneous pair of prices and the result is always labeled an ESTIMATE.

Methods
  ratio   mapped = level x (futures_price / base_price)          scale-free; the natural choice for ETFs
  basis   mapped = level + (futures_price - base_price)          valid only when both are on the same scale
                                                                  (index like NDX/SPX vs the future)
Neither is exact: the relationship drifts with time to expiry, dividends, financing, and market conditions.
When enough paired observations are stored, evaluate_methods() measures how well each method predicted the next
futures price, so you can pick by measured error instead of assumption.
"""
from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..timeutil import iso

FUTURES_FOR = {"QQQ": "NQ", "SPY": "ES", "I:NDX": "NQ", "I:SPX": "ES", "NDX": "NQ", "SPX": "ES", "_NDX": "NQ", "_SPX": "ES"}
INDEX_GROUP = {"_NDX": "Nasdaq 100", "NDX": "Nasdaq 100", "I:NDX": "Nasdaq 100", "QQQ": "Nasdaq 100", "QQQM": "Nasdaq 100",
               "_SPX": "S&P 500", "SPX": "S&P 500", "I:SPX": "S&P 500", "SPY": "S&P 500", "VOO": "S&P 500",
               "_RUT": "Russell 2000", "RUT": "Russell 2000", "IWM": "Russell 2000", "_DJX": "Dow", "DJX": "Dow", "DIA": "Dow"}
SAME_SCALE = {"I:NDX", "I:SPX", "NDX", "SPX", "_NDX", "_SPX"}
MONTH_CODES = {"F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6, "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12}


@dataclass
class PricePoint:
    symbol: str
    price: float | None
    ts: datetime | None
    source: str = ""
    contract: str | None = None
    manual: bool = False


def _third_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(4 - d.weekday()) % 7)
    return d + timedelta(weeks=2)


def contract_expiry(code: str, today: date | None = None) -> date | None:
    """Expiry (third Friday) of a futures contract code like NQZ6, NQZ26, MNQH27. None if unreadable."""
    today = today or date.today()
    code = (code or "").upper().strip()
    for root in ("MNQ", "MES", "NQ", "ES"):
        if code.startswith(root):
            rest = code[len(root):]
            break
    else:
        return None
    if len(rest) < 2 or rest[0] not in MONTH_CODES or not rest[1:].isdigit():
        return None
    yr = int(rest[1:])
    if yr < 10:
        yr = 2020 + yr
        if yr < today.year - 1:
            yr += 10
    elif yr < 100:
        yr += 2000
    return _third_friday(yr, MONTH_CODES[rest[0]])


def roll_status(code: str, today: date | None = None, warn_days: int = 8) -> dict:
    today = today or date.today()
    exp = contract_expiry(code, today)
    if exp is None:
        return {"contract": code, "expiry": None, "status": "unknown", "note": "Could not read the contract code."}
    days = (exp - today).days
    status = "expired" if days < 0 else "roll_soon" if days <= warn_days else "ok"
    note = {"expired": "This contract has expired. Select the next contract.",
            "roll_soon": f"Expires in {days} days. Volume usually rolls to the next contract about a week earlier.",
            "ok": ""}[status]
    return {"contract": code, "expiry": exp.isoformat(), "days_to_expiry": days, "status": status, "note": note}


def map_level(level: float, underlying: str, base: PricePoint, fut: PricePoint, now: datetime, method: str = "auto",
              max_age_s: float = 1200, max_skew_s: float = 180, prefer: str | None = None) -> dict:
    out = {"original_level": level, "original_units": underlying, "mapped": None, "method": None, "status": "ok",
           "base_price": base.price, "base_timestamp": iso(base.ts), "futures_price": fut.price,
           "futures_timestamp": iso(fut.ts), "futures_contract": fut.contract, "futures_price_manual": fut.manual,
           "calculated_at": iso(now), "warnings": []}
    w = out["warnings"]
    if not base.price or not fut.price:
        out["status"] = "unavailable"
        w.append("Missing " + ("underlying" if not base.price else "futures") + " price; no level was produced.")
        return out
    m = method
    if m == "auto":
        m = prefer or ("basis" if underlying in SAME_SCALE else "ratio")
    if m == "basis" and underlying not in SAME_SCALE:
        out["status"] = "invalid"
        w.append("Basis adjustment is not valid between an ETF and a futures price (different scale). Use ratio.")
        return out
    out["method"] = m
    out["mapped"] = level * fut.price / base.price if m == "ratio" else level + (fut.price - base.price)
    for name, p in (("underlying", base), ("futures", fut)):
        if p.ts is None:
            out["status"] = "degraded"
            w.append(f"The {name} price has no timestamp, so its age is unknown.")
        elif (now - p.ts).total_seconds() > max_age_s:
            out["status"] = "stale"
            w.append(f"The {name} price is {int((now - p.ts).total_seconds() // 60)} minutes old.")
    if base.ts and fut.ts and abs((base.ts - fut.ts).total_seconds()) > max_skew_s:
        out["status"] = "asynchronous" if out["status"] == "ok" else out["status"]
        w.append(f"The two prices are {int(abs((base.ts - fut.ts).total_seconds()))} seconds apart, so the relationship may be off by "
                 "however far the market moved in between.")
    if fut.manual:
        w.append("The futures price was typed in by hand, not read from a data feed.")
    return out


def map_with_typed_basis(level: float, underlying: str, spot: float | None, basis: float, entered_at: datetime | None, now: datetime,
                         max_age_s: float = 6 * 3600) -> dict:
    """level + a basis you typed in (futures minus index at one moment). Only valid for index options (NDX -> NQ, SPX -> ES)."""
    out = {"original_level": level, "original_units": underlying, "mapped": None, "method": "typed_basis", "status": "ok",
           "base_price": spot, "futures_price": None, "typed_basis": basis, "basis_entered_at": iso(entered_at),
           "calculated_at": iso(now), "warnings": []}
    if underlying not in SAME_SCALE:
        out["status"] = "invalid"
        out["warnings"].append("A typed basis only works for index options (_NDX, _SPX). For ETFs use a futures price and the ratio method.")
        return out
    out["mapped"] = level + basis
    out["warnings"].append(f"Uses a basis of {basis:+.2f} points that you typed in. The basis drifts by a few points over a session, so retype it now and then.")
    if entered_at is None or (now - entered_at).total_seconds() > max_age_s:
        out["status"] = "stale"
        out["warnings"].append("The typed basis is more than 6 hours old.")
    return out


def pair_observations(base_hist: list, fut_hist: list, max_skew_s: float = 180) -> list:
    """Pair stored base and futures prices whose timestamps are close. Rows are dicts from the prices table."""
    from ..timeutil import parse_ts
    pairs = []
    futs = [(parse_ts(f["source_ts"] or f["retrieved_at"]), f["price"]) for f in fut_hist]
    for b in base_hist:
        tb = parse_ts(b["source_ts"] or b["retrieved_at"])
        if tb is None:
            continue
        best = min(((abs((tf - tb).total_seconds()), pf) for tf, pf in futs if tf), default=None)
        if best and best[0] <= max_skew_s:
            pairs.append((tb, b["price"], best[1]))
    return sorted(pairs)


def evaluate_methods(pairs: list) -> dict:
    """Walk-forward test: use the relationship at observation i-1 to predict futures at i; report errors."""
    if len(pairs) < 11:
        return {"available": False, "n": len(pairs), "note": "Need at least 11 synchronized observations to measure mapping error."}
    res = {"ratio": [], "basis": []}
    for (t0, b0, f0), (t1, b1, f1) in zip(pairs, pairs[1:]):
        res["ratio"].append(f0 / b0 * b1 - f1)
        res["basis"].append(b1 + (f0 - b0) - f1)
    out = {"available": True, "n": len(pairs) - 1}
    for k, errs in res.items():
        out[k] = {"mae": sum(abs(e) for e in errs) / len(errs), "bias": sum(errs) / len(errs)}
    out["best"] = min(("ratio", "basis"), key=lambda k: out[k]["mae"])
    return out


def implied_forward_ratio(contracts, spot, now, fut_expiry, near=3, min_days=3.0):
    """Futures fair value / index, from the option chain itself (put-call parity), for index options (NDX -> NQ, SPX -> ES).

    For each expiry: forward = strike + call mid - put mid at the strikes nearest price (median of a few). The carry
    (financing minus dividends) is ln(forward / spot) / time. It is taken from the longest expiry at least `min_days` out and
    extended to the futures contract's own expiry: ratio = exp(carry x time to the futures expiry). An ESTIMATE of fair value;
    the traded futures price can sit a few points away from it. Returns {ratio, carry, from_expiry, futures_expiry} or None."""
    from statistics import median
    from .analytics import year_fraction
    if not spot or not fut_expiry:
        return None
    by = {}
    for c in contracts:
        if c.bid and c.ask and c.ask >= c.bid > 0:
            by.setdefault(c.expiry, {}).setdefault(c.strike, {})[c.right] = (c.bid + c.ask) / 2
    best = None
    for e, rows in by.items():
        T = year_fraction(e, now)
        if T * 365.25 < min_days:
            continue
        pairs = sorted((k for k, v in rows.items() if "C" in v and "P" in v), key=lambda k: abs(k - spot))[:near]
        if len(pairs) < 2:
            continue
        fwd = median(k + rows[k]["C"] - rows[k]["P"] for k in pairs)
        if fwd <= 0 or abs(fwd / spot - 1) > 0.05:
            continue
        if best is None or T > best[1]:
            best = (fwd, T, e)
    if best is None:
        return None
    carry = math.log(best[0] / spot) / best[1]
    if not -0.05 <= carry <= 0.15:                       # outside any sensible financing-minus-dividend rate: the quotes are off
        return None
    Tf = max(0.0, (fut_expiry - now.date()).days / 365.25)
    return {"ratio": math.exp(carry * Tf), "carry": carry, "from_expiry": best[2].isoformat(), "futures_expiry": fut_expiry.isoformat()}
