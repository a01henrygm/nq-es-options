"""Level reaction log: what price did after touching a level? Descriptive statistics only, not a trading edge.

A level counts as touched when price comes within `tol` of it or crosses it between two observations. After each touch we look
at where price was 15 and 30 minutes later. "Held" means price was still on the side it approached from; "broke" means price ended
up on the other side by more than the pin band; anything inside the pin band (price sitting on the level) is "pinned" (1.32.0).
Pinned touches are counted but left out of the held percentage, so a level price sticks to is no longer scored as a failure.
Several kinds at one price touched at one moment are one stack: summarize_stacks scores those events once each.
"""
from __future__ import annotations
from datetime import timedelta


def outcome(move, side, band):
    """'held', 'broke' or 'pinned' for a move from the level, approached from side (+1 above, -1 below)."""
    if move is None:
        return None
    if abs(move) <= band:
        return "pinned"
    return "held" if move * side > 0 else "broke"


def analyze(levels, prices, tol=0.0005, horizons=(15, 30), cooldown_min=10, pin=None):
    """levels: dicts with label, category, value. prices: list of (datetime, price) sorted by time.
    pin: the pin band as a fraction of the level (default: the touch tolerance)."""
    pin = tol if pin is None else pin
    touches = []
    for lv in levels:
        L, last = lv["value"], None
        for i in range(1, len(prices)):
            t1, p1 = prices[i]
            p0 = prices[i - 1][1]
            if not (abs(p1 - L) <= tol * L or (p0 - L) * (p1 - L) < 0):
                continue
            if last is not None and (t1 - last).total_seconds() < cooldown_min * 60:
                continue
            side = 0
            for j in range(i - 1, -1, -1):                      # last observation clearly on one side of the level
                if abs(prices[j][1] - L) > tol * L:
                    side = 1 if prices[j][1] > L else -1
                    break
            if side == 0:
                continue
            last = t1
            row = {"label": lv["label"], "category": lv["category"], "level": L, "time": t1, "approach": "from above" if side > 0 else "from below"}
            window = [p for t, p in prices[i:] if (t - t1).total_seconds() <= max(horizons) * 60]
            row["max_above"] = max(window) - L if window else None
            row["max_below"] = L - min(window) if window else None
            for h in horizons:
                target = t1 + timedelta(minutes=h)
                after = next(((t, p) for t, p in prices[i:] if t >= target and (t - target).total_seconds() <= 600), None)
                mv = None if after is None else after[1] - L
                oc = outcome(mv, side, pin * L)
                row[f"outcome_{h}"] = oc
                row[f"held_{h}"] = None if oc in (None, "pinned") else oc == "held"
                row[f"move_{h}"] = mv
            touches.append(row)
    return touches


def summarize(touches, horizons=(15, 30)):
    out = {}
    for t in touches:
        s = out.setdefault(t["category"], {"category": t["category"], "touches": 0, **{f"n_{h}": 0 for h in horizons}, **{f"held_{h}": 0 for h in horizons},
                                           **{f"pin_{h}": 0 for h in horizons}})
        s["touches"] += 1
        for h in horizons:
            if t.get(f"outcome_{h}") == "pinned":
                s[f"pin_{h}"] += 1
            if t[f"held_{h}"] is not None:
                s[f"n_{h}"] += 1
                s[f"held_{h}"] += 1 if t[f"held_{h}"] else 0
    rows = []
    for s in out.values():
        r = {"category": s["category"], "touches": s["touches"]}
        for h in horizons:
            r[f"measured_{h}"] = s[f"n_{h}"]
            r[f"held_pct_{h}"] = s[f"held_{h}"] / s[f"n_{h}"] if s[f"n_{h}"] else None
            r[f"pinned_{h}"] = s[f"pin_{h}"]
        r["enough_data"] = s["touches"] >= 10
        rows.append(r)
    return sorted(rows, key=lambda r: -r["touches"])


def stacks(touches):
    """Group touches of different kinds at the same price and moment into one event each."""
    ev = {}
    for t in touches:
        k = (str(t["time"]), round(t["level"], 2), t["approach"])
        e = ev.setdefault(k, {"time": t["time"], "level": t["level"], "approach": t["approach"], "kinds": set(), "first": t})
        e["kinds"].add(t["category"])
    return list(ev.values())


def bucket(n):
    return "1 kind" if n <= 1 else "2-3 kinds" if n <= 3 else "4+ kinds"


def summarize_stacks(touches, horizons=(15, 30)):
    """Held rate by how many kinds were stacked at the touched price, each touch event counted once."""
    out = {b: {"stack": b, "events": 0, **{f"n_{h}": 0 for h in horizons}, **{f"held_{h}": 0 for h in horizons}, **{f"pin_{h}": 0 for h in horizons}}
           for b in ("1 kind", "2-3 kinds", "4+ kinds")}
    for e in stacks(touches):
        s = out[bucket(len(e["kinds"]))]
        s["events"] += 1
        for h in horizons:
            oc = e["first"].get(f"outcome_{h}")
            if oc == "pinned":
                s[f"pin_{h}"] += 1
            elif oc is not None:
                s[f"n_{h}"] += 1
                s[f"held_{h}"] += 1 if oc == "held" else 0
    rows = []
    for s in out.values():
        r = {"stack": s["stack"], "events": s["events"]}
        for h in horizons:
            r[f"measured_{h}"] = s[f"n_{h}"]
            r[f"held_pct_{h}"] = s[f"held_{h}"] / s[f"n_{h}"] if s[f"n_{h}"] else None
            r[f"pinned_{h}"] = s[f"pin_{h}"]
        rows.append(r)
    return rows
