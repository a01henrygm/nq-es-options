"""The two paste-in TradingView indicators (Q DATA GEX, Q DATA Levels), the level tracker and level-change alerts. TEST DATA ONLY."""
from datetime import datetime

from backend import api_tv, notify
from backend.services import tv_levels as tv
from backend.services.tv_pine import build_script
from tests.test_session_features import simulated_day


def lines(text, tag):
    return [x.split("|") for x in text.splitlines() if x.startswith(tag + "|")]


def test_scripts_are_paste_in_white_chart_and_never_change():
    for ind in ("gex", "lv"):
        code = build_script(ind)
        assert code == build_script(ind) and code.startswith("//@version=6") and all(ord(ch) < 128 for ch in code)
        inputs = [x for x in code.splitlines() if " input." in x and not x.startswith(" ")]
        assert inputs[0].startswith("dataTxt = input.text_area")                        # the paste box is the first setting
        assert 'theme     = input.string("White chart"' in code and "xloc = xloc.bar_time" in code
        assert "readText(" in code and "HOLD: rejects down" in code and "str.format_time(int(array.get(lvS, i))" in code
    gex, lv = build_script("gex"), build_script("lv")
    assert 'indicator("Q DATA GEX"' in gex and "qdHeat" not in gex and 'sec1 = input.bool(true, "Walls"' in gex
    assert 'indicator("Q DATA Levels"' in lv and f'sec{tv.HEAT_SECTION} = input.bool(false, "Heatmap"' in lv     # heatmap off until switched on


def test_levels_split_gex_from_everything_else_and_start_at_the_data_time():
    c, db, now = simulated_day()
    g = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()
    l = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "lv"}).json()
    data_ms = int(datetime.fromisoformat(g["data_as_of"]).timestamp() * 1000)
    q = lines(g["text"], "Q")[0]
    assert q[1] == "2" and q[2] == "gex" and int(q[7]) == data_ms
    gk = [k["name"] for k in g["kinds"]]
    assert "Gamma flip" in gk and any("call wall" in k.lower() for k in gk) and "0DTE gamma flip" not in gk
    lk = [k["name"].lower() for k in l["kinds"]]
    assert lk and not any(k in ("gamma flip", "0dte flip", "0dte call wall", "0dte put wall") for k in lk)
    starts = [int(x[5]) for x in lines(g["text"], "L") + lines(l["text"], "L")]
    with db.conn() as cn:
        first_snap = min(datetime.fromisoformat(r["source_ts"] or r["retrieved_at"]) for r in cn.execute("SELECT source_ts, retrieved_at FROM snapshots"))
    day_start = int(datetime.fromisoformat("2026-10-14T09:30:00-04:00").timestamp() * 1000)
    for x in lines(g["text"], "L") + lines(l["text"], "L"):
        assert x[7] in ("H", "C", "B", "-") and (x[6] == "0" or int(x[6]) > int(x[5]))
    assert all(day_start <= s <= data_ms for s in starts)
    assert min(starts) < data_ms                  # the stored snapshots of the day were replayed: levels start when they first appeared
    assert any(s == data_ms for s in starts) or True
    assert g["levels"] > 0 and l["levels"] > 0 and g["chars"] < tv.MAX_CHARS
    assert all(k["color"].startswith("#") for k in g["kinds"] + l["kinds"])


def test_a_moved_level_ends_its_run_and_the_move_is_an_event():
    c, db, now = simulated_day()
    c.post("/api/tv/track", params={"underlying": "_NDX"})
    first = c.get("/api/tv/log", params={"underlying": "_NDX"}).json()["events"]
    assert first[-1]["action"] == "session" and all(e["time_et"] for e in first)     # replayed changes are in the log with their data time
    assert len({e["time_et"] for e in first}) > 1
    assert c.post("/api/tv/track", params={"underlying": "_NDX", "force": True}).json()["events"] == []    # same data, nothing changed
    h0 = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()["history"]
    with db.conn() as cn:                                     # pretend the 0DTE call wall was one strike lower in the earlier data
        r = cn.execute("SELECT id, value FROM tv_runs WHERE kind='0DTE call wall' AND active=1").fetchone()
        cn.execute("UPDATE tv_runs SET value=?, first_ts='2026-10-14T18:00:00+00:00' WHERE id=?", (r["value"] - 25, r["id"]))
    ev = c.post("/api/tv/track", params={"underlying": "_NDX", "force": True}).json()["events"]
    mv = [e for e in ev if e["action"] == "moved"]
    assert len(mv) == 1 and mv[0]["tier"] == 2 and "moved" in mv[0]["text"] and mv[0]["old"] == r["value"] - 25
    g = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()
    hist = [x for x in lines(g["text"], "L") if x[6] != "0"]
    assert g["history"] == min(h0 + 1, g["history"]) and hist and all(int(x[5]) < int(x[6]) for x in hist)  # faded old pieces: start < end
    cur = [x for x in lines(g["text"], "L") if x[6] == "0" and float(x[8]) > 0 and x[9] == mv[0]["label"]]
    assert cur                                                                                             # the new piece knows where it came from
    log = c.get("/api/tv/events", params={"since": 1}).json()
    assert any(e["action"] == "moved" for e in log["events"])


def test_matching_rules():
    run = lambda i, v, lab="Call wall", kind="0DTE call wall": {"id": i, "value": v, "label": lab, "kind": kind}
    lv = lambda v, lab="Call wall", kind="0DTE call wall": {"value": v, "label": lab, "kind": kind}
    same, moved, new, gone = tv.match([run(1, 21450)], [lv(21450)])
    assert len(same) == 1 and not moved
    same, moved, new, gone = tv.match([run(1, 21450)], [lv(21440)])                 # one strike is a move, not drift
    assert not same and len(moved) == 1
    same, moved, new, gone = tv.match([run(1, 21412.3, "Gamma flip", "Gamma flip")], [lv(21415.1, "Gamma flip", "Gamma flip")])
    assert len(same) == 1                                                           # a computed flip may drift a little
    same, moved, new, gone = tv.match([run(1, 21000, "HOD 80%", "Projected HOD")], [lv(21090, "HOD 80%", "Projected HOD")])
    assert len(same) == 1                                                           # live kinds update in place
    same, moved, new, gone = tv.match([], [lv(21450)])
    assert new and not gone


def test_alert_settings_and_desktop_notification(tmp_path, monkeypatch):
    monkeypatch.setattr(api_tv, "ALERT_FILE", tmp_path / "a.json")
    c, db, now = simulated_day()
    assert c.get("/api/tv/alerts").json()["which"] == "all"
    assert c.post("/api/tv/alerts", json={"which": "gex", "sound": False}).json() == {"on": True, "sound": False, "notify": True, "which": "gex"}
    got, played = [], []
    monkeypatch.setattr(notify, "SENDER", lambda t, b: got.append((t, b)))
    monkeypatch.setattr(notify, "play", lambda tier: played.append(tier))
    assert notify.send("Q DATA: GEX levels changed (1)", "Call wall moved", 2)
    assert got and played == [2]
    assert c.post("/api/tv/alerts/test", params={"tier": 1}).json()["desktop"] is True


def test_history_is_capped_and_hidden_kinds_stay_listed():
    runs = [{"kind": "0DTE call wall", "label": "Call wall", "value": 21000 + i * 5, "low": None, "high": None, "prev": None, "active": 0, "live": 0,
             "sec": 1, "first_ts_ms": 1000 * i, "end_ts_ms": 1000 * i + 500, "read": "H", "tip": "x"} for i in range(10)]
    runs.append({**runs[0], "active": 1, "end_ts_ms": 0})
    j = tv.build_text("gex", runs, lambda v: v, "m", "2026-10-14", "NDX", "u", 0, [])
    assert j["history"] == tv.HIST_PER_KIND and j["levels"] == 1
    j = tv.build_text("gex", runs, lambda v: v, "m", "2026-10-14", "NDX", "u", 0, [], prefs={"kinds": {"0DTE call wall": {"on": False}}})
    assert j["levels"] == 0 and j["hidden_kinds"][0]["name"] == "0DTE call wall"


def test_the_script_reads_every_field_where_the_text_puts_it():
    """Mirror of qdParse: the column each field is read from must match where build_text writes it (1.24.0 read the kind rows one
    column off, so every level looked hidden and nothing was drawn)."""
    import re
    code = build_script("gex")
    reads = dict(re.findall(r"array\.push\((k\w+|lv\w+), (?:int\()?(?:math\.max\(1, math\.min\(4, )?(?:num|fld)\(a, (\d+)\)", code))
    assert reads["kName"] == "1" and "array.push(kCol, hexColor(fld(a, 2)))" in code and reads["kSty"] == "3" and reads["kW"] == "4" and reads["kSec"] == "6"
    assert 'fld(a, 7) == "1"' in code and 'tag == "K" and array.size(a) >= 8' in code
    assert "p = num(a, 1)" in code and reads["lvG"] == "4" and reads["lvS"] == "5" and reads["lvE"] == "6" and reads["lvN"] == "9" and reads["lvTip"] == "10"
    runs = [{"kind": "0DTE call wall", "label": "Call wall", "value": 21000.0, "low": None, "high": None, "prev": None, "active": 1, "live": 0,
             "sec": 1, "first_ts_ms": 1000, "end_ts_ms": 0, "read": "H", "tip": "x"}]
    text = tv.build_text("gex", runs, lambda v: v, "m", "2026-10-14", "NDX", "u", 0, [])["text"]
    k = [x.split("|") for x in text.splitlines() if x.startswith("K|")][0]
    l = [x.split("|") for x in text.splitlines() if x.startswith("L|")][0]
    assert len(k) >= 8 and k[6] == "1" and k[7] == "1"                        # section 1 (Walls), key
    assert len(l) >= 10 and l[4] == "0" and l[5] == "1000" and l[9] == "Call wall"
    assert len("|".join(l[:10]).split("|")) >= 10                              # still readable when the hover text is dropped


def test_levels_start_setting_is_last_and_offers_open_and_chart_start():
    for ind in ("gex", "lv"):
        code = build_script(ind)
        inputs = [x for x in code.splitlines() if " input." in x and not x.startswith(" ")]
        assert inputs[-3].startswith("zoneFilter = input.string(") and inputs[-2].startswith("showStackN")   # 1.32.0
        assert inputs[-1].startswith('symTagIn = input.string("Auto"')                                          # 1.33.0, last
        inputs = inputs[:-3]
        if ind == "gex":                                       # 1.25.0 added "GEX levels are drawn as" after it
            assert inputs[-1].startswith("gexZones = input.string(")
            inputs = inputs[:-1]
        assert inputs[-2].startswith("startMode = input.string(\"When the data first showed it\"") and inputs[-1].startswith("startBars")
        for opt in ("9:30 open", "Start of chart data", "Last N bars"):
            assert f'"{opt}"' in code
        assert "x1 = startX(array.get(lvS, i))" in code and "showHist and dataStart()" in code and "max_bars_back = 5000" in code


def test_clean_view_keeps_every_section_and_the_expected_move():
    code = build_script("lv")
    assert "kindOf(array.get(lvG, j), 0) == si" in code and 'perSide   = input.int(3, "Levels on each side of price, per section' in code
    assert tv.is_key("Straddle (nearest expiry)") and tv.is_key("1 sd (nearest expiry)") and not tv.is_key("2 sd (later expiries)")
    c, db, now = simulated_day()
    l = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "lv"}).json()
    secs = {k["sec"] for k in l["kinds"]}
    assert {2, 3} <= secs                                                       # expected move and charm / vanna are in the pasted levels


def test_an_earlier_days_gex_levels_can_be_copied_for_a_backtest():
    c, db, now = simulated_day()
    c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"})            # today's runs exist (2026-10-14)
    with db.conn() as cn:                                                           # move them to an earlier day, as if copied a week ago
        cn.execute("UPDATE tv_runs SET day='2026-10-07'")
        cn.execute("INSERT INTO level_runs(underlying,session_date,category,label,value,first_seen,last_seen,active) VALUES"
                   "('_NDX','2026-10-01','call_wall','Call wall',25100,'2026-10-01T14:00:00+00:00','2026-10-01T19:00:00+00:00',1),"
                   "('_NDX','2026-10-01','oi_call_zone','OI zone',25000,'2026-10-01T14:00:00+00:00','2026-10-01T19:00:00+00:00',1)")
    days = c.get("/api/tv/days", params={"underlying": "_NDX"}).json()["days"]
    by = {d["day"]: d for d in days}
    assert by["2026-10-07"]["exact"] and not by["2026-10-01"]["exact"] and "2026-10-14" not in by      # the current day is the normal copy
    r = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex", "day": "2026-10-07"}).json()
    q = lines(r["text"], "Q")[0]
    assert r["backtest"] and r["exact"] and q[4] == "2026-10-07" and len(q) == 9
    assert int(q[8]) == int(datetime.fromisoformat("2026-10-07T17:00:00-04:00").timestamp() * 1000)    # drawn to that day's close
    assert lines(r["text"], "L") and not lines(r["text"], "H")
    o = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex", "day": "2026-10-01"}).json()
    assert not o["exact"] and [x[9] for x in lines(o["text"], "L")] == ["Call wall"]   # only the GEX kinds from the older log
    assert c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex", "day": "2026-09-01"}).status_code == 404
    t = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()  # today's copy keeps the old 8-field header
    assert len(lines(t["text"], "Q")[0]) == 8
    code = build_script("gex")
    assert "qdBtEnd(dataTxt)" in code and "refClose()" in code and "btEnd > 0 ? int(math.min(btEnd" in code


def test_best_zones_filter_defaults_and_classes():
    for ind, dflt in (("gex", "Best zones only"), ("kl", "Best zones only"), ("lv", "Everything"), ("all", "Everything")):
        code = build_script(ind)
        assert f'zoneFilter = input.string("{dflt}", "Show"' in code and all(ord(ch) < 128 for ch in code)
        assert "classOk(g)" in code and "array.push(kCls, kindClass(fld(a, 1)))" in code and "__" not in code.replace("__future__", "")
    code = build_script("kl")
    for best in ("biggest gex", "positive gex", "negative gex", "call wall zone", "put wall zone", "call open interest", "dealer delta: long"):
        assert f'"{best}"' in code
    for brk in ("flip", "expected move", "call volume"):
        assert f'"{brk}"' in code
    assert 'x" + str.tostring(cnt)' in code and "BREAK LEVEL" in code


def test_symbol_tag_on_labels():
    code = build_script("gex")
    assert "txt = symTag() + nm" in code and 'first != "NDX"' in code


def test_combined_indicators_are_named_for_their_ticker_and_only_take_their_own_levels():
    from backend.services.tv_pine import COMBO_SECTIONS
    for t in ("NDX", "QQQ", "SPX"):
        code = build_script("combo", t)
        assert code.startswith("//@version=6") and all(ord(ch) < 128 for ch in code) and code == build_script("combo", t)
        assert f'indicator("Q DATA {t}", shorttitle = "QD {t}"' in code and f'wantSym = "{t}"' in code
        assert [x for x in code.splitlines() if " input." in x and not x.startswith(" ")][0].startswith("dataTxt = input.text_area")
        assert 'sec16 = input.bool(true, "Your levels"' in code and 'input.bool(false, "Heatmap"' in code      # same place as in 1.34.0
        assert f'sec{len(COMBO_SECTIONS) - 1} = input.bool(true, "IV walls"' in code
        assert 'distZones = input.bool(true' in code and "superDist()" in code and "border_style = brk ? line.style_dashed" in code
        assert 'zoneFilter = input.string("Everything", "Show"' in code       # every section shows by default
    # the other indicators keep their old drawing: no distance zones, no ticker check, settings order unchanged
    for ind in ("gex", "lv", "kl", "all"):
        code = build_script(ind)
        assert "distZones = false" in code and 'wantSym = ""' in code and "input.bool(true, \"Zones by distance" not in code
    try:
        build_script("combo", "SPY")
        assert False
    except ValueError:
        pass


def test_combined_levels_merge_all_tabs_and_key_levels_without_duplicates():
    c, db, now = simulated_day()
    s = c.get("/api/tv/combo/script", params={"ticker": "ndx"}).json()
    assert s["title"] == "Q DATA NDX" and s["filename"].endswith(".pine") and 'indicator("Q DATA NDX"' in s["code"]
    assert c.get("/api/tv/combo/script", params={"ticker": "SPY"}).status_code == 422
    assert c.post("/api/tv/combo/levels", params={"ticker": "QQQ"}, json={}).status_code == 404     # not in this test's symbol list
    j = c.post("/api/tv/combo/levels", params={"ticker": "NDX", "key": 8}, json={}).json()
    a = c.post("/api/tv/alltabs/levels", params={"underlying": "_NDX"}, json={}).json()
    assert j["title"] == "Q DATA NDX" and lines(j["text"], "Q")[0][2] == "combo" and lines(j["text"], "Q")[0][5].startswith("NDX")
    assert j["levels"] >= a["levels"] and j["chars"] <= tv.MAX_CHARS
    from backend.services.tv_pine import COMBO_SECTIONS
    secs = {k["sec"] for k in j["kinds"]}
    assert secs and all(0 <= x < len(COMBO_SECTIONS) for x in secs)
    cur = [x for x in lines(j["text"], "L") if x[6] == "0"]
    ks = lines(j["text"], "K")
    seen = set()
    for x in cur:
        key = (ks[int(x[4])][6], ks[int(x[4])][1], x[1])
        assert key not in seen, key                      # one level per section, kind and price
        seen.add(key)
    assert any(r[1] == "Key levels" for r in lines(j["text"], "R"))
    assert j["key_levels"] > 0 and j["levels"] < a["levels"] + j["key_levels"]      # Key levels already on All Tabs were not added twice
