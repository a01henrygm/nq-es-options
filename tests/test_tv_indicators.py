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
    for x in lines(g["text"], "L") + lines(l["text"], "L"):
        assert int(x[5]) == data_ms and x[6] == "0" and x[7] in ("H", "C", "B", "-")   # first sighting = this snapshot's data time
    assert g["levels"] > 0 and l["levels"] > 0 and g["chars"] < tv.MAX_CHARS
    assert all(k["color"].startswith("#") for k in g["kinds"] + l["kinds"])


def test_a_moved_level_ends_its_run_and_the_move_is_an_event():
    c, db, now = simulated_day()
    c.post("/api/tv/track", params={"underlying": "_NDX"})
    first = c.get("/api/tv/log", params={"underlying": "_NDX"}).json()["events"]
    assert [e["action"] for e in first] == ["session"]
    assert c.post("/api/tv/track", params={"underlying": "_NDX", "force": True}).json()["events"] == []    # same data, nothing changed
    with db.conn() as cn:                                     # pretend the 0DTE call wall was one strike lower in the earlier data
        r = cn.execute("SELECT id, value FROM tv_runs WHERE kind='0DTE call wall' AND active=1").fetchone()
        cn.execute("UPDATE tv_runs SET value=?, first_ts='2026-10-14T18:00:00+00:00' WHERE id=?", (r["value"] - 25, r["id"]))
    ev = c.post("/api/tv/track", params={"underlying": "_NDX", "force": True}).json()["events"]
    mv = [e for e in ev if e["action"] == "moved"]
    assert len(mv) == 1 and mv[0]["tier"] == 2 and "moved" in mv[0]["text"] and mv[0]["old"] == r["value"] - 25
    g = c.get("/api/tv/levels", params={"underlying": "_NDX", "ind": "gex"}).json()
    hist = [x for x in lines(g["text"], "L") if x[6] != "0"]
    assert g["history"] == 1 and len(hist) == 1 and int(hist[0][5]) < int(hist[0][6])                     # faded old piece: start < end
    cur = [x for x in lines(g["text"], "L") if x[6] == "0" and float(x[8]) > 0]
    assert len(cur) == 1                                                                                   # the new piece knows where it came from
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
