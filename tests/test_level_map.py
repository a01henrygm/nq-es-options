"""Level map: candles from stored prices, the respect / chop / disrespect calls and the projected path. TEST DATA ONLY."""
from datetime import datetime, timedelta

from backend.services import behavior as bh
from backend.timeutil import ET
from tests.test_session_features import simulated_day


def test_candles_bucket_prices_and_open_at_the_previous_close():
    t0 = datetime(2026, 10, 14, 9, 30, tzinfo=ET)
    rows = [(t0 - timedelta(minutes=5), 99.0)] + [(t0 + timedelta(minutes=i), p) for i, p in enumerate([100, 102, 101, 104, 103, 99])]
    c = bh.candles(rows, t0, 2)
    assert [x["t"] for x in c] == [t0, t0 + timedelta(minutes=2), t0 + timedelta(minutes=4)]
    assert c[0] == {"t": t0, "o": 99.0, "h": 102, "l": 99.0, "c": 102, "n": 2}
    assert c[1]["o"] == 102 and c[1]["h"] == 104 and c[1]["c"] == 104 and c[2]["o"] == 104 and c[2]["l"] == 99


def _call(state, g, cats=("gex_concentration",), value=1010.0, flips=()):
    strikes = [{"strike": value, "net_gex": g}, {"strike": 1100.0, "net_gex": 1e9}]
    return bh.call_for({"value": value, "category": cats[0], "members": list(cats)}, state, 1000.0, list(flips), strikes, 1e9)[0]


def test_calls_follow_regime_and_dealer_gamma():
    assert _call("long", 8e8) == "RESPECT" and _call("long", -8e8) == "DISRESPECT"
    assert _call("short", -8e8) == "DISRESPECT" and _call("short", 8e8) == "CHOP"
    assert _call("long", 8e8, flips=(1011.0,)) == "CHOP" and _call("short", 0, cats=("gex0_flip",)) == "CHOP"
    assert _call("long", 0, cats=("expected_move",)) == "RESPECT" and _call("short", 0, cats=("expected_move",)) == "DISRESPECT"
    assert _call("long", 1e6) == "RESPECT" and _call("short", 1e6) == "DISRESPECT"          # little gamma: the regime default


def test_projected_path_acts_out_each_call():
    up = {"label": "wall", "value": 1010.0, "call": "RESPECT"}
    dn = {"label": "pocket", "value": 990.0, "call": "DISRESPECT"}
    p = bh.ghost_path([up, dn], 1000.0, 3.0, 40, 1)
    calls = [(e["value"], e["call"]) for e in p["events"]]
    assert calls[0] == (1010.0, "RESPECT") and calls[1] == (990.0, "DISRESPECT")
    i = p["events"][0]["i"]
    bar = p["candles"][i]
    assert bar["h"] > 1010.0 > bar["c"]                                                  # wick through, close back under
    j = p["events"][1]["i"]
    assert p["candles"][j]["c"] < 990.0 and min(c["c"] for c in p["candles"][j:]) < 990.0  # closes through and keeps going
    alt = bh.ghost_path([up, dn], 1000.0, 3.0, 40, 1, flip_first=True)
    assert alt["events"][0]["call"] == "DISRESPECT" and alt["candles"][alt["events"][0]["i"]]["c"] > 1010.0


def test_chop_swings_both_sides_before_resolving():
    lv = [{"label": "flip", "value": 1006.0, "call": "CHOP"}]
    p = bh.ghost_path(lv, 1000.0, 3.0, 20, 1)
    i = p["events"][0]["i"]
    swing = p["candles"][i + 1:i + 5]
    assert any(c["c"] > 1006 for c in swing) and any(c["c"] < 1006 for c in swing)


def test_level_map_lists_every_level_with_a_plan():
    c, db, now = simulated_day()
    j = c.get("/api/charts/level-map", params={"underlying": "_NDX"}).json()
    lv = j["levels"]
    assert "candles" not in j and len(lv) >= 10 and [l["value"] for l in lv] == sorted((l["value"] for l in lv), reverse=True)
    assert sum(j["counts"].values()) == len(lv)
    for l in lv:
        assert l["call"] in bh.CALLS and l["headline"] and l["plan"] and l["futures"] is not None
        assert l["chance"] is None or 0 <= l["chance"] <= 1
    up = [l for l in lv if l["value"] > j["spot"]]
    assert all(l["points"] > 0 for l in up) and up[-1]["order"] == 1                       # the nearest level above is first in line
    assert c.get("/api/charts/level-map", params={"underlying": "_NDX", "count": 2}).status_code == 422


def test_predictions_read_the_right_way():
    a = {"label": "Call wall", "value": 1010.0, "call": "RESPECT"}
    b = {"label": "Move zone", "value": 1020.0, "call": "DISRESPECT"}
    d = {"label": "Put wall", "value": 990.0, "call": "RESPECT"}
    p = bh.prediction(a, "above", b, d, "long", 0.4)
    assert p["headline"] == "Should hold as resistance" and "Put wall (990)" in p["plan"] and "Move zone (1,020)" in p["plan"]
    q = bh.prediction(b, "above", None, a, "long", 0.1)
    assert q["headline"] == "Should break" and "slow down" in q["plan"]
    assert bh.prediction(d, "below", None, a, "short", 0.3)["headline"] == "Should hold as support"


def test_history_day_explains_the_session():
    c, db, now = simulated_day()
    j = c.get("/api/history/day", params={"underlying": "_NDX"}).json()
    assert j["available"] and j["day"] == "2026-10-14" and "2026-10-13" in j["days"]
    sm = j["summary"]
    assert sm["open"] == 30000.0 and sm["high"] >= sm["close"] >= sm["low"] and "expected move" in sm["verdict"]
    tc = j["touch_counts"]
    assert tc["levels"] > 0 and tc["held"] + tc["broke"] <= len(j["touches"]) and all(t["result"] in ("held", "broke", "not measured") for t in j["touches"])
    assert len(j["metric"]["options"]) == 6 and j["metric"]["daily"] and j["lines"]["gamma_flip"]
    old = c.get("/api/history/day", params={"underlying": "_NDX", "date": "2026-10-13", "metric": "gamma_flip"}).json()
    assert old["day"] == "2026-10-13" and old["summary"]["rth_observations"] == 1           # one stored price at 15:50 that day
    assert c.get("/api/history/day", params={"underlying": "_NDX", "metric": "nope"}).status_code == 422
