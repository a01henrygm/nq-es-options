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
from .services.paste_pine import build_levels_text, build_paste_script, is_key_kind
from .services.level_kinds import CAT, HELP_RULES, help_for  # noqa: F401  (shared with the Key levels indicator)
from .timeutil import to_et

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
    "hodlod": ("Q DATA HOD / LOD", "QD HOD/LOD", "hod_lod"),      # last, so adding it did not move the other tabs' settings
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
                col = "#00d65c" if cd["side"] == "LONG" else "#ff3b30"
                why = f"{cd['side']} {cd['kind']} at {cd['label']} ({CALL_WORD.get(cd['call'], cd['call'])}). Grade {cd['grade']}: {cd['yes']} for, {cd['no']} against. Target {cd['r']:.1f}R."
                grp = "Top setups" if top else "More setups"
                add(cd["entry"], f"{grp}: {cd['side'].lower()} entries", f"{tag} entry", col, "solid", 2 if top else 1, why)
                add(cd["stop"], f"{grp}: stops", f"{tag} stop", "#9aa4b8", "dotted", 1, why)
                add(cd["target"], f"{grp}: targets", f"{tag} target {cd['r']:.1f}R", "#4da6ff", "dashed", 1, why)
            for a in gpj["avoid"]:
                p = a.get("level", a.get("price"))
                add(p, "Stay away (no edge)", "AVOID " + str(a.get("label") or ""), "#ffc400", "dotted", 1, a.get("reason") or "No edge here.")
            ai = gpj.get("already_in") or {}
            table = [("Regime", gpj["regime"]["title"]), ("Setups", str(len(gpj["cards"]))), ("High already in", pct(ai.get("high"))),
                     ("Low already in", pct(ai.get("low"))), ("No trade", gpj.get("no_trade"))]
            about = "The Game plan tab's graded setups: entry, stop and target lines. Hover a label for the team vote."
        elif tab == "bias":
            b = ep("/api/analytics/bias")(underlying=u, convention=convention)["data"]
            L = b["levels"]
            add(L.get("flip"), "Gamma flip", "Gamma flip", "#ffc400", "solid", 2, b["day_type"]["why"])
            add(L.get("call_wall"), "Call wall", f"Call wall ({L.get('walls_basis')})", "#00e5ff", "solid", 2, "The main ceiling.")
            add(L.get("put_wall"), "Put wall", f"Put wall ({L.get('walls_basis')})", "#ff1f7a", "solid", 2, "The main floor.")
            em = L.get("expected_move") or {}
            add(em.get("high"), "Expected move", f"EM high ({em.get('method')})", "#4da6ff", "dotted")
            add(em.get("low"), "Expected move", f"EM low ({em.get('method')})", "#4da6ff", "dotted")
            table = [("Bias", b["verdict"]), ("Confidence", b["confidence"]["label"]), ("Day type", b["day_type"]["label"])]
            for w in (b.get("what_would_change") or [])[:2]:
                table.append(("Would change", w[:90]))
        elif tab == "session":
            sj = ep("/api/charts/session")(underlying=u, day=None, scope="all")
            last = lambda k: (sj.get(k) or [{}])[-1].get("value")
            add(last("flip"), "Gamma flip", "Gamma flip", "#ffc400", "solid", 2)
            add(last("call_wall"), "Call wall", "Call wall", "#00e5ff", "solid", 2)
            add(last("put_wall"), "Put wall", "Put wall", "#ff1f7a", "solid", 2)
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
            add(gf["flip"] if gf["found"] else None, "Gamma flip", "Gamma flip", "#ffc400", "solid", 2, r.get("meaning"))
            if z.get("available"):
                add(z.get("flip"), "0DTE flip", "0DTE flip", "#ffdd00", "dashed", 1)
                add(z.get("call_wall"), "0DTE call wall", "0DTE call wall", "#00e5ff", "solid", 1)
                add(z.get("put_wall"), "0DTE put wall", "0DTE put wall", "#ff1f7a", "solid", 1)
            pb = qt.gamma_playbook(z, snap.spot, c["open"], c["sig_open"], c["gamma_series"], c["sig_rem"])
            rg = pb.get("range") or {}
            for k, nm in (("high", "Range high"), ("mid", "Range middle"), ("low", "Range low")):
                add(rg.get(k), "Playbook range", nm, pb.get("color") or "#00d65c", "dashed", 1, f"{pb['title']}: {pb['tagline']}")
            table = [("Regime", f"{r['label']} ({r['confidence']})"), ("Gamma", pb["title"]), ("Meaning", r.get("meaning", "")[:90])]
            for w in (r.get("what_would_change") or [])[:1]:
                table.append(("Would change", w[:90]))
        elif tab == "hodlod":
            hd = ep("/api/analytics/hodlod")(underlying=u, convention=convention)["data"]
            d = hd["hodlod"]
            if not d.get("available"):
                raise HTTPException(409, d.get("reason") or "No HOD / LOD read right now.")
            sd = d["sigma_open"]
            add(d["open"], "9:30 open", "9:30 open", "#ffffff", "dashed", 1, "Today's 9:30 open: the HOD / LOD ladder is built from it.")
            add(d["high"], "High of day so far", "HOD so far", "#00d65c", "solid", 2, "The session's high so far (from the app's own prices; TradingView's may differ by a tick or two).")
            add(d["low"], "Low of day so far", "LOD so far", "#ff3b30", "solid", 2, "The session's low so far (from the app's own prices; TradingView's may differ by a tick or two).")
            for side, rows, col, sign in (("HOD", d["up"], "#4da6ff", "+"), ("LOD", d["down"], "#ffa04d", "-")):
                for r in rows:
                    tip = sent(f"Open {sign}{r['k']:g} sd ({r['k'] * sd:,.0f} index points)", f"Chance at the open {pct(r['at_open']) or '-'}",
                               "Already hit today" if r["hit"] else f"Chance from here {pct(r['now']) or '-'}")
                    add(r["price"], f"{side} ladder (open {sign} sd)", f"{side} {sign}{r['k']:g} sd" + (" (hit)" if r["hit"] else ""), col, "dotted", 1, tip)
                    groups[names.index(f"{side} ladder (open {sign} sd)")]["on"] = False     # the full ladder is a lot of lines: off until you switch it on
            pr = d.get("projection")
            if pr:
                for side, col in (("hod", "#00e5ff"), ("lod", "#ff1f7a")):
                    for key, word in (("p50", "50%"), ("p80", "80%"), ("p95", "95%")):
                        v = pr[side].get(key)
                        tip = (f"Projected {'high' if side == 'hod' else 'low'} of the day: {word} of random-walk paths from here, with the move left in the day, "
                               f"{'top out at or below' if side == 'hod' else 'bottom out at or above'} this price.")
                        add(v, f"Projected {side.upper()}", f"{side.upper()} {word}", col, "dashed", 2 if key == "p80" else 1, tip)
            ai = hd.get("already_in") or {}
            table = [("High already in", pct(ai.get("high"))), ("Low already in", pct(ai.get("low"))), ("Range so far", f"{d['range_sd']:.2f} sd"),
                     ("Minutes left", f"{hd['minutes_left']:.0f}" if hd.get("minutes_left") else "closed")]
            about = "Today's high and low so far, the open +/- sd ladder (where the high and low usually land), and the projected HOD and LOD from here (50/80/95%)."
            if not pr:
                about += " The session has closed, so there is no projection until the next open."
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
                    add(c["open"] + sg * k * pts, f"Typical day +/-{k}", f"VIX day {'+' if sg > 0 else '-'}{k}", "#a64dff" if k == 1 else "#c34dff", sty, 1,
                        f"The 9:30 open {'+' if sg > 0 else '-'} {k} x the typical day priced by {mv.get('from')}. About {'2 days in 3' if k == 1 else '19 days in 20'} stay inside.")
            add(c["open"], "9:30 open", "9:30 open", "#ffffff", "dashed")
            table = [("Volatility regime", vj["regime"]["label"]), ("Typical day", f"{(mv.get('futures_points') or pts):,.0f} pts"), ("From", mv.get("from"))]
        elif tab == "quant":
            qj = q.quant(u, convention, None, "auto")["data"]
            pb = qj["playbook"]
            for t in pb.get("targets") or []:
                add(t["price"], "Playbook targets", t["label"].split(" (")[0], pb.get("color") or "#00d65c", "dashed", 1, f"{t['label']}. Chance today {pct(t.get('chance'))}.")
            mc = qj["monte_carlo"]
            if mc.get("available"):
                for k, v in (mc.get("hod") or {}).items():
                    add(v, "Monte Carlo high of day", f"MC HOD {k[1:]}%", "#00d65c", "dotted", 1, f"{k[1:]}% of simulated paths make their high at or below this by the close.")
                for k, v in (mc.get("lod") or {}).items():
                    add(v, "Monte Carlo low of day", f"MC LOD {k[1:]}%", "#ff3b30", "dotted", 1, f"{k[1:]}% of simulated paths make their low at or above this by the close.")
            table = [("Gamma", pb["title"]), ("Targets", pb.get("r_range")), ("Model", qj.get("model_used")),
                     ("Mean reversion", "significant" if (qj["mean_reversion"] or {}).get("significant") else "not significant")]
        elif tab == "zerodte":
            z = c["z"]
            if not z.get("available"):
                raise HTTPException(409, "No 0DTE expiry with data right now.")
            add(z.get("call_wall"), "0DTE call wall", "0DTE call wall", "#00e5ff", "solid", 2, "Biggest positive 0DTE gamma strike.")
            add(z.get("put_wall"), "0DTE put wall", "0DTE put wall", "#ff1f7a", "solid", 2, "Biggest negative 0DTE gamma strike.")
            add(z.get("flip"), "0DTE flip", "0DTE flip", "#ffdd00", "dashed", 2, z.get("flip_note"))
            for k in (z.get("top_positive") or [])[:5]:
                if k not in (z.get("call_wall"),):
                    add(k, "Top + 0DTE GEX strikes", "0DTE +GEX", "#1e7bff", "solid", 1)
            for k in (z.get("top_negative") or [])[:5]:
                if k not in (z.get("put_wall"),):
                    add(k, "Top - 0DTE GEX strikes", "0DTE -GEX", "#a64dff", "solid", 1)
            table = [("Expiry", z.get("expiry")), ("0DTE share of gamma", pct(z.get("gross_share")))]
        elif tab == "move":
            rows = ep("/api/analytics/moves")(underlying=u, n=3)["rows"]
            for i, r in enumerate(rows[:3]):
                tag = "today" if i == 0 else r["expiry"]
                for key, nm, sty, col in (("straddle_levels", "Straddle", "solid", "#4da6ff"), ("sd1_levels", "1 sd", "dashed", "#7a5cff"), ("sd2_levels", "2 sd", "dotted", "#c34dff")):
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

    ALL_DEFAULT_ON = ("stackmap", "gameplan", "session", "hodlod")

    @app.get("/api/export/all-pine")
    def export_all_pine_get(underlying: str, convention: str = "standard", on: str | None = None):
        return export_all_pine(underlying, convention, on)

    def export_all_pine(underlying: str, convention: str = "standard", on: str | None = None, prefs: dict | None = None):
        """Every tab's levels in ONE indicator ("Q DATA All Tabs"): an on/off switch and a color per tab, and under it a row per kind of level.
        on: comma list of tabs switched on when the indicator is first added (default Stack map, Game plan, Session, HOD / LOD).
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

    # ---- Q DATA All Tabs as a paste-in indicator: the script once, the levels text each session ----
    PASTE_DEFAULT_ON = ("stackmap", "gameplan", "session", "hodlod")

    @app.get("/api/export/all-script")
    def export_all_script():
        """The paste-in All Tabs script. It does not depend on the data: add it to TradingView once."""
        code = build_paste_script([(k, v[0].replace("Q DATA ", "")) for k, v in TABS.items()])
        return {"code": code, "title": "Q DATA All Tabs", "filename": "qdata_all_tabs_paste_in.pine",
                "note": "Add this to TradingView once (Pine Editor > paste > Save > Add to chart). Then each session paste the levels from Q DATA into its settings."}

    @app.post("/api/export/all-levels")
    def export_all_levels(underlying: str, convention: str = "standard", body: dict = Body(default={})):
        """The levels text to paste into the paste-in All Tabs indicator. body: {"prefs": {...}} from the TradingView indicator tab:
        tabs_on = which tabs go into the text (default Stack map, Game plan, Session, HOD / LOD), kinds = each kind's look
        (on, color, style, width, key)."""
        if convention not in an.SIGNS:
            raise HTTPException(422, "invalid convention")
        u = h.underlying_ok(underlying)
        c = q.context(u, convention)
        prefs = clean_prefs((body or {}).get("prefs"))
        want = set(prefs["tabs_on"]) if isinstance(prefs.get("tabs_on"), list) else set(PASTE_DEFAULT_ON)
        sections, skipped, cone, every = [], [], None, []
        for tab, (title, short, fname) in TABS.items():
            name = title.replace("Q DATA ", "")
            try:
                groups, levels, table, cone_, about = tab_parts(tab, u, convention, c)
            except HTTPException as e:
                skipped.append({"tab": tab, "title": title, "reason": str(e.detail)})
                every.append({"tab": tab, "name": name, "on": tab in want, "levels": 0, "kinds": 0, "reason": str(e.detail), "default_on": tab in PASTE_DEFAULT_ON})
                continue
            every.append({"tab": tab, "name": name, "on": tab in want, "levels": len(levels), "kinds": len(groups), "reason": "", "default_on": tab in PASTE_DEFAULT_ON,
                          "groups": groups})
            if tab in want:
                cone = cone or cone_
                sections.append({"tab": tab, "name": name, "groups": groups, "levels": levels, "table": table})
        units, src, sym, data = head(c)
        m = c["m"]
        made = to_et(c["now"]).strftime("%b %d %H:%M ET")
        out = build_levels_text(sections, [sym, data], made, to_et(c["now"]).strftime("%Y-%m-%d"), m["underlying"], units, cone,
                                c["spot_f"] or c["snap"].spot, prefs)
        kp = prefs.get("kinds") or {}
        kinds = {}
        for tb in every:
            for g in tb.get("groups") or []:
                d = _group(g)
                p = kp.get(d["name"]) or {}
                row = kinds.setdefault(d["name"], {"name": d["name"], "on": p["on"] if isinstance(p.get("on"), bool) else d["on"],
                                                   "key": p["key"] if isinstance(p.get("key"), bool) else is_key_kind(d["name"]),
                                                   "color": p.get("color") or d["color"], "style": (p.get("style") or d["style"]).lower(), "width": p.get("width") or d["width"],
                                                   "default": {"color": d["color"], "style": d["style"].lower(), "width": d["width"], "on": d["on"], "key": is_key_kind(d["name"])},
                                                   "short": d["short"], "help": d["help"], "tabs": []})
                row["tabs"].append(tb["name"])
            tb.pop("groups", None)
        return {"text": out["text"], "levels": out["levels"], "chars": out["chars"], "tips_dropped": out["tips_dropped"], "cut": out["cut"],
                "tabs": every, "kinds": list(kinds.values()), "skipped": skipped, "mapped": c["spot_f"] is not None, "meta": m,
                "key_lines": sum(1 for line in out["text"].splitlines() if line.startswith("L|") and line.split("|")[7 - 1] == "1"),
                "note": "Paste into the Q DATA All Tabs indicator's settings (Levels from Q DATA). Copy again each session."}


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
                out["kinds"][name] = {kk: k[kk] for kk in ("on", "color", "style", "width", "key") if kk in k}
    return out
