"""Mega-cap earnings in NQ points: when the biggest Nasdaq-100 companies report, how far their options say the stock will move,
and what that one stock's move alone does to NQ.

Sources (free, checked against the live endpoints, Oct 2026):
  members + market caps   https://api.nasdaq.com/api/quote/list-type/nasdaq100
  next report date        https://api.nasdaq.com/api/analyst/<SYM>/earnings-date      ("Earnings announcement* for NVDA: Nov 18, 2026")
  before/after the bell   https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD ("time-after-hours" / "time-pre-market")
  option chain            https://cdn.cboe.com/api/global/delayed_quotes/options/<SYM>.json

WEIGHTS. The Nasdaq-100 is a MODIFIED market-cap index: at each rebalance, if the companies above 4.5% together pass 48% of the index,
they are scaled down to 40%, and no company may pass 24% (capped to 20%). Raw market-cap shares would overstate the giants, so the same
rule is applied here. The result is an approximation of the official weights (the official ones use the index's own share counts and
change only at rebalances); you can type your own weights in place of any of them.

IMPLIED MOVE. The reaction day is the report day for a before-the-open report and the next trading day for an after-the-close report
(or when the time is unknown, since the next day's expiry covers both). From the first expiry on or after the reaction day:
  straddle move    = (ATM call mid + ATM put mid) / stock price           the market's quoted "implied move"
  event-only move  = the part of that expiry's variance not explained by an ordinary day, using the IV of the expiry before the report
                     (or after it) as the ordinary level:  e^2 = iv1^2 T1 - iv_base^2 (T1 - 1/365.25);  expected size = 0.8 x e
NQ POINTS = index weight x stock move x NQ price. That is the mechanical effect of that one stock; sympathy moves in related names
(a chip report moving every chip stock) come on top and are not counted.

Pure functions, no network access.
"""
from __future__ import annotations
import math
import re
from datetime import date, datetime, timedelta

from . import analytics as an
from . import market

CHAIN_WINDOW_DAYS = 21                 # option chains are downloaded for companies reporting within this many days
CLASS_SHARES = {"GOOG": "GOOGL"}           # share classes that report together; weights are added to the main class
SINGLE_CAP, SINGLE_TO = 0.24, 0.20
BIG, AGG_CAP, AGG_TO = 0.045, 0.48, 0.40


def _money(v):
    if v is None:
        return None
    s = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def ndx_weights(rows: list) -> dict:
    """Nasdaq list rows -> {symbol: {"weight", "raw_weight", "name", "price", "market_cap"}} with the modified-cap rule applied."""
    caps = {}
    info = {}
    for r in rows or []:
        sym = str(r.get("symbol", "")).strip().upper()
        cap = _money(r.get("marketCap"))
        if not sym or not cap or cap <= 0:
            continue
        caps[sym] = cap
        info[sym] = {"name": re.sub(r"\s+(Common Stock|Class [A-Z].*|Inc\..*|Corporation.*)$", "", str(r.get("companyName", ""))).strip() or sym,
                     "price": _money(r.get("lastSalePrice")), "market_cap": cap}
    tot = sum(caps.values())
    if not tot:
        return {}
    raw = {s: c / tot for s, c in caps.items()}
    w = dict(raw)
    for _ in range(10):                                   # the rule is applied until nothing is over a limit
        changed = False
        over = {s for s, x in w.items() if x > SINGLE_CAP}
        if over:
            free = sum(x for s, x in w.items() if s not in over)
            for s in over:
                w[s] = SINGLE_TO
            k = (1 - SINGLE_TO * len(over)) / free
            for s in w:
                if s not in over:
                    w[s] *= k
            changed = True
        big = {s for s, x in w.items() if x > BIG}
        agg = sum(w[s] for s in big)
        if agg > AGG_CAP + 1e-9:
            k_big, rest = AGG_TO / agg, sum(x for s, x in w.items() if s not in big)
            k_rest = (1 - AGG_TO) / rest
            for s in w:
                w[s] *= k_big if s in big else k_rest
            changed = True
        if not changed:
            break
    out = {}
    for s, x in w.items():
        main = CLASS_SHARES.get(s, s)
        o = out.setdefault(main, {"weight": 0.0, "raw_weight": 0.0, **info.get(main, info[s])})
        o["weight"] += x
        o["raw_weight"] += raw[s]
    return out


def parse_report_date(j: dict) -> dict | None:
    """Nasdaq 'earnings-date' JSON -> {"date", "estimated"}. 'estimated' is True when Nasdaq says the date comes from an algorithm."""
    d = (j or {}).get("data") or {}
    txt = " ".join(str(d.get(k) or "") for k in ("announcement", "reportText"))
    m = re.search(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})", str(d.get("announcement") or "")) or re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", txt)
    if not m:
        return None
    try:
        if m.group(1).isalpha():
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
        else:
            dt = date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    est = bool(re.search(r"estimat|algorithm", txt, re.I))
    return {"date": dt, "estimated": est}


def parse_calendar(j: dict) -> dict:
    """Nasdaq calendar JSON for one day -> {symbol: "before_open" | "after_close" | "unknown"}."""
    rows = (((j or {}).get("data") or {}).get("rows")) or []
    m = {"time-pre-market": "before_open", "time-after-hours": "after_close"}
    return {str(r.get("symbol", "")).upper(): m.get(str(r.get("time", "")), "unknown") for r in rows if r.get("symbol")}


def next_trading_day(d: date) -> date:
    d += timedelta(days=1)
    while not market.is_trading_day(d):
        d += timedelta(days=1)
    return d


def reaction_day(report: date, timing: str) -> date:
    """The first regular session that trades on the news."""
    if timing == "before_open" and market.is_trading_day(report):
        return report                                  # reported before the bell: that same session trades it
    return next_trading_day(report)                    # after the close, unknown time, or a non-trading day: the next session


def implied_move(contracts, spot, react: date, now: datetime) -> dict:
    """Straddle and event-only move for the first expiry that covers the reaction day (see the module notes)."""
    exps = sorted({c.expiry for c in contracts if an.year_fraction(c.expiry, now) > 0})
    after = [e for e in exps if e >= react]
    if not spot or not after:
        return {"available": False, "reason": "No listed expiry covers the reaction day yet."}
    e1 = after[0]
    em = an.expected_move(contracts, spot, now, e1.isoformat())
    st = em.get("straddle")
    a1 = an.atm_iv(contracts, spot, e1)
    if not st and not a1:
        return {"available": False, "reason": f"No usable at-the-money prices for the {e1} expiry."}
    before = [e for e in exps if e < react and an.year_fraction(e, now) * 365.25 >= 0.5]
    base_e = before[-1] if before else (after[1] if len(after) > 1 else None)
    a0 = an.atm_iv(contracts, spot, base_e) if base_e else None
    T1 = an.year_fraction(e1, now)
    event = None
    if a1 and a0 and T1 > 0:
        var = a1["iv"] ** 2 * T1 - a0["iv"] ** 2 * max(T1 - 1 / 365.25, 0)
        if var > 0:
            event = math.sqrt(var)
    straddle_pct = st["price"] / spot if st else None
    return {"available": True, "expiry": e1.isoformat(), "days_to_expiry": T1 * 365.25,
            "straddle_pct": straddle_pct, "straddle_price": st and st["price"], "atm_strike": st and st.get("strike"),
            "event_sd_pct": event, "event_expected_pct": event * math.sqrt(2 / math.pi) if event else None,
            "iv_event_expiry": a1 and a1["iv"], "iv_base": a0 and a0["iv"], "base_expiry": base_e and base_e.isoformat(),
            "headline_pct": straddle_pct if straddle_pct else (event * math.sqrt(2 / math.pi) if event else None)}


def build_table(names: list, weights: dict, reports: dict, timings: dict, moves: dict, nq_price: float | None,
                today: date, horizon_days: int = 45, overrides: dict | None = None) -> dict:
    """names: symbols to show (biggest first). reports: {sym: parse_report_date()}; timings: {sym: timing}; moves: {sym: implied_move()}.
    nq_price: NQ futures price (or NDX when no futures price is known). overrides: {sym: weight as a fraction} typed by you."""
    overrides = overrides or {}
    rows = []
    for s in names:
        w = weights.get(s) or {}
        wt = overrides.get(s, w.get("weight"))
        rep = reports.get(s)
        tm = timings.get(s, "unknown")
        days = (rep["date"] - today).days if rep else None
        mv = moves.get(s) or {"available": False, "reason": f"Option prices are checked from {CHAIN_WINDOW_DAYS} days before the report."
                              if days is not None and days > CHAIN_WINDOW_DAYS else "Option prices not downloaded yet."}
        pct = mv.get("headline_pct") if mv.get("available") else None
        nq = wt * pct * nq_price if wt and pct and nq_price else None
        ev = mv.get("event_expected_pct") if mv.get("available") else None
        rows.append({"symbol": s, "name": w.get("name", s), "weight": wt, "weight_source": "yours" if s in overrides else "approx. index rule",
                     "raw_weight": w.get("raw_weight"), "price": w.get("price"),
                     "report_date": rep and rep["date"].isoformat(), "estimated": rep and rep["estimated"], "days_away": days,
                     "timing": tm, "reaction_day": rep and reaction_day(rep["date"], tm).isoformat(),
                     "move": mv, "move_pct": pct, "nq_points": nq, "nq_points_event": (wt * ev * nq_price) if wt and ev and nq_price else None,
                     "in_window": days is not None and 0 <= days <= horizon_days})
    upcoming = sorted([r for r in rows if r["in_window"]], key=lambda r: (r["report_date"], -(r["weight"] or 0)))
    later = [r for r in rows if not r["in_window"]]
    # nights with more than one report: the effects add up (they are treated as independent, so they add in quadrature)
    by_day = {}
    for r in upcoming:
        if r["nq_points"]:
            by_day.setdefault(r["reaction_day"], []).append(r)
    clusters = [{"reaction_day": d, "symbols": [r["symbol"] for r in rs], "weight": sum(r["weight"] or 0 for r in rs),
                 "nq_points": math.sqrt(sum(r["nq_points"] ** 2 for r in rs)), "nq_points_if_same_way": sum(r["nq_points"] for r in rs)}
                for d, rs in sorted(by_day.items()) if len(rs) > 1]
    total_w = sum(r["weight"] or 0 for r in upcoming)
    return {"upcoming": upcoming, "later": later, "clusters": clusters, "nq_price": nq_price, "weight_reporting": total_w,
            "note": "NQ points are the mechanical effect of that one stock moving by its implied move (index weight x move x NQ). "
                    "Sympathy moves in related stocks are not included, so real index moves on big reports are often larger. "
                    "Weights apply the Nasdaq-100 capping rule to market caps and are approximate; type your own on this tab to replace any of them."}
