"""/api/export/tab-pine: one TradingView indicator per Q DATA tab that has levels, each named after its tab.

register() is called from api_quant.register with the quant helpers (context, stack_map, level_map, game_plan, quant).
Prices are converted to the futures contract (NQ / ES) whenever the app can, the same way the Level map and Stack map tabs do.
"""
from __future__ import annotations

from fastapi import HTTPException

from .services import analytics as an
from .services import flows as fl
from .services import quant as qt
from .services.tab_pine import CALL_COLOR, CALL_WORD, build_all_pine, build_tab_pine
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


def sent(*parts):
    """Join bits of text as sentences."""
    out = []
    for p in parts:
        p = str(p or "").strip()
        if p:
            out.append(p if p[-1] in ".!?:" else p + ".")
    return " ".join(out)


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

        def gi(name):
            if name not in groups:
                groups.append(name)
            return groups.index(name)

        def add(price, group, label, color, style="solid", width=1, tip=None, low=None, high=None, convert=True):
            if price is None:
                return
            f = tc if convert else (lambda v: v)
            levels.append({"price": f(price), "low": f(low) if low is not None else None, "high": f(high) if high is not None else None,
                           "group": gi(group), "label": label, "color": color, "style": style, "width": width, "tip": tip or label})

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
                gi(f"Stacked areas: {CALL_WORD[call]} ({call})" if tab == "stackmap" else f"{CALL_WORD[call]} levels ({call})")
        elif tab in CAT_TABS:
            for cat in CAT_TABS[tab][0]:
                gi(CAT[cat][0])

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
                add(cd["entry"], f"{grp}: entries", f"{tag} entry", col, "solid", 2 if top else 1, why)
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
            add(L.get("call_wall"), "Walls", f"Call wall ({L.get('walls_basis')})", "#22d3ee", "solid", 2, "The main ceiling.")
            add(L.get("put_wall"), "Walls", f"Put wall ({L.get('walls_basis')})", "#ff4d8d", "solid", 2, "The main floor.")
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
            add(last("call_wall"), "Walls", "Call wall", "#22d3ee", "solid", 2)
            add(last("put_wall"), "Walls", "Put wall", "#ff4d8d", "solid", 2)
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
                add(z.get("flip"), "0DTE flip and walls", "0DTE flip", "#ffd166", "dashed", 1)
                add(z.get("call_wall"), "0DTE flip and walls", "0DTE call wall", "#22d3ee", "solid", 1)
                add(z.get("put_wall"), "0DTE flip and walls", "0DTE put wall", "#ff4d8d", "solid", 1)
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
            add(z.get("call_wall"), "0DTE walls", "0DTE call wall", "#22d3ee", "solid", 2, "Biggest positive 0DTE gamma strike.")
            add(z.get("put_wall"), "0DTE walls", "0DTE put wall", "#ff4d8d", "solid", 2, "Biggest negative 0DTE gamma strike.")
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
    def export_tab_pine(tab: str, underlying: str, convention: str = "standard"):
        """The levels on one tab as a TradingView indicator named after that tab."""
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
        code = build_tab_pine(title, short, groups, levels, table, src, units, to_et(c["now"]).strftime("%Y-%m-%d %H:%M ET"), cone, about=about)
        return {"code": code, "title": title, "tab": tab, "levels": len(levels), "groups": groups, "mapped": mapped, "futures_root": root, "meta": m,
                "filename": f"qdata_{fname}_{u.lstrip('_')}.pine",
                "note": f"Paste into TradingView's Pine Editor and add to chart. It shows up as '{title}'. Each kind of level has its own show/hide box in the settings, "
                        "and hovering a label shows why it is there. The levels are baked in, so re-copy each session."}

    ALL_DEFAULT_ON = ("stackmap", "gameplan", "session")

    @app.get("/api/export/all-pine")
    def export_all_pine(underlying: str, convention: str = "standard", on: str | None = None):
        """Every tab's levels in ONE indicator ("Q DATA All Tabs"): an on/off switch per tab, and under it a box per kind of level.
        on: comma list of tabs switched on when the indicator is first added (default Stack map, Game plan, Session)."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = q.context(u, convention)
        want_on = set((on or ",".join(ALL_DEFAULT_ON)).split(","))
        sections, skipped, cone = [], [], None
        for tab, (title, short, fname) in TABS.items():
            try:
                groups, levels, table, cone_, about = tab_parts(tab, u, convention, c)
            except HTTPException as e:
                skipped.append({"tab": tab, "title": title, "reason": str(e.detail)})
                continue
            cone = cone or cone_
            sections.append({"tab": tab, "name": title.replace("Q DATA ", ""), "on": tab in want_on, "groups": groups, "levels": levels, "table": table})
        units, src, sym, data = head(c)
        code = build_all_pine(sections, [sym, data], src, units, to_et(c["now"]).strftime("%Y-%m-%d %H:%M ET"), cone)
        return {"code": code, "title": "Q DATA All Tabs", "tabs": [{"tab": x["tab"], "name": x["name"], "levels": len(x["levels"]), "on": x["on"]} for x in sections],
                "skipped": skipped, "levels": sum(len(x["levels"]) for x in sections), "mapped": c["spot_f"] is not None, "meta": c["m"],
                "filename": f"qdata_all_tabs_{u.lstrip('_')}.pine",
                "note": "One indicator with every tab. In its settings each tab has an on/off switch and a box for each kind of level. The levels are baked in, so re-copy each session."}
