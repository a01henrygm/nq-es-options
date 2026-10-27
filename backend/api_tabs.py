"""/api/export/tab-pine: one TradingView indicator per Q DATA tab that has levels, each named after its tab.

register() is called from api_quant.register with the quant helpers (context, stack_map, level_map, game_plan, quant).
Prices are converted to the futures contract (NQ / ES) whenever the app can, the same way the Level map and Stack map tabs do.
"""
from __future__ import annotations

from fastapi import Body, HTTPException

from .services import analytics as an
from .services import flows as fl
from .services import quant as qt
from .services.tab_pine import CALL_COLOR, CALL_WORD, SETTINGS, STYLES, TAB_COLORS, apply_kind_prefs, build_all_pine, build_tab_pine, setting_value, _group
from .timeutil import to_et

# category -> (show/hide group name, color, line style). Colors match the Key levels indicator.
CAT = {
    "gamma_flip": ("Gamma flip", "#e6b422", "solid"), "gex0_flip": ("0DTE gamma flip", "#ffd166", "dashed"),
    "gex0_call_wall": ("0DTE call wall", "#22d3ee", "solid"), "gex0_put_wall": ("0DTE put wall", "#ff4d8d", "solid"),
    "gex_concentration": ("Biggest GEX strikes", "#2f8bf5", "solid"),
    "gex_call_zone": ("GEX call wall zones", "#3fb96a", "solid"), "gex_put_zone": ("GEX put wall zones", "#e5534b", "solid"),
    "gex_pos_zone": ("Positive GEX zones", "#2f8bf5", "solid"), "gex_neg_zone": ("Negative GEX zones", "#a371f7", "solid"),
    "open_interest": ("Open interest strikes", "#ff7a2e", "solid"), "oi_by_expiry": ("Open interest by expiry", "#ff7a2e", "dashed"),
    "oi_mid": ("Open interest midpoints", "#ffb37a", "dotted"), "oi_call_zone": ("Call open interest", "#ff9f43", "solid"),
    "oi_put_zone": ("Put open interest", "#d9480f", "solid"),
    "volume": ("Volume strikes", "#3fb96a", "solid"), "volume_by_expiry": ("Volume by expiry", "#3fb96a", "dashed"),
    "volume_mid": ("Volume midpoints", "#8fd6a5", "dotted"), "volume_call_zone": ("Call volume", "#2ec4b6", "solid"),
    "volume_put_zone": ("Put volume", "#f06292", "solid"),
    "expected_move": ("Expected move", "#7db7ff", "dotted"), "expected_move_ext": ("Expected move (wider)", "#8e9bff", "dotted"),
    "charm_sell_zone": ("Charm: dealers sell", "#e76f51", "solid"), "charm_buy_zone": ("Charm: dealers buy", "#2a9d8f", "solid"),
    "vanna_pos_zone": ("Vanna positive", "#c77dff", "solid"), "vanna_neg_zone": ("Vanna negative", "#ffb703", "solid"),
    "dex_pos_zone": ("Dealer delta: long", "#4cc9f0", "solid"), "dex_neg_zone": ("Dealer delta: short", "#f72585", "solid"),
    "new_call_zone": ("New call positions", "#b5e48c", "solid"), "new_put_zone": ("New put positions", "#ff6b6b", "solid"),
    "custom": ("Your levels", "#ffffff", "solid"),
}

# tab key -> (indicator title, short title, file name part). Only tabs that draw levels.
TABS = {
    "stackmap": ("Q DATA Stack Map", "QD Stack", "stack_map"),
    "levelmap": ("Q DATA Level Map", "QD LvlMap", "level_map"),
    "gameplan": ("Q DATA Game Plan", "QD Plan", "game_plan"),
    "bias": ("Q DATA Bias and Plan", "QD Bias", "bias_plan"),
    "session": ("Q DATA Session", "QD Session", "session"),
    "regime": ("Q DATA Regime", "QD Regime", "regime"),
    "vix": ("Q DATA Volatility (VIX)", "QD VIX", "volatility"),
    "quant": ("Q DATA Quant Lab", "QD Quant", "quant_lab"),
    "gex": ("Q DATA GEX by Strike", "QD GEX", "gex_by_strike"),
    "zerodte": ("Q DATA 0DTE GEX", "QD 0DTE", "zero_dte_gex"),
    "flip": ("Q DATA Gamma Flip", "QD Flip", "gamma_flip"),
    "flows": ("Q DATA Charm and Vanna", "QD Charm", "charm_vanna"),
    "oi": ("Q DATA Open Interest", "QD OI", "open_interest"),
    "volume": ("Q DATA Volume", "QD Volume", "volume"),
    "preopen": ("Q DATA Overnight Changes", "QD Overnight", "overnight_changes"),
    "move": ("Q DATA Expected Move", "QD ExpMove", "expected_move"),
    "delta": ("Q DATA Delta Exposure", "QD Delta", "delta_exposure"),
}
# Tabs whose levels are the app's level list filtered to some categories: (categories, extra levels_payload settings)
CAT_TABS = {
    "gex": (["gex_concentration", "gex_call_zone", "gex_put_zone", "gex_pos_zone", "gex_neg_zone", "gamma_flip"], {"top": 6}),
    "flip": (["gamma_flip", "gex0_flip"], {}),
    "flows": (["charm_sell_zone", "charm_buy_zone", "vanna_pos_zone", "vanna_neg_zone"], {}),
    "oi": (["open_interest", "oi_by_expiry", "oi_mid", "oi_call_zone", "oi_put_zone"], {"top": 6, "by_expiry": 4, "mid": 2}),
    "volume": (["volume", "volume_by_expiry", "volume_mid", "volume_call_zone", "volume_put_zone"], {"top": 6, "by_expiry": 4, "mid": 2}),
    "preopen": (["new_call_zone", "new_put_zone"], {}),
    "delta": (["dex_pos_zone", "dex_neg_zone"], {}),
}


# What each kind of level means, in plain words: (short meaning shown next to the label, longer help shown in the settings tooltip)
HELP_RULES = [
    ("Stacked areas: HOLD", "stack, should hold", "Several different kinds of levels in one area, and the call is HOLD: price should stall and reject there. Fade it with a stop just past the area."),
    ("Stacked areas: CHOP", "stack, two-way", "Several kinds stacked, but the call is CHOP: expect back-and-forth around it. No edge either way; wait for price to leave it."),
    ("Stacked areas: BREAK", "stack, likely breaks", "Several kinds stacked, but the call is BREAK: in this gamma regime price tends to push through. Trade the break, not the fade."),
    ("HOLD levels", "should hold", "Price should respect this level: stall and reject, wicks through but closes back."),
    ("CHOP levels", "two-way trade", "Expect chop around this level: no clean hold or break."),
    ("BREAK levels", "likely breaks", "Price is likely to disrespect this level and push through it."),
    ("long entries", "buy here", "A Game plan long setup: the entry price. Hover the label for the grade and the team vote."),
    ("short entries", "sell here", "A Game plan short setup: the entry price. Hover the label for the grade and the team vote."),
    ("stops", "stop", "Where the setup is wrong: just past the far side of the area."),
    ("targets", "target", "The setup's target, at the R the Monte Carlo liked best."),
    ("Stay away", "no edge", "A CHOP area or a setup the team voted down: no edge, stay out."),
    ("0DTE gamma flip", "0DTE regime line", "Where today's-expiry dealer gamma flips sign. Above it moves get absorbed; below it moves get chased."),
    ("0DTE flip", "0DTE regime line", "Where today's-expiry dealer gamma flips sign. Above it moves get absorbed; below it moves get chased."),
    ("Gamma flip", "regime line", "Where total dealer gamma flips sign. Above it dealers dampen moves (range day); below it they add to moves (trend day)."),
    ("0DTE call wall", "0DTE ceiling", "Today's-expiry strike with the most positive gamma: a magnet and a ceiling while gamma is positive."),
    ("0DTE put wall", "0DTE floor", "Today's-expiry strike with the most negative gamma: a floor that can give way hard if broken."),
    ("Call wall", "ceiling", "The biggest call positioning: the main ceiling. Accepted above it, the ceiling is gone."),
    ("Put wall", "floor", "The biggest put positioning: the main floor. Accepted below it, the floor is gone."),
    ("Top + 0DTE", "+gamma strike", "Big positive 0DTE gamma: dealers sell rallies and buy dips around it, so price tends to stick."),
    ("Top - 0DTE", "-gamma strike", "Big negative 0DTE gamma: dealers hedge with the move, so price can speed up through it."),
    ("Biggest GEX", "big gamma strike", "Strikes with the most dealer gamma. Price often pauses or pins at them."),
    ("GEX call wall zones", "call wall zone", "Band around the call-side gamma wall: resistance while gamma is positive."),
    ("GEX put wall zones", "put wall zone", "Band around the put-side gamma wall: support, weaker if gamma turns negative."),
    ("Positive GEX zones", "+GEX, dampens", "Dealers long gamma here: they dampen moves, so expect slower, mean-reverting trade."),
    ("Negative GEX zones", "-GEX, speeds up", "Dealers short gamma here: they add to moves, so expect faster trade through it."),
    ("Call open interest", "call OI", "Heavy call open interest: often resistance."),
    ("Put open interest", "put OI", "Heavy put open interest: often support."),
    ("Call volume", "call volume", "Heavy call trading today at this strike."),
    ("Put volume", "put volume", "Heavy put trading today at this strike."),
    ("Open interest", "open interest", "Strikes with the most open contracts: positions people care about, often reaction points."),
    ("Volume", "today's volume", "Strikes trading the most today: where today's money is."),
    ("Expected move (wider)", "outer move", "The wider expected-move band: price gets here on bigger days only."),
    ("Expected move", "expected move", "The move options price for the day: about 2 days in 3 stay inside."),
    ("Straddle", "straddle move", "Spot +/- the at-the-money straddle: the market's price for the move to that expiry."),
    ("1 sd", "1 sd move", "1 standard deviation from implied volatility: about 68% of the time price stays inside."),
    ("2 sd", "2 sd move", "2 standard deviations: about 95% of the time price stays inside. Rarely reached."),
    ("Charm: dealers sell", "charm selling", "Charm makes dealers sell here as time passes: a drift lower into the close."),
    ("Charm: dealers buy", "charm buying", "Charm makes dealers buy here as time passes: a drift higher into the close."),
    ("Vanna positive", "vanna +", "If volatility falls, dealers buy here (vanna)."),
    ("Vanna negative", "vanna -", "If volatility rises, dealers sell here (vanna)."),
    ("Dealer delta: long", "dealers long delta", "Dealers net long delta here: they sell into rallies to hedge."),
    ("Dealer delta: short", "dealers short delta", "Dealers net short delta here: they buy dips to hedge."),
    ("New call", "new calls", "Fresh call positions since the last session."),
    ("New put", "new puts", "Fresh put positions since the last session."),
    ("9:30 open", "the open", "Today's 9:30 open: the anchor for the expected move and the cone."),
    ("Playbook range", "range edge", "The gamma playbook's range: fade failed auctions at the edges, the middle is the first target."),
    ("Playbook targets", "playbook target", "Targets from the gamma playbook for today's regime."),
    ("Monte Carlo high", "simulated HOD", "Where simulated paths put today's high: e.g. 80% means 4 paths in 5 top out at or below it."),
    ("Monte Carlo low", "simulated LOD", "Where simulated paths put today's low."),
    ("Typical day", "VIX day range", "The 9:30 open +/- the typical day priced by the VIX family: +/-1 holds about 2 days in 3, +/-2 about 19 in 20."),
    ("Your levels", "your level", "A level you typed into Q DATA."),
]


def help_for(name):
    for key, short, long_ in HELP_RULES:
        if key.lower() in name.lower():
            return short, long_
    return "", name


def sent(*parts):
    """Join bits of text as sentences."""
    out = []
    for p in parts:
        p = str(p or "").strip()
        if p:
            out.append(p if p[-1] in ".!?:" else p + ".")
    return " ".join(out)


def zone_pts(c):
    """Default distance for joining levels into a stack zone: about 0.04% of price (NQ about 10 points, ES about 2.5)."""
    px = c["spot_f"] or c["snap"].spot
    return max(0.25, round(px * 0.0004 * 4) / 4)


def pct(v):
    return None if v is None else f"{v * 100:.0f}%"


def register(app, h, q):
    def ep(path):
        """Another tab's endpoint function (they are registered in other modules)."""
        for r in app.routes:
            if getattr(r, "path", None) == path:
                return r.endpoint
        raise HTTPException(500, f"missing route {path}")

    @app.get("/api/export/tab-pine/tabs")
    def tab_pine_tabs():
        return {"tabs": [{"tab": k, "title": v[0]} for k, v in TABS.items()]}

    def tab_parts(tab, u, convention, c):
        """One tab's levels: (groups, levels, table rows, cone, about). Raises HTTPException(409) when the tab has nothing right now."""
        snap, root = c["snap"], c["root"]
        mapped = c["spot_f"] is not None
        tc = (lambda v: None if v is None else c["conv"](v)) if mapped else (lambda v: v)
        groups, levels, table, cone, about = [], [], [], None, ""

        names = []

        def gi(name, color=None, style="solid", width=1):
            """A kind of level (one show/hide row in the indicator settings, with its own color, style and width)."""
            if name not in names:
                names.append(name)
                short, long_ = help_for(name)
                groups.append({"name": name, "color": color, "style": style, "width": width, "short": short, "help": long_})
            g = groups[names.index(name)]
            if g["color"] is None and color:
                g.update({"color": color, "style": style, "width": width})
            return names.index(name)

        def add(price, group, label, color, style="solid", width=1, tip=None, low=None, high=None, convert=True):
            if price is None:
                return
            f = tc if convert else (lambda v: v)
            k = gi(group, color, style, width)
            levels.append({"price": f(price), "low": f(low) if low is not None else None, "high": f(high) if high is not None else None,
                           "group": k, "label": label, "boost": max(0, int(width) - int(groups[k]["width"] or 1)), "tip": tip or label})

        def from_categories(cats, extra):
            j = h.levels_payload(u, convention, "auto", ",".join(cats), extra.get("top", 2), None, extra.get("by_expiry", 0), extra.get("mid", 0), extra.get("moves", 0))
            for x in j["levels"]:
                name, col, sty = CAT.get(x["category"], (x["category"], "#9aa4b8", "solid"))
                tip = f"{x['label']}. {x.get('method') or ''}".strip()
                if x.get("importance") is not None:
                    tip += f" Importance {x['importance']:.2f}."
                add(x["value"], name, x["label"], col, sty, 2 if x["category"] in ("gamma_flip", "gex0_call_wall", "gex0_put_wall") else 1, tip,
                    x.get("low"), x.get("high"))
            return j

        if tab in ("stackmap", "levelmap"):                  # same three boxes every time, even when one call has no levels today
            for call in ("RESPECT", "CHOP", "DISRESPECT"):
                gi(f"Stacked areas: {CALL_WORD[call]} ({call})" if tab == "stackmap" else f"{CALL_WORD[call]} levels ({call})", CALL_COLOR[call], "solid", 2 if tab == "stackmap" else 1)
        elif tab in CAT_TABS:
            for cat in CAT_TABS[tab][0]:
                gi(CAT[cat][0], CAT[cat][1], CAT[cat][2], 2 if cat in ("gamma_flip", "gex0_call_wall", "gex0_put_wall") else 1)

        if tab == "stackmap":
            sm = q.stack_map(u, convention, 3, 0.05)
            for st in sm["stacks"]:
                call = st["call"]
                n = len(st["families"])
                name = f"Stacked areas: {CALL_WORD[call]} ({call})"
                tip = sent(f"{st['tier']}: {n} kinds ({', '.join(st['family_names'])})", st.get("headline"), st.get("plan"),
                           f"Chance price gets here today {pct(st.get('chance')) or '-'}", f"Why: {st.get('why') or ''}")
                add(st["center"], name, f"STACK {n}x {CALL_WORD[call]}", CALL_COLOR[call], "solid", 3 if st["tier"] == "Very stacked" else 2, tip,
                    st["low"] if st["high"] > st["low"] else None, st["high"] if st["high"] > st["low"] else None)
            ai = sm["already_in"] or {}
            table = [("Regime", sm["regime"]["title"]), ("High already in", pct(ai.get("high"))), ("Low already in", pct(ai.get("low"))),
                     ("Stacked areas", str(len(sm["stacks"]))), ("Rule", f"3+ kinds within {sm['inputs']['tolerance_points']:,.0f} index points")]
            about = "Only areas where at least 3 different kinds of levels sit together. Green HOLD, yellow CHOP, red BREAK."
        elif tab == "levelmap":
            lm = q.level_map(u, convention, 40)
            for l in lm["levels"]:
                call = l["call"]
                tip = sent(f"{l['label']}: {CALL_WORD[call]}", l.get("headline"), l.get("plan"), f"Chance today {pct(l.get('chance')) or '-'}", f"Why: {l.get('why') or ''}")
                add(l["value"], f"{CALL_WORD[call]} levels ({call})", f"{l['label']} {CALL_WORD[call]}", CALL_COLOR[call], "solid", 1, tip, l.get("low"), l.get("high"))
            cn = lm["counts"]
            table = [("Regime", lm["regime"]["title"]), ("HOLD / CHOP / BREAK", f"{cn.get('RESPECT', 0)} / {cn.get('CHOP', 0)} / {cn.get('DISRESPECT', 0)}"),
                     ("Targets", lm["regime"].get("r_range"))]
            about = "Every key level with what price should do there: green HOLD (respect), yellow CHOP, red BREAK (disrespect)."
        elif tab == "gameplan":
            gpj = q.game_plan(u, convention)
            if not gpj.get("available"):
                raise HTTPException(409, gpj.get("reason") or "No game plan right now.")
            for i, cd in enumerate(gpj["cards"] + gpj["more"]):
                top = i < len(gpj["cards"])
                tag = f"#{i + 1} {cd['grade']} {cd['side']}"
                col = "#3fb96a" if cd["side"] == "LONG" else "#e5534b"
                why = f"{cd['side']} {cd['kind']} at {cd['label']} ({CALL_WORD.get(cd['call'], cd['call'])}). Grade {cd['grade']}: {cd['yes']} for, {cd['no']} against. Target {cd['r']:.1f}R."
                grp = "Top setups" if top else "More setups"
                add(cd["entry"], f"{grp}: {cd['side'].lower()} entries", f"{tag} entry", col, "solid", 2 if top else 1, why)
                add(cd["stop"], f"{grp}: stops", f"{tag} stop", "#9aa4b8", "dotted", 1, why)
                add(cd["target"], f"{grp}: targets", f"{tag} target {cd['r']:.1f}R", "#7db7ff", "dashed", 1, why)
            for a in gpj["avoid"]:
                p = a.get("level", a.get("price"))
                add(p, "Stay away (no edge)", "AVOID " + str(a.get("label") or ""), "#e6b422", "dotted", 1, a.get("reason") or "No edge here.")
            ai = gpj.get("already_in") or {}
            table = [("Regime", gpj["regime"]["title"]), ("Setups", str(len(gpj["cards"]))), ("High already in", pct(ai.get("high"))),
                     ("Low already in", pct(ai.get("low"))), ("No trade", gpj.get("no_trade"))]
            about = "The Game plan tab's graded setups: entry, stop and target lines. Hover a label for the team vote."
        elif tab == "bias":
            b = ep("/api/analytics/bias")(underlying=u, convention=convention)["data"]
            L = b["levels"]
            add(L.get("flip"), "Gamma flip", "Gamma flip", "#e6b422", "solid", 2, b["day_type"]["why"])
            add(L.get("call_wall"), "Call wall", f"Call wall ({L.get('walls_basis')})", "#22d3ee", "solid", 2, "The main ceiling.")
            add(L.get("put_wall"), "Put wall", f"Put wall ({L.get('walls_basis')})", "#ff4d8d", "solid", 2, "The main floor.")
            em = L.get("expected_move") or {}
            add(em.get("high"), "Expected move", f"EM high ({em.get('method')})", "#7db7ff", "dotted")
            add(em.get("low"), "Expected move", f"EM low ({em.get('method')})", "#7db7ff", "dotted")
            table = [("Bias", b["verdict"]), ("Confidence", b["confidence"]["label"]), ("Day type", b["day_type"]["label"])]
            for w in (b.get("what_would_change") or [])[:2]:
                table.append(("Would change", w[:90]))
        elif tab == "session":
            sj = ep("/api/charts/session")(underlying=u, day=None, scope="all")
            last = lambda k: (sj.get(k) or [{}])[-1].get("value")
            add(last("flip"), "Gamma flip", "Gamma flip", "#e6b422", "solid", 2)
            add(last("call_wall"), "Call wall", "Call wall", "#22d3ee", "solid", 2)
            add(last("put_wall"), "Put wall", "Put wall", "#ff4d8d", "solid", 2)
            op = (sj.get("open") or {}).get("price")
            dmv = (sj.get("day_move") or {}).get("points")
            add(op, "9:30 open", "9:30 open", "#ffffff", "dashed", 1)
            if op and dmv and sj.get("day"):
                y, mo, d = (int(x) for x in sj["day"].split("-"))
                o_c, e_c = tc(op), tc(op + dmv)
                if o_c is not None and e_c is not None:
                    cone = {"open": o_c, "move": e_c - o_c, "y": y, "m": mo, "d": d}
            table = [("Day", sj.get("day")), ("Day's expected move", f"{(cone or {}).get('move', 0):,.0f} pts" if cone else None),
                     ("From", (sj.get("day_move") or {}).get("method"))]
        elif tab == "regime":
            r = ep("/api/analytics/regime")(underlying=u, convention=convention)["data"]
            z = c["z"]
            gf = an.gamma_flip(snap.contracts, snap.spot, c["now"], convention)
            add(gf["flip"] if gf["found"] else None, "Gamma flip", "Gamma flip", "#e6b422", "solid", 2, r.get("meaning"))
            if z.get("available"):
                add(z.get("flip"), "0DTE flip", "0DTE flip", "#ffd166", "dashed", 1)
                add(z.get("call_wall"), "0DTE call wall", "0DTE call wall", "#22d3ee", "solid", 1)
                add(z.get("put_wall"), "0DTE put wall", "0DTE put wall", "#ff4d8d", "solid", 1)
            pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
            rg = pb.get("range") or {}
            for k, nm in (("high", "Range high"), ("mid", "Range middle"), ("low", "Range low")):
                add(rg.get(k), "Playbook range", nm, pb.get("color") or "#3fb96a", "dashed", 1, f"{pb['title']}: {pb['tagline']}")
            table = [("Regime", f"{r['label']} ({r['confidence']})"), ("Gamma", pb["title"]), ("Meaning", r.get("meaning", "")[:90])]
            for w in (r.get("what_would_change") or [])[:1]:
                table.append(("Would change", w[:90]))
        elif tab == "vix":
            vj = ep("/api/volatility")()
            if not vj.get("available"):
                raise HTTPException(409, vj.get("reason") or "No VIX data yet.")
            nasdaq = "nq" if root in ("NQ", "MNQ") or "NDX" in u else "es"
            mv = (vj["moves"].get("nq_today") if nasdaq == "nq" else None) or vj["moves"].get(f"{nasdaq}_day") or {}
            pts = mv.get("index_points")
            if not (c["open"] and pts):
                raise HTTPException(409, "Needs today's 9:30 open and a VIX-family reading for this symbol.")
            for k, sty in ((1, "solid"), (2, "dashed")):
                for sg in (1, -1):
                    add(c["open"] + sg * k * pts, f"Typical day +/-{k}", f"VIX day {'+' if sg > 0 else '-'}{k}", "#a371f7" if k == 1 else "#c77dff", sty, 1,
                        f"The 9:30 open {'+' if sg > 0 else '-'} {k} x the typical day priced by {mv.get('from')}. About {'2 days in 3' if k == 1 else '19 days in 20'} stay inside.")
            add(c["open"], "9:30 open", "9:30 open", "#ffffff", "dashed")
            table = [("Volatility regime", vj["regime"]["label"]), ("Typical day", f"{(mv.get('futures_points') or pts):,.0f} pts"), ("From", mv.get("from"))]
        elif tab == "quant":
            qj = q.quant(u, convention, None, "auto")["data"]
            pb = qj["playbook"]
            for t in pb.get("targets") or []:
                add(t["price"], "Playbook targets", t["label"].split(" (")[0], pb.get("color") or "#3fb96a", "dashed", 1, f"{t['label']}. Chance today {pct(t.get('chance'))}.")
            mc = qj["monte_carlo"]
            if mc.get("available"):
                for k, v in (mc.get("hod") or {}).items():
                    add(v, "Monte Carlo high of day", f"MC HOD {k[1:]}%", "#3fb96a", "dotted", 1, f"{k[1:]}% of simulated paths make their high at or below this by the close.")
                for k, v in (mc.get("lod") or {}).items():
                    add(v, "Monte Carlo low of day", f"MC LOD {k[1:]}%", "#e5534b", "dotted", 1, f"{k[1:]}% of simulated paths make their low at or above this by the close.")
            table = [("Gamma", pb["title"]), ("Targets", pb.get("r_range")), ("Model", qj.get("model_used")),
                     ("Mean reversion", "significant" if (qj["mean_reversion"] or {}).get("significant") else "not significant")]
        elif tab == "zerodte":
            z = c["z"]
            if not z.get("available"):
                raise HTTPException(409, "No 0DTE expiry with data right now.")
            add(z.get("call_wall"), "0DTE call wall", "0DTE call wall", "#22d3ee", "solid", 2, "Biggest positive 0DTE gamma strike.")
            add(z.get("put_wall"), "0DTE put wall", "0DTE put wall", "#ff4d8d", "solid", 2, "Biggest negative 0DTE gamma strike.")
            add(z.get("flip"), "0DTE flip", "0DTE flip", "#ffd166", "dashed", 2, z.get("flip_note"))
            for k in (z.get("top_positive") or [])[:5]:
                if k not in (z.get("call_wall"),):
                    add(k, "Top + 0DTE GEX strikes", "0DTE +GEX", "#2f8bf5", "solid", 1)
            for k in (z.get("top_negative") or [])[:5]:
                if k not in (z.get("put_wall"),):
                    add(k, "Top - 0DTE GEX strikes", "0DTE -GEX", "#a371f7", "solid", 1)
            table = [("Expiry", z.get("expiry")), ("0DTE share of gamma", pct(z.get("gross_share")))]
        elif tab == "move":
            rows = ep("/api/analytics/moves")(underlying=u, n=3)["rows"]
            for i, r in enumerate(rows[:3]):
                tag = "today" if i == 0 else r["expiry"]
                for key, nm, sty, col in (("straddle_levels", "Straddle", "solid", "#7db7ff"), ("sd1_levels", "1 sd", "dashed", "#8e9bff"), ("sd2_levels", "2 sd", "dotted", "#c77dff")):
                    lv_ = r.get(key) or {}
                    for side, sg in (("up", "+"), ("down", "-")):
                        add(lv_.get(side), f"{nm} ({'nearest expiry' if i == 0 else 'later expiries'})", f"{nm} {sg} {tag}", col, sty, 2 if i == 0 else 1,
                            f"{nm} move to the {r['expiry']} expiry: {sg}{(r.get('straddle') if key == 'straddle_levels' else r.get('sd1') if key == 'sd1_levels' else r.get('sd2')) or 0:,.0f} index points.")
            if rows:
                table = [("Nearest expiry", rows[0]["expiry"]), ("Straddle", f"{rows[0]['straddle']:,.0f} index pts" if rows[0].get("straddle") else None),
                         ("ATM IV", pct(rows[0].get("atm_iv")))]
        else:
            cats, extra = CAT_TABS[tab]
            j = from_categories(cats, extra)
            table = [("Levels", str(len(levels)))]
            if tab == "flows":
                drift = fl.greek_exposure(snap.contracts, snap.spot, c["now"], convention).get("drift_to_close")
                if drift is not None:
                    table.append(("Charm drift to close", f"dealers {'buy' if drift > 0 else 'sell'} into the close"))
            if tab == "flip":
                gf = an.gamma_flip(snap.contracts, snap.spot, c["now"], convention)
                table += [("Reliability", gf.get("reliability")), ("Crossings", str(gf.get("crossings")))]
            if tab == "preopen" and not levels:
                table.append(("Note", "Needs the previous session's open interest, stored daily from the next session on."))

        return groups, levels, table, cone, about

    def head(c):
        m, root, mapped = c["m"], c["root"], c["spot_f"] is not None
        units = (f"Prices are ESTIMATED {root} points (converted from {m['underlying']})." if mapped
                 else f"Prices are in {m['underlying']} units (no {root or 'futures'} price or basis saved). Use the offset setting.")
        src = f"Source: {m['provider']} {m['underlying']}, snapshot {m['calculated_at_et']}."
        return units, src, ("Symbol", f"{m['underlying']} -> {root} (est.)" if mapped else m["underlying"]), ("Data", f"{m['calculated_at_et']} ({m['data_status']})")

    @app.get("/api/export/tab-pine")
    def export_tab_pine_get(tab: str, underlying: str, convention: str = "standard"):
        return export_tab_pine(tab, underlying, convention)

    def export_tab_pine(tab: str, underlying: str, convention: str = "standard", prefs: dict | None = None):
        """The levels on one tab as a TradingView indicator named after that tab. prefs: the look chosen on the TradingView indicator tab."""
        if tab not in TABS:
            raise HTTPException(422, f"tab must be one of {', '.join(TABS)}")
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = q.context(u, convention)
        m, root, mapped = c["m"], c["root"], c["spot_f"] is not None
        title, short, fname = TABS[tab]
        groups, levels, table, cone, about = tab_parts(tab, u, convention, c)
        table = [("Symbol", f"{m['underlying']} -> {root} (est.)" if mapped else m["underlying"])] + table + [("Data", f"{m['calculated_at_et']} ({m['data_status']})")]
        units = (f"Prices are ESTIMATED {root} points (converted from {m['underlying']})." if mapped
                 else f"Prices are in {m['underlying']} units (no {root or 'futures'} price or basis saved). Use the offset setting.")
        src = f"Source: {m['provider']} {m['underlying']}, snapshot {m['calculated_at_et']}, data status: {m['data_status']}, sign scenario {convention}."
        code = build_tab_pine(title, short, groups, levels, table, src, units, to_et(c["now"]).strftime("%Y-%m-%d %H:%M ET"), cone, about=about,
                              zone_pts=zone_pts(c), prefs=clean_prefs(prefs), tab=tab)
        return {"code": code, "title": title, "tab": tab, "levels": len(levels), "groups": [g["name"] for g in groups], "mapped": mapped, "futures_root": root, "meta": m,
                "filename": f"qdata_{fname}_{u.lstrip('_')}.pine",
                "note": f"Paste into TradingView's Pine Editor and add to chart. It shows up as '{title}'. Each kind of level has its own show/hide box in the settings, "
                        "and hovering a label shows why it is there. The levels are baked in, so re-copy each session."}

    @app.post("/api/export/tab-pine")
    def export_tab_pine_post(tab: str, underlying: str, convention: str = "standard", body: dict = Body(default={})):
        return export_tab_pine(tab, underlying, convention, (body or {}).get("prefs"))

    ALL_DEFAULT_ON = ("stackmap", "gameplan", "session")

    @app.get("/api/export/all-pine")
    def export_all_pine_get(underlying: str, convention: str = "standard", on: str | None = None):
        return export_all_pine(underlying, convention, on)

    def export_all_pine(underlying: str, convention: str = "standard", on: str | None = None, prefs: dict | None = None):
        """Every tab's levels in ONE indicator ("Q DATA All Tabs"): an on/off switch and a color per tab, and under it a row per kind of level.
        on: comma list of tabs switched on when the indicator is first added (default Stack map, Game plan, Session).
        prefs: the look chosen on Q DATA's TradingView indicator tab (see services/tab_pine.py); its tabs_on wins over `on`.
        Every tab is always in the indicator, even one with no levels right now, so the settings stay in the same places from day
        to day (TradingView remembers settings by their position in the script)."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = q.context(u, convention)
        prefs = clean_prefs(prefs)
        want_on = set(prefs["tabs_on"]) if isinstance(prefs.get("tabs_on"), list) else set((on or ",".join(ALL_DEFAULT_ON)).split(","))
        prefs.pop("tabs_on", None)
        sections, skipped, cone = [], [], None
        for tab, (title, short, fname) in TABS.items():
            try:
                groups, levels, table, cone_, about = tab_parts(tab, u, convention, c)
            except HTTPException as e:
                skipped.append({"tab": tab, "title": title, "reason": str(e.detail)})
                groups, levels, table, cone_, about = [], [], [], None, str(e.detail)
            cone = cone or cone_
            sections.append({"tab": tab, "name": title.replace("Q DATA ", ""), "on": tab in want_on, "groups": groups, "levels": levels, "table": table, "about": about})
        units, src, sym, data = head(c)
        zp = zone_pts(c)
        code = build_all_pine(sections, [sym, data], src, units, to_et(c["now"]).strftime("%Y-%m-%d %H:%M ET"), cone, zone_pts=zp, prefs=prefs)
        kinds = {}
        for sec in sections:
            for g in sec["groups"]:
                k = apply_kind_prefs(_group(g), prefs)
                d = _group(g)
                row = kinds.setdefault(k["name"], {"name": k["name"], "on": k["on"], "color": k["color"], "style": k["style"].lower(), "width": k["width"],
                                                   "default": {"color": d["color"], "style": d["style"].lower(), "width": d["width"]},
                                                   "short": k["short"], "help": k["help"], "tabs": []})
                row["tabs"].append(sec["name"])
        auto = {"maxDistPct": 4.0, "zDist": zp, "zMaxW": zp * 4}
        settings = [{**x, "value": setting_value(x, prefs.get("set"), auto), "auto": x["default"] is None, "default": x["default"] if x["default"] is not None else auto[x["var"]]}
                    for x in SETTINGS]
        return {"code": code, "title": "Q DATA All Tabs",
                "tabs": [{"tab": x["tab"], "name": x["name"], "levels": len(x["levels"]), "on": x["on"], "kinds": len(x["groups"]),
                          "color": (prefs.get("tab_colors") or {}).get(x["tab"]) or TAB_COLORS[i % len(TAB_COLORS)], "default_color": TAB_COLORS[i % len(TAB_COLORS)],
                          "default_on": x["tab"] in ALL_DEFAULT_ON}
                         for i, x in enumerate(sections)],
                "kinds": list(kinds.values()), "settings": settings,
                "skipped": skipped, "levels": sum(len(x["levels"]) for x in sections), "mapped": c["spot_f"] is not None, "meta": c["m"],
                "filename": f"qdata_all_tabs_{u.lstrip('_')}.pine",
                "note": "One indicator with every tab. In its settings each tab has an on/off switch and a color, and a row for each kind of level. The levels are baked in, so re-copy each session."}

    @app.post("/api/export/all-pine")
    def export_all_pine_post(underlying: str, convention: str = "standard", body: dict = Body(default={})):
        """Same as the GET, with the look from Q DATA's TradingView indicator tab in the body: {"prefs": {...}}."""
        return export_all_pine(underlying, convention, None, (body or {}).get("prefs"))


def clean_prefs(prefs) -> dict:
    """Keep only the parts of the indicator look that the builder understands, with sane types. Bad values are dropped
    (the builder then uses its defaults), never an error: an old saved look must not stop the indicator being made."""
    if not isinstance(prefs, dict):
        return {}
    out = {}
    if isinstance(prefs.get("set"), dict):
        out["set"] = {k: v for k, v in prefs["set"].items() if isinstance(k, str) and isinstance(v, (bool, int, float, str))}
    if isinstance(prefs.get("tabs_on"), list):
        out["tabs_on"] = [x for x in prefs["tabs_on"] if x in TABS]
    if isinstance(prefs.get("tab_colors"), dict):
        out["tab_colors"] = {k: v for k, v in prefs["tab_colors"].items() if k in TABS and isinstance(v, str)}
    if isinstance(prefs.get("kinds"), dict):
        out["kinds"] = {}
        for name, k in list(prefs["kinds"].items())[:500]:
            if isinstance(name, str) and isinstance(k, dict):
                out["kinds"][name] = {kk: k[kk] for kk in ("on", "color", "style", "width") if kk in k}
    return out
