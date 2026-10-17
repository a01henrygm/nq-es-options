"""Which levels matter most? A transparent ranking so the dashboard can show a short list instead of every strike.

Importance (0 to 100) of one level = size x type x closeness, then merged into zones:
  size       how big the level is compared with the biggest level of its own kind (open interest, volume, GEX...). The gamma flip and
             levels you typed in count as full size.
  type       gamma flip 1.0, your own levels 1.0, GEX 0.9, open interest 0.85, expected-move edges 0.85, volume 0.7, by-expiry 0.6, mid-size 0.4.
  closeness  levels inside about one expected move of price count fully; the factor fades to 35% at two expected moves away and beyond.
Zones: bands (GEX, open interest and volume zones) that overlap by half or more are merged into one that shows both names, +0.12 for agreeing.
Other levels closer together than 0.10% of price are merged into ONE zone (about 30 points on NDX). A zone scores as its best member plus
0.12 for each extra kind of level that agrees there (confluence, capped at +0.36).

The weights are my own judgement. They decide what is shown FIRST; they are not tested evidence that a level will matter.
"""
from __future__ import annotations
import re
from datetime import datetime

TYPE_FACTOR = {"gamma_flip": 1.0, "custom": 1.0, "gex_call_zone": 0.95, "gex_put_zone": 0.95, "gex_pos_zone": 0.9, "gex_neg_zone": 0.9, "expected_move_ext": 0.7, "oi_call_zone": 0.85, "oi_put_zone": 0.85, "volume_call_zone": 0.7, "volume_put_zone": 0.7, "gex_concentration": 0.9, "open_interest": 0.85, "expected_move": 0.85, "volume": 0.7,
               "oi_by_expiry": 0.6, "volume_by_expiry": 0.6, "oi_mid": 0.4, "volume_mid": 0.4}
RULE = ("Importance = size (versus the biggest level of its kind) x type weight x closeness to price (full inside about one expected move, "
        "fading to 35% beyond two). Levels within 0.10% of price of each other are merged into one zone, which gets +0.12 for each extra "
        "kind of level that agrees there. The weights are my own judgement, not tested evidence.")


def _group(l):
    return (l["category"], re.sub(r"\s#\d+$", "", re.sub(r"\s\d\d/\d\d.*$", "", l["label"])))


def _metric(l):
    i, cat = l.get("inputs") or {}, l["category"]
    if "zone_mag" in i:
        return i["zone_mag"]
    for k in ("net_gex", "call_gex", "put_gex"):
        if k in i:
            return abs(i[k])
    if cat == "volume":
        return (i.get("call") or 0) + (i.get("put") or 0)
    for k in ("call_oi", "put_oi", "call", "put", "total"):
        if k in i and isinstance(i[k], (int, float)):
            return i[k]
    return None


def short_tag(l):
    """One short word or two for the KIND of level, so a zone reads like 'Call OI / Volume / GEX+'."""
    c, lab = l["category"], l["label"].lower()
    if c == "gamma_flip":
        return "Gamma flip"
    if c in ("gex_call_zone", "gex_put_zone", "gex_pos_zone", "gex_neg_zone"):
        return {"gex_call_zone": "Call wall zone", "gex_put_zone": "Put wall zone", "gex_pos_zone": "+GEX zone", "gex_neg_zone": "-GEX zone"}[c]
    if c in ("oi_call_zone", "oi_put_zone", "volume_call_zone", "volume_put_zone"):
        return {"oi_call_zone": "Call OI zone", "oi_put_zone": "Put OI zone", "volume_call_zone": "Call volume zone", "volume_put_zone": "Put volume zone"}[c]
    if c == "gex_concentration":
        return "Call GEX" if "call gex" in lab else "Put GEX" if "put gex" in lab else "GEX+" if "positive" in lab else "GEX-"
    if c in ("open_interest", "oi_by_expiry", "oi_mid"):
        return "Call OI" if "call" in lab else "Put OI"
    if c in ("volume", "volume_by_expiry", "volume_mid"):
        return "Volume"
    if c in ("expected_move", "expected_move_ext"):
        if l.get("low") is not None:
            return "Move zone" if c == "expected_move" else "Extended move zone"
        return "Move edge"
    return l["label"]


def score_levels(levels, spot, scale):
    """Adds importance (0 to 1) to each level. scale = about one expected move in price points."""
    scale = scale or spot * 0.01
    mx = {}
    for l in levels:
        m = _metric(l)
        if m:
            mx[_group(l)] = max(mx.get(_group(l), 0), m)
    em_days = sorted({(l.get("inputs") or {}).get("days") for l in levels if l["category"] in ("expected_move", "expected_move_ext") and (l.get("inputs") or {}).get("days") is not None})
    for l in levels:
        c, lab = l["category"], l["label"]
        if c in ("gamma_flip", "custom"):
            size = 1.0 if c == "gamma_flip" else 0.95
        elif c in ("expected_move", "expected_move_ext"):
            d = (l.get("inputs") or {}).get("days")
            base = 1.0 if c == "expected_move" else 0.5
            if (l.get("inputs") or {}).get("kind") is None:                      # older single-line form
                base = 0.9 if d is None else (1.0 if "1 sigma" in lab else 0.8 if "straddle" in lab else 0.5)
            size = base * (0.6 ** (em_days.index(d) if d in em_days else 0))
        else:
            m, top = _metric(l), mx.get(_group(l))
            size = (m / top) if (m and top) else 0.3
        near = max(0.0, 1 - abs(l["value"] - spot) / (2 * scale))
        l["importance"] = round(size * TYPE_FACTOR.get(c, 0.5) * (0.35 + 0.65 * near), 4)
    return levels


# Per-type counts ("quota"): how many zones of each family to show, so one family (for example GEX) can get more lines than the others.
FAMILY = {"gex_concentration": "gex", "gex_call_zone": "gex", "gex_put_zone": "gex", "gex_pos_zone": "gex", "gex_neg_zone": "gex",
          "open_interest": "oi", "oi_call_zone": "oi", "oi_put_zone": "oi", "oi_by_expiry": "oi", "oi_mid": "oi",
          "volume": "vol", "volume_call_zone": "vol", "volume_put_zone": "vol", "volume_by_expiry": "vol", "volume_mid": "vol",
          "expected_move": "move", "expected_move_ext": "move"}
QUOTA_KEYS = ("gex", "oi", "vol", "move")
QUOTA_RULE = ("Per-type counts: within each family (GEX, open interest, volume, expected move) the highest-scoring zones are kept, up to that family's "
              "count. A zone where several families line up uses ONE slot, from the family that leads it if it has room, otherwise from another "
              "family in it that still has room. The gamma flip and levels you typed in are always shown and use no slot.")


def parse_quota(text):
    """'gex:8,oi:2,vol:1,move:2' -> {'gex': 8, 'oi': 2, 'vol': 1, 'move': 2}. Missing families count 0. Raises ValueError on bad text."""
    q = dict.fromkeys(QUOTA_KEYS, 0)
    for part in filter(None, (p.strip() for p in str(text).split(","))):
        k, _, v = part.partition(":")
        k = k.strip().lower()
        if k not in q or not v.strip().isdigit() or not 0 <= int(v) <= 20:
            raise ValueError(part)
        q[k] = int(v)
    return q


def select_by_quota(zones, quota):
    """Keeps zones per family up to each family's count (see QUOTA_RULE). Returns highest price first."""
    left, out = dict(quota), []
    for z in sorted(zones, key=lambda z: -z["importance"]):
        cats = [z["category"]] + [m["category"] for m in (z.get("inputs") or {}).get("members", [])]
        if any(c in ("gamma_flip", "custom") for c in cats):
            out.append(z)
            continue
        fams = list(dict.fromkeys(FAMILY[c] for c in cats if c in FAMILY))
        f = next((f for f in fams if left.get(f, 0) > 0), None)
        if f:
            left[f] -= 1
            out.append({**z, "slot": f})
    return sorted(out, key=lambda z: -z["value"])


def _overlap(a, b):
    """How much of the narrower band the two bands share (0 to 1)."""
    shared = max(0.0, min(a["high"], b["high"]) - max(a["low"], b["low"]))
    return shared / max(1e-9, min(a["high"] - a["low"], b["high"] - b["low"]))


def make_zones(levels, spot, top_n=10, cluster_pct=0.0010):
    """Merges nearby levels into zones and returns the top_n by score (highest price first). Each zone lists its members.

    GEX wall zones (levels that already have a low and a high) keep their own shape. Plain levels that sit inside one are listed under
    it instead of being drawn again."""
    if not levels:
        return []
    bands = [l for l in levels if l.get("low") is not None]
    plain = [l for l in levels if l.get("low") is None]
    keep = ("gamma_flip", "custom")                                               # the flip and your own levels are never hidden inside a band
    inside = {id(l): ([b for b in bands if b["low"] <= l["value"] <= b["high"]] if l["category"] not in keep else []) for l in plain}
    absorbed = [l for l in plain if inside[id(l)]]
    ordered = sorted((l for l in plain if not inside[id(l)]), key=lambda l: l["value"])
    groups, cur = [], []
    for l in ordered:
        if cur and l["value"] - cur[-1]["value"] > cluster_pct * spot:
            groups.append(cur)
            cur = []
        cur.append(l)
    if cur:
        groups.append(cur)
    zones = []
    for g in groups:
        best = max(g, key=lambda l: l["importance"])
        kinds = {l["category"].replace("_by_expiry", "").replace("_mid", "") for l in g}
        score = min(1.0, best["importance"] + min(0.36, 0.12 * (len(kinds) - 1)))
        tags = []
        for l in sorted(g, key=lambda l: -l["importance"]):
            t = short_tag(l)
            if t not in tags:
                tags.append(t)
        label = " / ".join(tags[:3]) + (f" (+{len(tags) - 3} more)" if len(tags) > 3 else "")
        seen = [m["first_seen"] for m in g if m.get("first_seen")]
        zones.append({**{k: best[k] for k in ("instrument", "source_timestamp", "data_status", "provider", "reliability") if k in best},
                      "category": best["category"], "label": label, "value": best["value"], "importance": round(score, 4), "zone": True,
                      "method": "Zone: " + RULE, "inputs": {"members": [{"label": m["label"], "category": m["category"], "value": m["value"], "importance": m["importance"]} for m in sorted(g, key=lambda l: -l["importance"])]},
                      "first_seen": min(seen, key=lambda s: datetime.fromisoformat(s)) if seen else None})
    for b in bands:
        inner = [{"label": l["label"], "category": l["category"], "value": l["value"], "importance": l["importance"]} for l in absorbed if b in inside[id(l)]]
        zones.append({**{k: b[k] for k in ("instrument", "source_timestamp", "data_status", "provider", "reliability") if k in b},
                      "category": b["category"], "label": b["label"], "value": b["value"], "low": b["low"], "high": b["high"], "importance": b["importance"],
                      "zone": True, "band": True, "method": b["method"],
                      "inputs": {"members": ([{"label": f"{m['side']} strike", "category": b["category"], "value": m["strike"], "importance": b["importance"]} for m in b["inputs"]["members"]]
                                               if b["inputs"].get("members") else [{"label": f"{b['label']} edges", "category": b["category"], "value": b["value"], "importance": b["importance"]}]) + inner,
                                 **{k: v for k, v in b["inputs"].items() if k.endswith("_strikes")}},
                      "first_seen": b.get("first_seen")})
    # bands that overlap by half or more are merged into one that shows both names, with a bonus for the agreement
    merged, tags = [], {}
    for z in sorted((z for z in zones if z.get("band")), key=lambda z: -z["importance"]):
        hit = next((k for k in merged if _overlap(k, z) >= 0.5), None)
        if hit is None:
            merged.append(z)
            tags[id(z)] = [short_tag(z)]
            continue
        hit["importance"] = round(min(1.0, hit["importance"] + 0.12), 4)
        hit["inputs"]["members"] += [{"label": z["label"], "category": z["category"], "value": z["value"], "importance": z["importance"]}]
        if short_tag(z) not in tags[id(hit)]:
            tags[id(hit)].append(short_tag(z))
        hit["label"] = " / ".join(tags[id(hit)][:3]) + (f" (+{len(tags[id(hit)]) - 3} more)" if len(tags[id(hit)]) > 3 else "")
    zones = [z for z in zones if not z.get("band")] + merged
    return sorted(sorted(zones, key=lambda z: -z["importance"])[:top_n], key=lambda z: -z["value"])
