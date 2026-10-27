"""Session replay: rebuild any stored day snapshot by snapshot, so you can watch the GEX profile, the walls and the flip move against price.

Everything comes from what the app already stores while it runs (one GEX profile per new snapshot, about every 2 minutes, and the
level series). Nothing is re-downloaded and nothing is estimated between snapshots: each frame shows the last known value at that time.

Pure functions, no network access.
"""
from __future__ import annotations
from bisect import bisect_right

LINES = ("gamma_flip", "call_wall", "put_wall", "em_low", "em_high", "gamma_at_spot")
FLIP_STEP = 0.0025           # a flip shift is reported once it has moved 0.25% of price (about 70 NDX points) since the last report
TOUCH_TOL = 0.0005            # price within 0.05% of a wall counts as reaching it (same tolerance as the reaction log)


def _asof(series, t):
    """Last value at or before time t (ISO strings compare correctly because they are all UTC)."""
    ts = [r["t"] for r in series]
    i = bisect_right(ts, t)
    return series[i - 1]["value"] if i else None


def _price_asof(price, t):
    """Last stored price at or before t. Prices carry the data time and profiles the time they were calculated (a little later),
    so the snapshot's own price is always found."""
    ts = [p["t"] for p in price]
    i = bisect_right(ts, t)
    return price[i - 1]["price"] if i else None


def _fmt(v, d=0):
    return "-" if v is None else f"{v:,.{d}f}"


def build_frames(profiles: list, price: list, lines: dict, max_frames: int = 400) -> dict:
    """profiles: [{"t", "detail": [[strike, net, call, put], ...]}] in time order. price: [{"t", "price"}]. lines: {name: [{"t", "value"}]}.
    Returns frames (one per stored snapshot) and a timeline of the moments where something meaningful changed."""
    price = sorted(price, key=lambda p: p["t"])
    lines = {k: sorted(lines.get(k) or [], key=lambda r: r["t"]) for k in LINES}
    frames, events = [], []
    prev, flip_ref = None, None             # flip_ref: the flip as last reported, so a slow drift is reported once it adds up
    for i, pr in enumerate(sorted(profiles, key=lambda r: r["t"])):
        t = pr["t"]
        prof = [r for r in (pr.get("detail") or []) if isinstance(r, (list, tuple)) and len(r) >= 4]
        f = {"i": len(frames), "t": t, "price": _price_asof(price, t), "profile": prof,
             **{k: _asof(lines[k], t) for k in LINES}}
        f["net_total"] = sum(r[1] for r in prof) if prof else None
        ev = []
        if prev:
            for k, name in (("call_wall", "Call wall"), ("put_wall", "Put wall")):
                if f[k] is not None and prev[k] is not None and f[k] != prev[k]:
                    ev.append(("wall", f"{name} moved {_fmt(prev[k])} -> {_fmt(f[k])}"))
            if f["gamma_flip"] is not None and flip_ref is not None and f["price"] and abs(f["gamma_flip"] - flip_ref) >= f["price"] * FLIP_STEP:
                ev.append(("flip", f"Gamma flip shifted {_fmt(flip_ref)} -> {_fmt(f['gamma_flip'])}"))
                flip_ref = f["gamma_flip"]
            if f["price"] and prev["price"] and f["gamma_flip"] and prev["gamma_flip"]:
                a, b = prev["price"] - prev["gamma_flip"], f["price"] - f["gamma_flip"]
                if a * b < 0:
                    ev.append(("cross", f"Price crossed {'above' if b > 0 else 'below'} the gamma flip ({_fmt(f['gamma_flip'])}): "
                                        f"{'calmer, positive-gamma side' if b > 0 else 'negative-gamma side, moves can extend'}"))
            for k, name in (("call_wall", "call wall"), ("put_wall", "put wall")):
                lv = f[k]
                if lv and f["price"] and prev["price"]:
                    was, now_ = abs(prev["price"] - lv) / lv <= TOUCH_TOL, abs(f["price"] - lv) / lv <= TOUCH_TOL
                    crossed = (prev["price"] - lv) * (f["price"] - lv) < 0
                    if (now_ and not was) or crossed:
                        ev.append(("touch", f"Price {'crossed' if crossed else 'reached'} the {name} at {_fmt(lv)}"))
            if f["gamma_at_spot"] is not None and prev["gamma_at_spot"] is not None and f["gamma_at_spot"] * prev["gamma_at_spot"] < 0:
                ev.append(("regime", "Dealer gamma at price turned " + ("positive: moves get absorbed" if f["gamma_at_spot"] > 0 else "negative: moves can run")))
            old = {r[0]: r[1] for r in prev["profile"]}
            moves = sorted(((r[0], r[1] - old.get(r[0], 0.0)) for r in prof), key=lambda x: -abs(x[1]))[:3]
            f["biggest_changes"] = [{"strike": k, "change": d} for k, d in moves if d]
        else:
            f["biggest_changes"] = []
        if flip_ref is None:
            flip_ref = f["gamma_flip"]
        f["events"] = [{"kind": k, "text": s} for k, s in ev]
        for k, s in ev:
            events.append({"i": f["i"], "t": t, "kind": k, "text": s})
        frames.append(f)
        prev = f
    if len(frames) > max_frames:                          # thin evenly, but never drop a frame where something happened
        keep = {0, len(frames) - 1} | {e["i"] for e in events}
        step = len(frames) / max_frames
        keep |= {int(j * step) for j in range(max_frames)}
        frames = [f for f in frames if f["i"] in keep]
        remap = {f["i"]: n for n, f in enumerate(frames)}
        for n, f in enumerate(frames):
            f["i"] = n
        events = [dict(e, i=remap[e["i"]]) for e in events if e["i"] in remap]
    strikes = sorted({r[0] for f in frames for r in f["profile"]})
    return {"frames": frames, "events": events, "strikes": strikes, "price": price,
            "range": {"price_low": min((p["price"] for p in price), default=None), "price_high": max((p["price"] for p in price), default=None)}}
