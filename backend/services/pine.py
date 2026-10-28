"""The Key levels tab's TradingView indicator ("Q DATA Key Levels").

Built with the same engine as the tab indicators (services/tab_pine.py), so it has the same settings: a View switch (Clean by
default: shaded stack zones where levels pile up, and only key levels keep their line inside them), a row per kind of level
(show, color, style, width, Key), label and table options, and a Chart background setting that keeps colors readable on white.

Every kind of level is always listed, in a fixed order, even when today has none of it: TradingView remembers settings by their
position, so the rows never move and the changes you make in TradingView survive re-pasting a fresh copy each session.
Written as conservative Pine v6; it has not been compiled by TradingView from here.
"""
from __future__ import annotations
import re
from datetime import datetime

from .level_kinds import CAT, help_for
from .tab_pine import VIEWS, build_tab_pine

# Kinds that keep their line in the Clean and Minimal views (they are the levels people trade off directly).
KEY_CATS = ("gamma_flip", "gex0_flip", "gex0_call_wall", "gex0_put_wall", "gex_call_zone", "gex_put_zone", "custom")
# Only GEX levels and the call / put walls are drawn as shaded bands; every other kind stays a single line.
BAND_CATS = ("gex_call_zone", "gex_put_zone", "gex_pos_zone", "gex_neg_zone")
WIDE = ("gamma_flip", "gex0_call_wall", "gex0_put_wall")
ORDER = list(CAT)                                   # fixed order of the kinds = fixed order of the settings rows


def _s(text) -> str:
    """Strip characters that would break a Pine string or comment line."""
    return re.sub(r"\s+", " ", re.sub(r'["\\]', "", str(text))).strip()


def kind_groups() -> list:
    out = []
    for cat in ORDER:
        name, color, style = CAT[cat]
        short, long_ = help_for(name)
        out.append({"name": name, "color": color, "style": style, "width": 2 if cat in WIDE else 1, "short": short, "help": long_,
                    "key": cat in KEY_CATS})
    return out


def build_pine(levels: list, source: str, units: str, start_et: datetime | None = None, prefs: dict | None = None) -> str:
    """levels: dicts with label, category, price, and optional low / high (zone edges), tip, importance.
    start_et: when the levels were made (shown in the script header)."""
    lv = []
    for x in levels:
        if x.get("price") is None or x["price"] <= 0:
            continue
        cat = x.get("category")
        gi = ORDER.index(cat) if cat in CAT else ORDER.index("custom")
        band = cat in BAND_CATS and x.get("low") is not None and x.get("high") is not None and x["high"] > x["low"]
        tip = x.get("tip") or x.get("label") or ""
        if x.get("importance") is not None:
            tip = f"{tip} Importance {float(x['importance']):.2f}."
        lv.append({"price": float(x["price"]), "group": gi, "label": x.get("label") or CAT.get(cat, ("Level",))[0],
                   "low": float(x["low"]) if band else None, "high": float(x["high"]) if band else None, "tip": tip})
    prices = sorted(x["price"] for x in lv)
    ref = prices[len(prices) // 2] if prices else 0.0
    zone = max(0.25, round(ref * 0.0004 * 4) / 4) if ref else 10.0     # join levels within ~0.04% of price: NQ ~10 points, ES ~2.5
    p = dict(prefs or {})
    p["set"] = {"viewMode": VIEWS[1], **((prefs or {}).get("set") or {})}
    made = start_et.strftime("%Y-%m-%d %H:%M ET") if start_et else ""
    table = [("Levels", str(len(lv))), ("Made", made or "-")]
    about = ("Today's key options levels. Clean view: shaded stack zones show where several kinds of level pile up (hover the zone "
             "label for what is inside); flips, walls and your own levels always keep their line.")
    return build_tab_pine("Q DATA Key Levels", "QD Levels", kind_groups(), lv, table, _s(source), _s(units), made, None, 5.0, about, zone,
                          p, "levels")
