"""Game plan: trades from the calls, the team vote, grades, and the card log. TEST DATA ONLY."""
from datetime import datetime, timedelta

from backend.services import gameplan as gp
from backend.timeutil import UTC
from tests.test_session_features import simulated_day


def cand(price, call, low=None, high=None, kinds=4):
    return {"price": price, "low": low or price, "high": high or price, "call": call, "kinds": kinds, "label": "x"}


def test_trades_follow_the_call_and_side():
    t = gp.trade_for(cand(1010.0, "RESPECT", 1008.0, 1012.0), 1000.0, 50.0, [990.0, 1010.0, 1030.0])
    assert (t["side"], t["kind"], t["entry"], t["stop"], t["target"]) == ("SHORT", "fade", 1010.0, 1016.0, 990.0) and abs(t["r"] - 20 / 6) < 1e-9
    b = gp.trade_for(cand(990.0, "DISRESPECT", 988.0, 992.0), 1000.0, 50.0, [970.0, 990.0, 1010.0])
    assert b["side"] == "SHORT" and b["kind"] == "break" and b["entry"] < 990.0 < b["stop"] and b["target"] == 970.0
    near = gp.trade_for(cand(1010.0, "RESPECT"), 1000.0, 50.0, [1009.0, 1010.0])           # nothing far enough: 2 R
    assert near["r"] == 2.0 and near["target"] == near["entry"] - 2 * near["stop_dist"]
    assert gp.trade_for(cand(1010.0, "CHOP"), 1000.0, 50.0, []) is None


def test_votes_and_grades():
    t = {"side": "SHORT", "kind": "fade"}
    ctx = {"state": "long", "already_in": {"high": 0.8, "low": 0.2}, "mr": {"available": True, "significant": True, "lean": "range", "verdict": "Mean-reverting: x", "t_stat": -3.5},
           "pca": {"available": True, "correlation": 0.9, "residual_z": -1.5}, "drift": 2e9, "record": {"held_pct": 0.7, "n": 20}, "chance": 0.4, "ev_r": 0.3, "p_win": 0.35}
    v = gp.votes_for(t, cand(1010.0, "RESPECT"), ctx)
    assert all(x[1] is True for x in v) and len(v) == 9 and gp.grade(v)[0] == "A"
    long_ = gp.votes_for({"side": "LONG", "kind": "fade"}, cand(990.0, "RESPECT"), ctx)
    names = {n: x for n, x, _ in long_}
    assert names["Timekeeper"] is False and names["Clock"] is False and names["2nd opinion"] is False
    assert gp.grade([("a", True, ""), ("b", False, ""), ("c", False, "")])[0] == "No trade"
    assert gp.grade([("a", True, "")] * 4 + [("b", False, "")] * 2)[0] == "B"


def test_outcome_needs_a_fill_then_target_or_stop():
    t0 = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    card = {"side": "SHORT", "kind": "fade", "entry": 1010.0, "stop": 1016.0, "target": 990.0}
    path = lambda ps: [(t0 + timedelta(minutes=i), p) for i, p in enumerate(ps)]
    assert gp.outcome(card, path([1000, 1005, 1008])) == "not filled"
    assert gp.outcome(card, path([1005, 1010.5, 1000, 989])) == "target"
    assert gp.outcome(card, path([1005, 1011, 1017])) == "stop"
    assert gp.outcome(card, path([1005, 1011, 1003])) == "open"


def test_game_plan_endpoint_logs_and_grades_cards():
    c, db, now = simulated_day()
    j = c.get("/api/analytics/game-plan", params={"underlying": "_NDX"}).json()
    assert j["available"] and 1 <= len(j["cards"]) <= 3
    for cd in j["cards"]:
        assert cd["grade"] in ("A", "B", "C") and cd["yes"] > cd["no"] and cd["f"]["entry"] and len(cd["votes"]) >= 6
        assert (cd["stop"] - cd["entry"]) * (1 if cd["side"] == "SHORT" else -1) > 0 and (cd["target"] - cd["entry"]) * (1 if cd["side"] == "LONG" else -1) > 0
    order = {"A": 0, "B": 1, "C": 2}
    assert [order[x["grade"]] for x in j["cards"]] == sorted(order[x["grade"]] for x in j["cards"])
    j2 = c.get("/api/analytics/game-plan", params={"underlying": "_NDX"}).json()
    assert j2["record"]["cards"] == len(j["cards"])                                       # logged once per half hour, not on every refresh
