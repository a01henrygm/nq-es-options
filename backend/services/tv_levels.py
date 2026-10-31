"""The paste-in TradingView indicators: Q DATA GEX (gamma levels only), Q DATA Levels (everything else) and Q DATA Key Levels
(the Key levels tab's own levels, 1.28.0).

Pure logic, no web or database code: which section each kind of level belongs to, the white-chart colors, which kinds are key,
the read (what price should do at a level), matching one snapshot's levels to the runs already being tracked, and the levels text.

Times: every start and end time is the OPTIONS DATA time of the snapshot (snap.source_ts), not the time the data arrived (it is
about 15 minutes delayed). They travel in the text as epoch milliseconds, the same clock TradingView's bar times use, so no time
zone parsing is needed on the chart.

The levels text (one record per line, fields split by |):
  Q|2|<ind gex|lv>|<made ET>|<day>|<symbol>|<units>|<data time ms>
  K|<name>|#rrggbb|S|D|O|<width>|<short meaning>|<section>|<key 1/0>       kinds; levels refer to them by order
  L|<price>|<low>|<high>|<kind>|<start ms>|<end ms, 0 = current>|<read H C B ->|<moved from, 0 = none>|<label>|<hover>
  H|<price>|<low>|<high>|<heat 0-100>                                       heatmap rows (Levels only)
  R|<name>|<value>                                                           info box rows
"""
from __future__ import annotations
import re

MAX_CHARS = 30000
TIP_CHARS = 150
HIST_PER_KIND = 4

GEX_SECTIONS = ["Gamma flips", "Walls", "GEX strikes", "GEX zones"]
LV_SECTIONS = ["Open interest", "Volume", "Expected move", "Charm and vanna", "Dealer delta", "New positions", "HOD / LOD",
               "Stack zones", "Game plan", "VIX day", "Quant targets", "Heatmap"]
# Q DATA tab -> section of the Levels indicator. GEX comes from these tabs instead: gex, zerodte, flip.
GEX_TABS = ("gex", "zerodte", "flip")
LV_TABS = {"oi": 0, "volume": 1, "move": 2, "flows": 3, "delta": 4, "preopen": 5, "hodlod": 6, "stackmap": 7, "gameplan": 8, "vix": 9, "quant": 10}
HEAT_SECTION = 11
OFF_BY_DEFAULT = {"lv": [HEAT_SECTION]}
# Q DATA Key Levels (1.28.0): the Key levels tab's own levels, the GEX sections first (drawn like Q DATA GEX), then the rest.
KL_SECTIONS = GEX_SECTIONS + ["Open interest", "Volume", "Expected move", "Charm and vanna", "Dealer delta", "New positions", "Your levels"]


def kl_section(category: str, name: str) -> int:
    """Section of the Key Levels indicator for one Key levels category."""
    c = category or ""
    if c in ("gamma_flip", "gex0_flip"):
        return 0
    if c in ("gex0_call_wall", "gex0_put_wall", "call_wall", "put_wall"):
        return 1
    if c == "gex_concentration":
        return 2
    if c.startswith("gex_"):
        return 3
    if c.startswith("oi") or c.startswith("open_interest"):
        return 4
    if c.startswith("volume"):
        return 5
    if c.startswith("expected_move"):
        return 6
    if c.startswith("charm") or c.startswith("vanna"):
        return 7
    if c.startswith("dex"):
        return 8
    if c.startswith("new_"):
        return 9
    if c == "custom":
        return 10
    return gex_section(name) if "gex" in (name or "").lower() or "wall" in (name or "").lower() or "flip" in (name or "").lower() else 4

# deep, saturated colors that read well on a pure white chart (and still work on dark)
WHITE = [
    ("0dte flip", "#b45309"), ("gamma flip", "#d97706"), ("flip", "#d97706"),
    ("0dte call wall", "#0891b2"), ("0dte put wall", "#db2777"), ("call wall zone", "#10b981"), ("put wall zone", "#ef4444"),
    ("call wall", "#059669"), ("put wall", "#dc2626"),
    ("top - 0dte", "#7c3aed"), ("negative gex", "#7c3aed"), ("top + 0dte", "#2563eb"), ("positive gex", "#2563eb"), ("biggest gex", "#1d4ed8"),
    ("call open interest", "#f97316"), ("put open interest", "#c2410c"), ("open interest midpoints", "#fb923c"), ("open interest", "#ea580c"),
    ("call volume", "#0d9488"), ("put volume", "#e11d48"), ("volume midpoints", "#22c55e"), ("volume", "#16a34a"),
    ("expected move (wider)", "#6366f1"), ("straddle", "#2563eb"), ("2 sd", "#7c3aed"), ("1 sd", "#4f46e5"), ("expected move", "#3b82f6"),
    ("charm: dealers sell", "#e11d48"), ("charm: dealers buy", "#0f766e"), ("vanna positive", "#9333ea"), ("vanna negative", "#ca8a04"),
    ("dealer delta: long", "#0284c7"), ("dealer delta: short", "#be185d"), ("new call", "#65a30d"), ("new put", "#dc2626"),
    ("high of day so far", "#15803d"), ("low of day so far", "#b91c1c"), ("projected hod", "#0e7490"), ("projected lod", "#be123c"),
    ("hod ladder", "#0369a1"), ("lod ladder", "#c2410c"), ("9:30 open", "#334155"),
    ("hold", "#16a34a"), ("chop", "#ca8a04"), ("break", "#dc2626"),
    ("long entries", "#15803d"), ("short entries", "#b91c1c"), ("stops", "#64748b"), ("targets", "#2563eb"), ("stay away", "#ca8a04"),
    ("typical day +/-2", "#9333ea"), ("typical day", "#7c3aed"), ("playbook", "#0f766e"), ("monte carlo high", "#15803d"), ("monte carlo low", "#b91c1c"),
]
KEY_KINDS = ("gamma flip", "0dte flip", "call wall", "put wall", "your levels", "of day so far", "long entries", "short entries", "stacked areas", "projected hod", "projected lod",
             "straddle (nearest expiry)", "1 sd (nearest expiry)")
LIVE_KINDS = ("so far", "projected", "monte carlo", "ladder", "typical day", "9:30 open", "straddle", "1 sd", "2 sd", "playbook", "expected move")
STY = {"solid": "S", "dashed": "D", "dotted": "O"}


def white_color(name: str, fallback: str = "#475569") -> str:
    n = (name or "").lower()
    for k, c in WHITE:
        if k in n:
            return c
    return fallback


def is_key(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in KEY_KINDS) and "zones" not in n and "(80%" not in n


def is_live(name: str) -> bool:
    """Kinds that follow price or the clock (high so far, projections, expected moves): updated in place, no history, no alerts."""
    n = (name or "").lower()
    return any(k in n for k in LIVE_KINDS)


def gex_section(name: str) -> int:
    n = (name or "").lower()
    if "flip" in n:
        return 0
    if "zones" in n:
        return 3
    if "wall" in n:
        return 1
    return 2


def call_category(name: str) -> str:
    n = (name or "").lower()
    if "flip" in n:
        return "gamma_flip"
    if "expected move" in n or "straddle" in n or " sd" in n:
        return "expected_move"
    return "other"


def fixed_read(name: str):
    """A read that comes with the kind itself (stack calls), '-' for kinds that have no read (setups, projections), else None."""
    n = (name or "").lower()
    if "(respect)" in n:
        return "H"
    if "(disrespect)" in n:
        return "B"
    if "(chop)" in n:
        return "C"
    if any(k in n for k in ("entries", "stops", "targets", "stay away", "projected", "monte carlo", "ladder", "typical day", "playbook")):
        return "-"
    return None


READ = {"RESPECT": "H", "CHOP": "C", "DISRESPECT": "B"}


def same_level(a: float, b: float) -> bool:
    """Strike levels (multiples of 5) must match exactly; computed levels (flips, zone centers) may drift 0.03%."""
    if abs(a - round(a / 5) * 5) < 1e-6 and abs(b - round(b / 5) * 5) < 1e-6:
        return abs(a - b) < 0.01
    return abs(a - b) <= 0.0003 * max(abs(a), abs(b), 1.0)


def match(old_runs: list, new_levels: list) -> tuple[list, list, list, list]:
    """Pair one snapshot's levels of one kind with the runs already showing.
    Returns (same [(run, lv)], moved [(run, lv)], new [lv], gone [run]). Live kinds only pair by label (value follows in place)."""
    same, moved, used_r, used_n = [], [], set(), set()
    live = bool(new_levels and is_live(new_levels[0]["kind"])) or bool(old_runs and is_live(old_runs[0]["kind"]))
    for i, lv in enumerate(new_levels):
        for r in old_runs:
            if r["id"] in used_r:
                continue
            if r["label"] == lv["label"] and (live or same_level(r["value"], lv["value"])):
                same.append((r, lv)); used_r.add(r["id"]); used_n.add(i)
                break
    for i, lv in enumerate(new_levels):
        if i in used_n:
            continue
        for r in old_runs:
            if r["id"] not in used_r and same_level(r["value"], lv["value"]):
                same.append((r, lv)); used_r.add(r["id"]); used_n.add(i)
                break
    rest_n = [i for i in range(len(new_levels)) if i not in used_n]
    rest_r = [r for r in old_runs if r["id"] not in used_r]
    for i in sorted(rest_n, key=lambda i: new_levels[i]["value"]):
        if not rest_r:
            break
        lv = new_levels[i]
        cand = [r for r in rest_r if r["label"] == lv["label"]] or rest_r
        r = min(cand, key=lambda r: abs(r["value"] - lv["value"]))
        moved.append((r, lv)); rest_r.remove(r); used_n.add(i)
    new = [new_levels[i] for i in range(len(new_levels)) if i not in used_n]
    return same, moved, new, rest_r


def f(text, n=None) -> str:
    t = re.sub(r"\s+", " ", str(text if text is not None else "").replace("|", "/")).strip()
    t = "".join(ch if ord(ch) < 128 else " " for ch in t)
    return t[:n] if n else t


def build_text(ind: str, runs: list, conv, made: str, day: str, symbol: str, units: str, data_ms: int, rows: list,
               heat: list | None = None, prefs: dict | None = None) -> dict:
    """runs: today's tracked runs of one indicator (current and ended). conv: index price -> chart price."""
    kp = (prefs or {}).get("kinds") or {}
    kinds, kidx, out_lv, hidden = [], {}, [], {}
    cur = [r for r in runs if r["active"]]
    hist = [r for r in runs if not r["active"] and not r["live"]]
    by_kind = {}
    for r in sorted(hist, key=lambda r: r["end_ts_ms"] or 0, reverse=True):
        by_kind.setdefault(r["kind"], []).append(r)
    hist = [r for v in by_kind.values() for r in v[:HIST_PER_KIND]]
    for r in cur + hist:
        p = kp.get(r["kind"]) or {}
        if p.get("on") is False:
            hidden.setdefault(r["kind"], {"name": r["kind"], "color": white_color(r["kind"]), "key": is_key(r["kind"]), "hidden": True})
            continue
        price = conv(r["value"])
        if price is None or price <= 0:
            continue
        if r["kind"] not in kidx:
            kidx[r["kind"]] = len(kinds)
            col = p.get("color") if isinstance(p.get("color"), str) and re.fullmatch(r"#[0-9a-fA-F]{6}", p.get("color") or "") else white_color(r["kind"])
            key = p["key"] if isinstance(p.get("key"), bool) else is_key(r["kind"])
            width = 2 if key else 1
            kinds.append({"name": r["kind"], "color": col.lower(), "style": STY.get(r.get("style") or "solid", "S"), "width": width,
                          "short": r.get("short") or "", "sec": int(r["sec"]), "key": key})
        lo, hi = conv(r["low"]) if r["low"] else None, conv(r["high"]) if r["high"] else None
        band = lo is not None and hi is not None and hi > lo
        prev = conv(r["prev"]) if r.get("prev") else None
        out_lv.append({"price": price, "low": lo if band else 0.0, "high": hi if band else 0.0, "kind": kidx[r["kind"]],
                       "start": int(r["first_ts_ms"]), "end": 0 if r["active"] else int(r["end_ts_ms"] or 0), "read": r.get("read") or "-",
                       "prev": prev or 0.0, "label": r["label"], "tip": r.get("tip") or r["label"], "cur": bool(r["active"])})
    out_lv.sort(key=lambda x: (not x["cur"], -x["price"]))

    def render(levels, tips=True):
        o = [f"Q|2|{ind}|{f(made, 40)}|{f(day, 10)}|{f(symbol, 30)}|{f(units, 110)}|{int(data_ms)}"]
        o += [f"K|{f(k['name'], 48)}|{k['color']}|{k['style']}|{k['width']}|{f(k['short'], 28)}|{k['sec']}|{1 if k['key'] else 0}" for k in kinds]
        o += [f"L|{x['price']:.2f}|{x['low']:.2f}|{x['high']:.2f}|{x['kind']}|{x['start']}|{x['end']}|{x['read']}|{x['prev']:.2f}|{f(x['label'], 36)}|"
              + (f(x["tip"], TIP_CHARS) if tips else "") for x in levels]
        o += [f"H|{h['price']:.2f}|{h['low']:.2f}|{h['high']:.2f}|{int(h['heat'])}" for h in (heat or [])]
        o += [f"R|{f(k, 30)}|{f(v, 60)}" for k, v in rows if v not in (None, "")]
        return "\n".join(o) + "\n"

    text = render(out_lv)
    cut = 0
    if len(text) > MAX_CHARS:
        text = render(out_lv, False)
    while len(text) > MAX_CHARS and out_lv:
        drop = max(1, len(out_lv) // 10)
        keep = sorted(out_lv, key=lambda x: (not x["cur"], not kinds[x["kind"]]["key"]))[:len(out_lv) - drop]
        cut += len(out_lv) - len(keep)
        out_lv = sorted(keep, key=lambda x: (not x["cur"], -x["price"]))
        text = render(out_lv, False)
    return {"text": text, "levels": sum(1 for x in out_lv if x["cur"]), "history": sum(1 for x in out_lv if not x["cur"]),
            "kinds": kinds, "hidden_kinds": list(hidden.values()), "chars": len(text), "cut": cut}
