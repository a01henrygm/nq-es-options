"""Stack map: where do the most DIFFERENT kinds of levels pile up?

Every price level the app makes goes in, each tagged with its family:
  gex       GEX concentrations, GEX and wall zones, 0DTE walls and flip          flip      the gamma flip (overall)
  oi        open interest (all expiries, by expiry, mid-size)                     vol       volume (session, by expiry, mid-size)
  move      expected-move edges and extensions                                    charm / vanna / dex / new   modeled flows and new positions
  ladder    the HOD / LOD ladder steps (open +/- k sd)                            proj      projected HOD / LOD (50% and 80%)
  prior     yesterday's high, low and close                                       session   today's open, high and low so far
  activity  hot spots of volume, open interest and GEX on the activity heatmap     mine      levels you typed in

Stacking: around each level, every family within `tol` of it adds its strongest member's weight once (a family can only count once, so
ten open-interest strikes in a row do not make a stack). The best centre is taken, its members removed, and the search repeats. A stack is
kept only when at least `min_families` different families agree and its score passes `min_score`. Score = sum of the families' weights;
weights are each level's own importance (0 to 1) where the app has one, otherwise a fixed weight per family.

My own rule, not backtested: stacked areas are where more reasons to react line up, not a promise that price will.
"""
from __future__ import annotations

from .importance import FAMILY

DEFAULT_W = {"ladder": 0.5, "proj": 0.6, "prior": 0.8, "session": 0.6, "activity": 0.7, "mine": 0.9, "flip": 1.0}
FAMILY_NAME = {"gex": "GEX", "flip": "Gamma flip", "oi": "Open interest", "vol": "Volume", "move": "Expected move", "charm": "Charm", "vanna": "Vanna",
               "dex": "Dealer delta", "new": "New positions", "ladder": "HOD/LOD ladder", "proj": "Projected HOD/LOD", "prior": "Yesterday",
               "session": "Today's open/high/low", "activity": "Activity hot spot", "mine": "Your level"}
RULE = __doc__.split("\n\n", 1)[1].strip()


def family_of(category):
    if category == "gamma_flip":
        return "flip"
    if category == "custom":
        return "mine"
    return FAMILY.get(category)


def find_stacks(items, spot, tol, min_families=3, min_score=2.2, max_stacks=12):
    """items: [{price, family, label, weight}]. Returns stacks, strongest first: {center, low, high, score, families, members}."""
    pool = [dict(x) for x in items if x.get("price") and x.get("family")]
    out = []
    while pool and len(out) < max_stacks:
        best = None
        for c in pool:
            near = [x for x in pool if abs(x["price"] - c["price"]) <= tol]
            fam = {}
            for x in near:
                if x["weight"] > fam.get(x["family"], (0, None))[0]:
                    fam[x["family"]] = (x["weight"], x)
            score = sum(w for w, _ in fam.values())
            if best is None or score > best[0] or (score == best[0] and abs(c["price"] - spot) < abs(best[1]["price"] - spot)):
                best = (score, c, near, fam)
        score, c, near, fam = best
        if len(fam) < min_families or score < min_score:
            break
        wsum = sum(w for w, _ in fam.values())
        center = sum(w * x["price"] for w, x in fam.values()) / wsum
        out.append({"center": center, "low": min(x["price"] for x in near), "high": max(x["price"] for x in near), "score": round(score, 3),
                    "families": sorted(fam, key=lambda f: -fam[f][0]), "members": sorted(near, key=lambda x: -x["weight"])})
        ids = {id(x) for x in near}
        pool = [x for x in pool if id(x) not in ids]
    return out


def tier(score):
    return "Very stacked" if score >= 4.0 else "Stacked"
