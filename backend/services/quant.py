"""Quant lab: the gamma-regime take-profit playbook, a mean-reversion test, a Monte Carlo of targets and stops, an ES/NQ
principal-component split, and the projected high and low of the day.

Everything here is pure Python (no numpy) so the desktop build stays small. None of it is backtested; each result says what
it assumed. Prices are in index points unless a caller maps them to futures.

Gamma playbook
  Short gamma (dealer gamma at price below zero): dealers hedge WITH the move, so ranges expand and trend. Plan for one trade
  and push the target out (1 to 2 expected moves from the open). Long gamma (above zero): dealers hedge AGAINST the move, so
  price rotates. Trade failed auctions at the range edges (the 0DTE walls) and keep targets small (1 to 3 R). Within a quarter
  of a percent of the 0DTE flip the regime can switch with a small move, so neither playbook is assumed.

Mean reversion (the test from 'Quant finance from scratch', part 23)
  Regress each step's change on the previous step's distance from the average: v = a + b*u. A negative slope b means a pull
  back to the average. Half life = -ln 2 / ln(1 + b) steps. The t statistic must be below -2.9 (the Dickey-Fuller 5% value):
  at -2 about a third of pure random walks already look like a pull.

Monte Carlo
  Thousands of paths from the current price to the 16:00 ET close, one standard deviation equal to the market's own remaining
  expected move. In a long-gamma session with a significant pull, paths are pulled back toward the session average at the
  measured half life (an Ornstein-Uhlenbeck path); otherwise they are a plain random walk. For each target (in R, a multiple of
  the stop distance) it counts how often the target is touched before the stop and before the close.

Principal components (ES/NQ)
  The 2 x 2 covariance of NDX and SPX returns has two eigenvectors. The first (both moving together) is the market factor;
  its eigenvalue share says how much of the movement is shared. What is left of NQ after the market factor (the residual
  against SPX) shows whether NQ is running ahead of or behind its usual relationship with ES.

Projected high and low of the day
  Ladder: the 9:30 open plus and minus k standard deviations of the day, from the expected move priced at the open. Levels are
  static once the open is known. The chance of each level being touched uses the running-maximum rule for a random walk:
  P(max reaches d) = 2 * (1 - N(d / sigma)). The live chance re-runs it from the current price with the remaining expected move;
  a level the day has already traded through is 100%.
"""
from __future__ import annotations
import math
import random
from statistics import NormalDist

_N = NormalDist()
STRADDLE_TO_SIGMA = math.sqrt(math.pi / 2)        # an ATM straddle is about 0.798 standard deviations of the move
T_LIMIT = -2.9
LADDER = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5)
DEFAULT_RS = (1, 2, 3, 5, 8, 12)
TRANSITION_PCT = 0.0025


def Phi(x):
    return _N.cdf(x)


def sigma_from_move(points, method):
    """One standard deviation in points from the stored day move (a straddle price is scaled up, an IV move is already 1 sd)."""
    if points is None:
        return None
    return points * STRADDLE_TO_SIGMA if "straddle" in (method or "") else points


def touch_prob(dist, sigma):
    """Chance a driftless random walk with this standard deviation touches a level `dist` away (running-maximum rule)."""
    if sigma is None or sigma <= 0:
        return None
    if dist <= 0:
        return 1.0
    return min(1.0, 2 * (1 - Phi(dist / sigma)))


# ---- gamma playbook ---------------------------------------------------------------------------------------------------
PLAYBOOK = {
    "short": {"title": "Short gamma: the trend day", "tagline": "Dealers amplify. Trade the expansion.", "color": "#e5534b",
              "rules": [["Dealers feed the move", "If price goes up, dealers buy as it goes up; if it goes down they sell. They add to the move instead of fading it."],
                        ["Expect a volatile, trendy session", "Plan for expansion, not rotation. Ranges can run past the expected move."],
                        ["Aim higher, take fewer trades", "One good trade can carry the day. Push the target out toward 1 to 2 expected moves from the open and trail it."],
                        ["Scalpers sit it out", "If you take 1 or 2 R or trade rotations, this is not your regime."]],
              "r_range": "3 R and more", "trades": "One, maybe two"},
    "long": {"title": "Long gamma: the range day", "tagline": "Dealers suppress. Trade the range.", "color": "#3fb96a",
             "rules": [["Dealers suppress the move", "Dealers hedge against the move to rebalance, so moves get absorbed and price mean-reverts."],
                       ["Failed auctions fit here", "When price pushes out of the range extreme and fails back in, that is the trade."],
                       ["Keep the targets small", "1, 2 or 3 R at most. A big target asks for a move the dealers are hedging against."],
                       ["Stop hunting high R", "Once a session flips to long gamma after a big expansion, high risk-to-reward setups are rare. It is fine to be done."]],
             "r_range": "1 to 3 R", "trades": "Several small rotations"},
    "transition": {"title": "Transition: at the 0DTE flip", "tagline": "Wait for price to leave the flip.", "color": "#e6b422",
                   "rules": [["The regime can switch on a small move", "Price is within a quarter of a percent of the 0DTE gamma flip."],
                             ["Do not assume either playbook", "Size down or wait until price is clearly on one side."],
                             ["Above or below decides it", "Breaking away on the short-gamma side opens the trend playbook; holding on the long-gamma side keeps the range one."],
                             ["Targets", "Use the nearer range edge until the regime settles."]],
                   "r_range": "1 to 2 R until it settles", "trades": "Wait"},
    "unknown": {"title": "Regime unknown", "tagline": "No 0DTE gamma reading.", "color": "#8a8f98",
                "rules": [["No reading", "The 0DTE gamma at price could not be modeled from the current data."]], "r_range": "-", "trades": "-"},
}


def regime_flips(series, hold=2):
    """series: [{t, value}] of dealer gamma at price. Each change of sign that then holds for `hold` readings in a row
    (the latest reading counts on its own), so gamma hovering around zero does not show as a string of flips."""
    pts = [("long" if r["value"] >= 0 else "short", r["t"]) for r in series if r.get("value") is not None]
    out, cur = [], pts[0][0] if pts else None
    for i in range(1, len(pts)):
        s = pts[i][0]
        if s != cur:
            run = pts[i:i + hold]
            if all(x[0] == s for x in run) and (len(run) == hold or i + len(run) == len(pts)):
                out.append({"t": pts[i][1], "from": cur, "to": s})
                cur = s
    return out


def gamma_playbook(z, spot, open_px=None, sigma_open=None, gamma_series=None, sigma_rem=None):
    """z: intraday.zero_dte() result. Returns the regime, its playbook and target prices."""
    g = z.get("exposure_at_spot") if z and z.get("available") else None
    flip = z.get("flip") if z and z.get("available") else None
    if g is None:
        state = "unknown"
    elif flip is not None and abs(spot - flip) / spot < TRANSITION_PCT:
        state = "transition"
    else:
        state = "long" if g >= 0 else "short"
    pb = PLAYBOOK[state]
    out = {"state": state, **pb, "gamma_at_spot": g, "flip": flip, "call_wall": z.get("call_wall") if z else None,
           "put_wall": z.get("put_wall") if z else None, "flips": regime_flips(gamma_series or []), "targets": [], "notes": []}
    if flip is not None:
        out["notes"].append(f"0DTE flip {flip:,.0f} is {abs(spot - flip):,.0f} points {'below' if spot > flip else 'above'} price.")
    if sigma_open and open_px:
        moved = spot - open_px
        out["moved_sd"] = moved / sigma_open
        if state == "short":
            dirs = [1 if moved > 0 else -1] if abs(moved) > 0.1 * sigma_open else [1, -1]
            for d in dirs:
                for k in (1.0, 1.5, 2.0):
                    p = open_px + d * k * sigma_open
                    if (p - spot) * d > 0:
                        out["targets"].append({"label": f"Open {'+' if d > 0 else '-'}{k:g} sd", "price": p, "side": "long" if d > 0 else "short",
                                               "chance": touch_prob(abs(p - spot), sigma_rem)})
        elif state in ("long", "transition"):
            hi = out["call_wall"] if out["call_wall"] and out["call_wall"] > spot else open_px + 0.5 * sigma_open
            lo = out["put_wall"] if out["put_wall"] and out["put_wall"] < spot else open_px - 0.5 * sigma_open
            out["range"] = {"high": hi, "low": lo, "mid": (hi + lo) / 2,
                            "basis": "0DTE call and put walls" if out["call_wall"] and out["put_wall"] else "open +/- half an expected move"}
            out["targets"] = [{"label": "Range high (fade failed auctions above)", "price": hi, "side": "short", "chance": touch_prob(abs(hi - spot), sigma_rem)},
                              {"label": "Range middle (first target from either edge)", "price": (hi + lo) / 2, "side": "either", "chance": touch_prob(abs((hi + lo) / 2 - spot), sigma_rem)},
                              {"label": "Range low (fade failed auctions below)", "price": lo, "side": "long", "chance": touch_prob(abs(lo - spot), sigma_rem)}]
        if state == "long" and abs(moved) > sigma_open:
            out["notes"].append(f"Price already moved {abs(moved) / sigma_open:.1f} sd from the open and the regime is long gamma: the expansion is likely done. "
                                "Stop looking for high risk-to-reward setups.")
    if out["flips"]:
        last = out["flips"][-1]
        out["notes"].append(f"The regime flipped {len(out['flips'])} time(s) today; the last was {last['from']} to {last['to']} gamma.")
    return out


# ---- mean reversion --------------------------------------------------------------------------------------------------
def mean_reversion(prices, step_minutes=None, min_n=30):
    """prices: a list of floats in time order. The part-23 test on the distance from the window's average."""
    x = [p for p in prices if p is not None]
    n = len(x)
    if n < min_n:
        return {"available": False, "reason": f"Needs at least {min_n} price observations; {n} stored."}
    m = sum(x) / n
    u = [a - sum(x[:-1]) / (n - 1) for a in x[:-1]]
    v = [x[i + 1] - x[i] for i in range(n - 1)]
    uu = sum(a * a for a in u)
    if uu <= 0:
        return {"available": False, "reason": "Price did not move."}
    b = sum(a * c for a, c in zip(u, v)) / uu
    vm = sum(v) / len(v)
    e = [c - vm - b * a for a, c in zip(u, v)]
    se = math.sqrt(sum(r * r for r in e) / max(1, n - 3) / uu)
    t = b / se if se > 0 else 0.0
    hl = -math.log(2) / math.log(1 + b) if -1 < b < 0 else None
    sd = math.sqrt(sum((a - m) ** 2 for a in x) / n)
    z = (x[-1] - m) / sd if sd > 0 else 0.0
    if t <= T_LIMIT:
        verdict, lean = "Mean-reverting: a real pull back to the average", "range"
    elif t <= -2:
        verdict, lean = "Weak pull: random walks pass this often, do not trust it", "unclear"
    else:
        verdict, lean = "No pull: price is wandering or trending", "trend"
    return {"available": True, "n": n, "slope": b, "t_stat": t, "t_limit": T_LIMIT, "half_life_steps": hl,
            "half_life_minutes": hl * step_minutes if hl is not None and step_minutes else None, "step_minutes": step_minutes,
            "mean": m, "sd": sd, "z_now": z, "verdict": verdict, "lean": lean, "significant": t <= T_LIMIT,
            "note": "Distance from the average of the stored session prices. -2.9 is the Dickey-Fuller 5% value; at -2 about a third of pure random walks look like a pull."}


# ---- Monte Carlo -----------------------------------------------------------------------------------------------------
def monte_carlo(spot, sigma_rem, stop, rs=DEFAULT_RS, paths=None, minutes_left=390.0, half_life_minutes=None, mean=None, hi=None, lo=None, seed=17):
    """Paths to the close. sigma_rem: one sd of the remaining move in points. stop: stop distance in points.
    half_life_minutes + mean: pull paths toward `mean` (an Ornstein-Uhlenbeck walk) instead of a plain walk.
    Each step's true high and low are drawn from the Brownian bridge between its end points, so touches between steps are not missed."""
    if not sigma_rem or sigma_rem <= 0 or not stop or stop <= 0:
        return {"available": False, "reason": "Needs a remaining expected move and a stop distance above zero."}
    steps = int(min(400, max(60, (4 * sigma_rem / stop) ** 2)))
    paths = paths or (4000 if steps <= 120 else 2000)
    rng = random.Random(seed)
    sd = sigma_rem / math.sqrt(steps)
    var2 = 2 * sd * sd
    step_min = max(minutes_left, 1.0) / steps
    k = 1 - math.exp(-math.log(2) * step_min / half_life_minutes) if half_life_minutes and mean is not None else 0.0
    gauss, rnd, sqrt, log = rng.gauss, rng.random, math.sqrt, math.log
    s_lo, s_hi = spot - stop, spot + stop
    hit_long, hit_short = [], []                  # best excursion before the stop (or the close), in points
    end_long, end_short = [], []                  # where the close left the trade when neither target nor stop was hit
    stopped_long, stopped_short = [], []
    highs, lows = [], []
    every = max(1, steps // 60)                      # keep about 60 points of each path for the fan chart
    marks = [i for i in range(steps) if (i + 1) % every == 0 or i == steps - 1]
    track = {i: [] for i in marks}
    keep, sample = [], min(150, paths)
    for n_path in range(paths):
        p, mx, mn = spot, spot, spot
        line = [spot] if n_path < sample else None
        best_l = best_s = 0.0
        sl = ss = False
        for st in range(steps):
            q = p + (k * (mean - p) if k else 0.0) + sd * gauss(0, 1)
            d2 = (q - p) * (q - p)
            top = (p + q + sqrt(d2 - var2 * log(1.0 - rnd()))) / 2         # the step's high and low (Brownian bridge)
            bot = (p + q - sqrt(d2 - var2 * log(1.0 - rnd()))) / 2
            if top > mx:
                mx = top
            if bot < mn:
                mn = bot
            if not sl:
                if bot <= s_lo:
                    sl = True                                               # stop and target in the same step count as the stop
                elif top - spot > best_l:
                    best_l = top - spot
            if not ss:
                if top >= s_hi:
                    ss = True
                elif spot - bot > best_s:
                    best_s = spot - bot
            p = q
            if st in track:
                track[st].append(p)
                if line is not None:
                    line.append(p)
        if line is not None:
            keep.append(line)
        hit_long.append(best_l)
        hit_short.append(best_s)
        stopped_long.append(sl)
        stopped_short.append(ss)
        end_long.append(p - spot)
        end_short.append(spot - p)
        highs.append(max(mx, hi) if hi is not None else mx)
        lows.append(min(mn, lo) if lo is not None else mn)
    rows = []
    for r in rs:
        tgt = r * stop
        res = {}
        for side, best, stp, end in (("long", hit_long, stopped_long, end_long), ("short", hit_short, stopped_short, end_short)):
            win = sum(1 for b in best if b >= tgt)
            loss = sum(1 for b, s in zip(best, stp) if b < tgt and s)
            open_ = [e for b, s, e in zip(best, stp, end) if b < tgt and not s]
            ev = (win * r - loss + sum(e / stop for e in open_)) / paths
            res[side] = {"win": win / paths, "stop": loss / paths, "neither": len(open_) / paths, "ev_r": ev}
        rows.append({"r": r, "target_points": tgt, **res, "no_clock": 1 / (1 + r)})
    highs.sort()
    lows.sort()
    q = lambda arr, f: arr[min(len(arr) - 1, int(f * len(arr)))]
    t_min = [0.0] + [(i + 1) * step_min for i in marks]
    bands = {}
    for f in (0.05, 0.25, 0.5, 0.75, 0.95):
        bands[f"p{int(f * 100):02d}"] = [spot] + [q(sorted(track[i]), f) for i in marks]
    finals = sorted(track[marks[-1]])
    lo_f, hi_f = finals[0], finals[-1]
    nb = 40
    width = (hi_f - lo_f) / nb or 1.0
    hist = [0] * nb
    for v in finals:
        hist[min(nb - 1, int((v - lo_f) / width))] += 1
    fan = {"minutes": t_min, "paths": [[round(v, 2) for v in ln] for ln in keep], "bands": {k2: [round(v, 2) for v in b] for k2, b in bands.items()},
           "final_hist": {"lo": lo_f, "width": width, "counts": hist}, "start": spot}
    return {"available": True, "paths": paths, "steps": steps, "sigma_remaining": sigma_rem, "stop": stop, "rows": rows,
            "model": "pulled to the average (OU)" if k else "random walk", "half_life_minutes": half_life_minutes if k else None, "minutes_left": minutes_left,
            "fan": fan, "hod": {"p50": q(highs, 0.5), "p80": q(highs, 0.8), "p95": q(highs, 0.95)}, "lod": {"p50": q(lows, 0.5), "p20": q(lows, 0.2), "p05": q(lows, 0.05)},
            "note": "No-clock is the textbook chance for a driftless walk with no time limit, 1 / (1 + R). The clock (the 16:00 close) and the "
                    "pull to the average are what move the odds away from it. A target and stop touched inside the same step count as a stop."}


# ---- principal components ES / NQ ------------------------------------------------------------------------------------
def align(a, b, max_gap_s=180):
    """a, b: [(datetime, price)] sorted. Pairs each a observation with the nearest b within max_gap_s."""
    out, j = [], 0
    for t, p in a:
        while j + 1 < len(b) and abs((b[j + 1][0] - t).total_seconds()) <= abs((b[j][0] - t).total_seconds()):
            j += 1
        if b and abs((b[j][0] - t).total_seconds()) <= max_gap_s:
            out.append((t, p, b[j][1]))
    return out


def pca_pair(pairs, min_n=20):
    """pairs: [(t, nq_like, es_like)]. Eigen split of the return covariance and NQ's residual against ES."""
    ra, rb = [], []
    for i in range(1, len(pairs)):
        a0, b0, a1, b1 = pairs[i - 1][1], pairs[i - 1][2], pairs[i][1], pairs[i][2]
        if a0 > 0 and b0 > 0 and a1 > 0 and b1 > 0 and pairs[i][0] != pairs[i - 1][0]:
            ra.append(math.log(a1 / a0))
            rb.append(math.log(b1 / b0))
    n = len(ra)
    if n < min_n:
        return {"available": False, "reason": f"Needs at least {min_n} matched NDX and SPX observations; {n} so far. Both symbols must be tracked."}
    ma, mb = sum(ra) / n, sum(rb) / n
    saa = sum((x - ma) ** 2 for x in ra) / (n - 1)
    sbb = sum((x - mb) ** 2 for x in rb) / (n - 1)
    sab = sum((x - ma) * (y - mb) for x, y in zip(ra, rb)) / (n - 1)
    tr, half = (saa + sbb) / 2, math.sqrt(((saa - sbb) / 2) ** 2 + sab ** 2)
    l1, l2 = tr + half, tr - half
    if abs(sab) > 1e-18:
        v1 = (l1 - sbb, sab)
    else:
        v1 = (1.0, 0.0) if saa >= sbb else (0.0, 1.0)
    norm = math.hypot(*v1) or 1.0
    v1 = (v1[0] / norm, v1[1] / norm)
    if v1[0] + v1[1] < 0:
        v1 = (-v1[0], -v1[1])
    corr = sab / math.sqrt(saa * sbb) if saa > 0 and sbb > 0 else None
    beta = sab / sbb if sbb > 0 else None
    resid = [x - (beta or 0) * y for x, y in zip(ra, rb)]
    rm = sum(resid) / n
    rsd = math.sqrt(sum((x - rm) ** 2 for x in resid) / (n - 1)) if n > 1 else 0
    cum = sum(resid)
    z = cum / (rsd * math.sqrt(n)) if rsd > 0 else 0.0
    if corr is not None and corr < 0.5:
        read = "NQ and ES are not moving together enough in this window for the comparison to mean much (correlation under 0.5)."
    elif z >= 2:
        read = "NQ is running ahead of ES (stronger than its usual ratio). A divergence worth checking for SMT."
    elif z <= -2:
        read = "NQ is lagging ES (weaker than its usual ratio). A divergence worth checking for SMT."
    else:
        read = "NQ and ES are moving in line with their usual relationship."
    return {"available": True, "n": n, "eigenvalues": [l1, l2], "pc1_share": l1 / (l1 + l2) if l1 + l2 > 0 else None, "pc1_loadings": {"nq": v1[0], "es": v1[1]},
            "pc2_loadings": {"nq": -v1[1], "es": v1[0]}, "correlation": corr, "beta": beta, "residual_cum_pct": cum * 100, "residual_z": z, "read": read,
            "note": "PC1 is the shared market move; its share says how much of the movement NQ and ES have in common. The residual is NQ's return "
                    "minus beta times ES's, added up over the session. Index prices (NDX and SPX) stand in for NQ and ES."}


# ---- projected high and low of the day -------------------------------------------------------------------------------
def hodlod(open_px, hi, lo, spot, sigma_open, sigma_rem, ks=LADDER, walls=None):
    """The static ladder from the open with chances at the open and now. walls: {call_wall, put_wall, flip} (0DTE) or None."""
    if not open_px or not sigma_open:
        return {"available": False, "reason": "Needs the 9:30 price and the expected move stored near the open."}
    hi = max(hi if hi is not None else spot, spot)
    lo = min(lo if lo is not None else spot, spot)
    up, dn = [], []
    for k in ks:
        pu, pd = open_px + k * sigma_open, open_px - k * sigma_open
        up.append({"k": k, "price": pu, "at_open": touch_prob(k * sigma_open, sigma_open), "now": touch_prob(pu - spot, sigma_rem) if hi < pu else 1.0,
                   "hit": hi >= pu})
        dn.append({"k": k, "price": pd, "at_open": touch_prob(k * sigma_open, sigma_open), "now": touch_prob(spot - pd, sigma_rem) if lo > pd else 1.0,
                   "hit": lo <= pd})
    proj = None
    if sigma_rem and sigma_rem > 0:
        qm = lambda f: _N.inv_cdf((1 + f) / 2)            # quantile of a running maximum, in sd
        proj = {"hod": {f"p{int(f * 100)}": max(hi, spot + sigma_rem * qm(f)) for f in (0.5, 0.8, 0.95)},
                "lod": {f"p{int(f * 100)}": min(lo, spot - sigma_rem * qm(f)) for f in (0.5, 0.8, 0.95)}}
    w = walls or {}
    caps = []
    if w.get("call_wall"):
        caps.append({"label": "0DTE call wall (likely ceiling in long gamma)", "price": w["call_wall"], "side": "hod", "now": touch_prob(w["call_wall"] - spot, sigma_rem) if w["call_wall"] > hi else 1.0})
    if w.get("put_wall"):
        caps.append({"label": "0DTE put wall (likely floor in long gamma)", "price": w["put_wall"], "side": "lod", "now": touch_prob(spot - w["put_wall"], sigma_rem) if w["put_wall"] < lo else 1.0})
    return {"available": True, "open": open_px, "high": hi, "low": lo, "spot": spot, "sigma_open": sigma_open, "sigma_remaining": sigma_rem,
            "range_sd": (hi - lo) / sigma_open, "up": up, "down": dn, "projection": proj, "walls": caps,
            "note": "Ladder: the open +/- k standard deviations of the day (from the expected move at the open), fixed for the session. "
                    "Chance = how often a random walk touches that far: 2 x (1 - N(distance / sd)). 'Now' re-runs it from the current price with the "
                    "remaining expected move. Real days have fatter tails than this, especially in short gamma."}


# ---- the moves we may encounter (HOD / LOD tab) ----------------------------------------------------------------------
TYPICAL_RANGE_SD = 2 * math.sqrt(2 / math.pi)      # a random walk's average full-day range is about 1.6 standard deviations


def stay_inside(x, lo, hi, sigma):
    """Chance a driftless random walk starting at x stays strictly between lo and hi until the close (sigma = remaining 1 sd).
    The classic two-barrier series: sum over odd n of 4/(n pi) sin(n pi u / L) exp(-(n pi sigma / L)^2 / 2)."""
    if sigma is None or sigma <= 0 or not lo < x < hi:
        return None
    L, u = hi - lo, x - lo
    tot = 0.0
    for n in range(1, 400, 2):
        term = 4 / (n * math.pi) * math.sin(n * math.pi * u / L) * math.exp(-0.5 * (n * math.pi * sigma / L) ** 2)
        tot += term
        if abs(term) < 1e-9:
            break
    return min(1.0, max(0.0, tot))


def move_map(spot, hi, lo, open_px, sigma_open, sigma_rem, levels, state, greeks=None, events=None, mins_left=None, to_fut=None):
    """What can happen from here: the path up and the path down through the levels (each with its call and touch chance), the
    chance of staying between the nearest levels until the close, and the data behind it, each with what it means for the move."""
    to_fut = to_fut or (lambda v: None)
    if not sigma_rem or not sigma_open:
        return {"available": False, "reason": "Needs the expected move (the session has closed or no expiry is priced)."}
    above = sorted((l for l in levels if l["value"] > spot), key=lambda l: l["value"])[:4]
    below = sorted((l for l in levels if l["value"] < spot), key=lambda l: -l["value"])[:4]
    word = {"RESPECT": "should reject", "CHOP": "should stall and chop", "DISRESPECT": "should break and run"}

    def chain(lv, d):
        out, stop = [], None
        for i, l in enumerate(lv):
            dist = abs(l["value"] - spot)
            row = {"price": l["value"], "futures": to_fut(l["value"]), "label": l["label"], "call": l["call"], "why": l["why"],
                   "points": dist, "sd": dist / sigma_rem, "chance": touch_prob(dist, sigma_rem)}
            if stop is None and l["call"] == "RESPECT":
                stop = i
                row["note"] = f"First level that {word['RESPECT']}: the likely {'high' if d > 0 else 'low'} of the day if price gets here."
            elif stop is not None:
                row["note"] = "Only in play if the level before it gives way."
            elif l["call"] == "DISRESPECT":
                row["note"] = "Price should go through this one; it adds speed toward the next level."
            else:
                row["note"] = "Expect overlap and two-way wicks here before price picks a side."
            out.append(row)
        return out
    up, dn = chain(above, 1), chain(below, -1)
    rng = None
    if above and below:
        p_in = stay_inside(spot, below[0]["value"], above[0]["value"], sigma_rem)
        rng = {"low": below[0]["value"], "high": above[0]["value"], "low_futures": to_fut(below[0]["value"]), "high_futures": to_fut(above[0]["value"]),
               "low_label": below[0]["label"], "high_label": above[0]["label"], "stay_inside": p_in}
    used = (hi - lo) / sigma_open if hi is not None and lo is not None else None
    drivers = []
    if state == "short":
        drivers.append({"name": "Gamma regime", "reading": "Short gamma (dealers short gamma at price)", "effect": "Dealers hedge with the move, so ranges tend to run past the expected move. Favour the break of the first level and aim far."})
    elif state == "long":
        drivers.append({"name": "Gamma regime", "reading": "Long gamma (dealers long gamma at price)", "effect": "Dealers hedge against the move, so moves fade at levels. Favour rejections and the range; keep targets small."})
    else:
        drivers.append({"name": "Gamma regime", "reading": "At the 0DTE flip" if state == "transition" else "Unknown", "effect": "The regime can switch on a small move. Wait for price to leave the flip."})
    if used is not None:
        frac = used / TYPICAL_RANGE_SD
        drivers.append({"name": "Range used", "reading": f"{hi - lo:,.0f} points, {used:.2f} sd ({frac * 100:.0f}% of a typical day's range)",
                        "effect": ("Most of a normal day's range is done; new highs or lows need extra fuel." if frac >= 0.9 else
                                   "Plenty of range left for a normal day." if frac <= 0.5 else "About an average amount of range left.")})
    drivers.append({"name": "Time left", "reading": f"{mins_left:.0f} minutes, 1 sd still to come = {sigma_rem:,.1f} points" if mins_left else f"1 sd = {sigma_rem:,.1f} points",
                    "effect": "The chances below shrink as the clock runs: the same distance gets harder to reach later in the day."})
    if greeks:
        dr, t = greeks.get("drift_to_close") or 0.0, greeks.get("totals") or {}
        if dr:
            drivers.append({"name": "Charm into the close", "reading": f"Dealers {'sell' if dr > 0 else 'buy'} about ${abs(dr) / 1e9:,.2f} billion by 16:00 if price and IV hold",
                            "effect": f"A {'downward' if dr > 0 else 'upward'} drift as the day goes on, strongest in the last hour. It {'helps the LOD side' if dr > 0 else 'helps the HOD side'}."})
        if t.get("vanna"):
            v = t["vanna"]
            drivers.append({"name": "Vanna (IV moves)", "reading": f"If IV falls 1 point dealers {'buy' if v > 0 else 'sell'} about ${abs(v) / 1e9:,.2f} billion",
                            "effect": f"A volatility crush (calm tape, after an event) pushes price {'up' if v > 0 else 'down'}; a volatility spike does the reverse."})
        if t.get("dex"):
            drivers.append({"name": "Dealer delta", "reading": f"Dealers net {'long' if t['dex'] > 0 else 'short'} ${abs(t['dex']) / 1e9:,.1f} billion",
                            "effect": "Context for how much hedging is already on; large and one-sided positioning makes squeezes bigger."})
    for e in events or []:
        drivers.append({"name": "Scheduled event", "reading": f"{e['name']}{' ' + e['time'] + ' ET' if e.get('time') else ''}",
                        "effect": "A big release can blow through any level and any regime. Expect the calls to be less reliable around it."})
    up_first = next((r for r in up if r["call"] == "RESPECT"), up[-1] if up else None)
    dn_first = next((r for r in dn if r["call"] == "RESPECT"), dn[-1] if dn else None)
    summary = []
    if up_first:
        summary.append(f"Upside: the likely ceiling is {up_first['label'].split(' / ')[0]} at {up_first['price']:,.0f}" +
                       (f" ({up_first['futures']:,.0f} futures)" if up_first.get("futures") else "") + f", a {up_first['chance'] * 100:.0f}% chance to be touched.")
    if dn_first:
        summary.append(f"Downside: the likely floor is {dn_first['label'].split(' / ')[0]} at {dn_first['price']:,.0f}" +
                       (f" ({dn_first['futures']:,.0f} futures)" if dn_first.get("futures") else "") + f", a {dn_first['chance'] * 100:.0f}% chance to be touched.")
    if rng and rng["stay_inside"] is not None:
        pin = "under 1%" if rng["stay_inside"] < 0.005 else "over 99%" if rng["stay_inside"] > 0.995 else f"{rng['stay_inside'] * 100:.0f}%"
        summary.append(f"A {pin} chance price stays between {rng['low']:,.0f} and {rng['high']:,.0f} until the close.")
    return {"available": True, "up": up, "down": dn, "range": rng, "drivers": drivers, "summary": summary,
            "note": "Chances use the remaining expected move and the running-maximum rule for a random walk; calls come from the gamma regime and the "
                    "dealer gamma at each level (the Level map rules). Real days have fatter tails, especially in short gamma. Scenarios, not forecasts."}
