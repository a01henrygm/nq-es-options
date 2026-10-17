"""Market regime scorecard. SYNTHETIC test data only."""
from datetime import date, timedelta

import pytest

from backend.services import analytics as an
from backend.services.freshness import classify
from backend.services.regime import MIN_SESSIONS, compute_regime, daily_last, decide, percentile_of
from tests.conftest import NOW, make_chain
from tests.test_features import Snap, api_client


def d(key, lean, available=True, scored=True):
    return {"key": key, "name": key, "reading": "", "lean": lean, "why": "", "available": available, "scored": scored}


def test_labels_follow_the_visible_rule():
    assert decide([d("gamma", 2), d("vol", 1), d("term", 1)])["label"] == "Pinned and calm"                    # total +4
    assert decide([d("gamma", 2), d("vol", -1)])["label"] == "Calm"                                              # +1
    assert decide([d("gamma", 2), d("vol", -2)])["label"] == "Mixed"                                             # 0
    assert decide([d("gamma", -2), d("vol", 1)])["label"] == "Leaning unstable"                                  # -1
    assert decide([d("gamma", -2), d("vol", -1), d("term", -1)])["label"] == "Trending, expansion risk"          # -4
    assert decide([d("gamma", 0), d("vol", -2)], transition=True)["label"] == "Transition: near the gamma flip"
    assert decide([d("gamma", 0, available=False)])["label"] == "Unclear"
    assert decide([d("gamma", 2), d("vol", 1, available=False)])["total"] == 2                                   # unavailable measures add nothing
    assert decide([d("gamma", 2), d("x", 5, scored=False)])["total"] == 2                                        # info-only rows are not scored


def test_confidence_needs_several_measures_that_agree():
    full = decide([d("gamma", 2), d("vol", 1), d("term", 1), d("range", 1), d("skew", 0)])
    assert full["confidence"] == "High" and full["dimensions_agree"]
    one = decide([d("gamma", 2)])
    assert one["confidence"] == "Low" and one["dimensions_available"] == 1
    split = decide([d("gamma", 2), d("vol", -1), d("term", -1), d("range", 1), d("skew", 0)])
    assert not split["dimensions_agree"] and split["confidence"] != "High"


def test_percentile_needs_history_and_daily_last_uses_one_value_per_day():
    assert percentile_of(0.2, [0.1] * (MIN_SESSIONS - 1)) is None
    past = [0.1 + 0.01 * i for i in range(MIN_SESSIONS)]
    assert percentile_of(0.1, past) == pytest.approx(10.0) and percentile_of(10, past) == 100.0
    base = NOW.replace(hour=15)
    rows = [{"value": 1.0, "calculated_at": (base - timedelta(days=2, hours=1)).isoformat()}, {"value": 2.0, "calculated_at": (base - timedelta(days=2)).isoformat()},
            {"value": 3.0, "calculated_at": (base - timedelta(days=1)).isoformat()}, {"value": 9.0, "calculated_at": base.isoformat()}]
    assert daily_last(rows, base.astimezone(__import__("backend.timeutil", fromlist=["ET"]).ET).date()) == [2.0, 3.0]      # last of each day, today left out


def multi(iv0=0.20, step=0.01):
    cons = []
    for i, dd in enumerate((1, 3, 9, 16, 23)):
        cons += make_chain(spot=500.0, n_strikes=21, step=5.0, iv=iv0 + step * i, expiry=NOW.date() + timedelta(days=dd))
    return cons


def run(cons=None, hist=None, actual=None, events=None, group="Nasdaq 100", convention="standard"):
    snap = Snap(cons or multi())
    return compute_regime(snap, NOW, classify(NOW, NOW, "delayed"), convention, hist, actual, events, group, [])


def test_dimensions_term_shape_and_volatility_from_a_real_chain():
    contango = run(multi(0.20, 0.01))
    backward = run(multi(0.30, -0.02))
    by = lambda r: {x["key"]: x for x in r["dimensions"]}
    assert by(contango)["term"]["lean"] == 1 and "contango" in by(contango)["term"]["reading"]
    assert by(backward)["term"]["lean"] == -1 and "backwardation" in by(backward)["term"]["reading"]
    assert contango["iv"]["mid"] is not None and by(contango)["vol"]["available"]
    assert "rough fixed ranges" in by(contango)["vol"]["reading"]                                                 # no history yet: says so


def test_volatility_uses_the_stored_history_once_there_is_enough():
    cons = multi()
    mid = an.iv_points(cons, 500.0, NOW)["mid"]["atm_iv"]
    rows = lambda vals: [{"value": v, "calculated_at": (NOW - timedelta(days=i + 1)).isoformat()} for i, v in enumerate(vals)]
    cheap = run(cons, hist={"iv_mid": rows([mid * 1.5] * 12)})                                                   # today is far below its own history
    rich = run(cons, hist={"iv_mid": rows([mid * 0.6] * 12)})                                                    # today is far above it
    v = lambda r: next(x for x in r["dimensions"] if x["key"] == "vol")
    assert v(cheap)["lean"] == 1 and "low" in v(cheap)["reading"] and "12 sessions" in v(cheap)["reading"]
    assert v(rich)["lean"] == -2 and "high" in v(rich)["reading"]


def test_range_skew_and_event_dimensions():
    by = lambda r: {x["key"]: x for x in r["dimensions"]}
    calm = run(actual={"available": True, "fraction_of_expected": 0.2})
    wild = run(actual={"available": True, "fraction_of_expected": 1.4})
    assert by(calm)["range"]["lean"] == 1 and by(wild)["range"]["lean"] == -1 and not by(run())["range"]["available"]
    ev = run(events=[{"name": "FOMC rate decision", "time": "14:00", "importance": "high", "days_away": 0}])
    assert by(ev)["event"]["lean"] == -1 and ev["event_today_high"] and "FOMC" in by(ev)["event"]["reading"]
    assert by(run(events=[{"name": "CPI", "importance": "high", "days_away": 1}]))["event"]["lean"] == 0         # tomorrow does not count as today
    sk = an.skew_25d(multi(), 500.0, NOW)
    if sk:
        prev = [{"value": sk["value"] - 2.0, "calculated_at": (NOW - timedelta(days=1)).isoformat()}]
        assert by(run(hist={"skew_25d": prev}))["skew"]["lean"] == -1                                             # skew up 2 points since yesterday


def test_stale_data_caps_confidence_and_gross_scenario_has_no_gamma_direction():
    snap = Snap(multi())
    r = compute_regime(snap, NOW, classify(NOW - timedelta(days=3), NOW, "delayed"), "standard", {}, None, [], "S&P 500", [])
    assert r["confidence"] == "Low" and any("stale" in n for n in r["notes"])
    g = run(convention="gross")
    assert not next(x for x in g["dimensions"] if x["key"] == "gamma")["available"] and g["gamma"] is None


def test_regime_api_overview_and_collector_metric():
    c, db = api_client()
    j = c.get("/api/analytics/regime", params={"underlying": "_NDX"}).json()
    r = j["data"]
    assert r["label"] in ("Pinned and calm", "Calm", "Mixed", "Leaning unstable", "Trending, expansion risk", "Transition: near the gamma flip", "Unclear")
    assert {x["key"] for x in r["dimensions"]} == {"gamma", "vol", "term", "skew", "range", "event"} and "not backtested" in r["caution"] and r["meaning"]
    assert j["futures_root"] == "NQ" and j["futures_offset"] is None
    c.post("/api/basis", json={"root": "NQ", "basis": 250.0})
    assert c.get("/api/analytics/regime", params={"underlying": "_NDX"}).json()["futures_offset"] == 250.0
    assert c.get("/api/analytics/regime", params={"underlying": "_NDX", "convention": "nope"}).status_code == 422
    c.post("/api/events", json={"date": NOW.date().isoformat(), "time": "08:30", "name": "CPI inflation", "importance": "high"})
    assert c.get("/api/analytics/regime", params={"underlying": "_NDX"}).json()["data"]["event_today_high"]


def test_overview_cards_carry_the_regime_and_it_agrees_with_the_regime_tab():
    from tests.test_features import two_symbol_client
    c, _ = two_symbol_client()
    j = c.get("/api/analytics/bias-overview").json()
    for r in j["rows"]:
        if r.get("available"):
            tab = c.get("/api/analytics/regime", params={"underlying": r["underlying"]}).json()["data"]
            assert r["regime"] == {"label": tab["label"], "confidence": tab["confidence"], "total": tab["total"]}


def test_collector_stores_the_three_week_volatility_each_cycle():
    from backend.collector import Collector
    from backend.config import Settings
    from backend.database import Database
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    db = Database(":memory:")
    col = Collector(Settings(provider="cboe", underlyings=("_NDX",)), None, db, lambda: NOW)
    cons = multi()
    snap = ChainSnapshot("cboe", "_NDX", NOW, 500.0, NOW, cons, content_hash(cons)); snap.snapshot_id = 1
    db.save_snapshot(snap) if hasattr(db, "save_snapshot") else None
    col._store_metrics("_NDX", snap, NOW)
    rows = db.metric_history("_NDX", "iv_mid", 10)
    assert len(rows) == 1 and 0.05 < rows[0]["value"] < 1.0


def test_split_between_total_gamma_and_the_flip_is_called_out_and_caps_confidence():
    r = run(multi(0.20, 0.01))
    g = r["gamma"]
    note = next(n for n in r["notes"] if n.startswith("Total modeled GEX"))
    assert ("split" in note) == (r["gamma"] is not None and "split" in note)
    if "split" in note:
        assert r["confidence"] in ("Medium", "Low") and "Medium confidence at most" in note
    else:
        assert "agrees" in note or g is None or abs(g["distance_pct"]) < 0.25
    # forced case: total gamma and the flip disagree
    import backend.services.regime as rg
    orig = rg.an.gex_by_strike
    try:
        rg.an.gex_by_strike = lambda *a, **k: {"total_net_gex": -1.0 if (g and g["calm_side"]) else 1.0}
        forced = run(multi(0.20, 0.01))
    finally:
        rg.an.gex_by_strike = orig
    if g and abs(g["distance_pct"]) >= 0.25:
        assert any("signals split" in n for n in forced["notes"]) and forced["confidence"] != "High"
