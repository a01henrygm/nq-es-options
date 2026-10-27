"""Volatility tab, Earnings tab and Session replay (1.15). Quote and API shapes are copied from the live files read on 2026-10-26."""
import json
import math
from datetime import date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings
from backend.database import Database
from backend.extras import Extras
from backend.models import OptionContract
from backend.providers.cboe import CboeProvider
from backend.services import earnings as ea
from backend.services import replay as rp
from backend.services import volatility as vol
from backend.timeutil import UTC

NIGHT = datetime(2026, 10, 27, 1, 13, tzinfo=UTC)            # 9:13 PM ET Monday


def quote(sym, price, change, pdc=None, t="2026-10-26T16:15:01", **kw):
    return {"timestamp": "2026-10-27 01:13:15", "data": {"symbol": "^" + sym.lstrip("_"), "current_price": price, "price_change": change,
            "prev_day_close": price if pdc is None else pdc, "close": price, "open": price, "high": price, "low": price,
            "last_trade_time": t, "iv30": kw.get("iv30", 0.0)}}


LIVE = {"_VIX1D": quote("_VIX1D", 10.49, -6.32), "_VIX9D": quote("_VIX9D", 17.92, -0.78), "_VIX": quote("_VIX", 18.39, -1.06, iv30=92.631),
        "_VIX3M": quote("_VIX3M", 19.94, -0.54), "_VIX6M": quote("_VIX6M", 21.63, -0.33), "_VVIX": quote("_VVIX", 101.43, -8.27),
        "_VXN": quote("_VXN", 26.4, 0.0, t="2026-10-26T15:15:01.253000-05:00")}


# ---- volatility ------------------------------------------------------------------------------------------------------------

def test_after_close_change_comes_from_price_change_not_prev_close():
    q = vol.parse_quote(LIVE["_VIX"])
    assert q["value"] == 18.39 and q["prev"] == pytest.approx(19.45) and q["change"] == pytest.approx(-1.06) and q["iv30"] == pytest.approx(92.631)
    during = vol.parse_quote(quote("_VIX", 18.39, -1.06, pdc=19.45))
    assert during["prev"] == 19.45


def test_vxn_has_no_change_in_its_file_and_an_offset_time():
    q = vol.parse_quote(LIVE["_VXN"])
    assert q["change"] is None and q["time"] == datetime(2026, 10, 26, 20, 15, 1, 253000, tzinfo=UTC)


def test_history_csv_layouts():
    a = vol.parse_history_csv("DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2025,17.0,18.0,16.0,17.5\n01/03/2025,17.5,17.9,16.1,16.2\n")
    assert a == [(date(2025, 1, 2), 17.5), (date(2025, 1, 3), 16.2)]
    b = vol.parse_history_csv("DATE,VVIX\n2025-01-02,95.1\nbad,row\n2025-01-03,97.0\n")
    assert b == [(date(2025, 1, 2), 95.1), (date(2025, 1, 3), 97.0)]
    assert vol.parse_history_csv("") == [] and vol.parse_history_csv("DATE,CLOSE\n") == []


def test_analyze_live_evening():
    qs = {k: vol.parse_quote(j) for k, j in LIVE.items()}
    days = [date(2025, 10, 27) + timedelta(days=i) for i in range(400) if (date(2025, 10, 27) + timedelta(days=i)).weekday() < 5][:260]
    hist = {"VXN": [(d, 22 + (i % 10)) for i, d in enumerate(days)] + [(date(2026, 10, 23), 26.9)],
            "VIX": [(d, 14 + (i % 12)) for i, d in enumerate(days)]}
    a = vol.analyze(qs, hist, ndx=29273.4, spx=7676.77, nq_ratio=1.0103, es_ratio=1.0063, now=NIGHT)
    assert a["regime"]["label"] == "Normal"                                    # VIX/VIX3M = 0.92
    assert a["ratios"]["vix_vix3m"] == pytest.approx(18.39 / 19.94)
    vxn = next(r for r in a["rows"] if r["name"] == "VXN")
    assert vxn["change"] == pytest.approx(26.4 - 26.9)                         # from the history, since the file says 0
    assert 0 <= next(r for r in a["rows"] if r["name"] == "VIX")["pct_1y"] <= 1
    nq = a["moves"]["nq_day"]
    assert nq["index_points"] == pytest.approx(29273.4 * 0.264 / math.sqrt(252)) and nq["futures_points"] == pytest.approx(nq["index_points"] * 1.0103)
    assert a["moves"]["nq_today"]["index_points"] == pytest.approx(nq["index_points"] * 10.49 / 18.39)
    assert any("priced quiet" in f["text"] for f in a["flags"])                # VIX1D / VIX = 0.57
    assert a["curve"]["shape"] == "upward (contango)" and len(a["curve"]["today"]) == 5


@pytest.mark.parametrize("r,vix,label", [(0.80, 13, "Calm"), (0.90, 17, "Normal"), (0.97, 22, "Tense"), (1.03, 28, "Stressed"), (1.15, 38, "Panic"),
                                         (1.15, 25, "Stressed"), (None, 20, "Unknown")])
def test_regime_rules(r, vix, label):
    assert vol.regime(r, vix, None, None)[0] == label


# ---- earnings --------------------------------------------------------------------------------------------------------------

def members():
    caps = {"AAPL": 5019, "NVDA": 4900, "MSFT": 3900, "AMZN": 2675, "GOOGL": 1500, "GOOG": 1450, "META": 1800, "AVGO": 1600, "TSLA": 1200}
    rows = [{"symbol": s, "companyName": s + " Inc. Common Stock", "marketCap": f"{c * 1e9:,.0f}", "lastSalePrice": "$100.00"} for s, c in caps.items()]
    rows += [{"symbol": f"S{i:02d}", "companyName": "Other", "marketCap": f"{(150 - i) * 1e9:,.0f}", "lastSalePrice": "$50"} for i in range(92)]
    return rows


def test_ndx_weights_apply_the_capping_rule_and_merge_share_classes():
    w = ea.ndx_weights(members())
    assert "GOOG" not in w and w["GOOGL"]["raw_weight"] > 0.04                    # GOOG folded into GOOGL
    assert sum(x["weight"] for x in w.values()) == pytest.approx(1.0)
    big = sum(x["weight"] for x in w.values() if x["weight"] > ea.BIG)
    raw_big = sum(x["raw_weight"] for x in w.values() if x["raw_weight"] > ea.BIG)
    assert raw_big > 0.48 and big <= 0.48 + 1e-6                               # the giants were scaled down
    assert w["AAPL"]["weight"] < w["AAPL"]["raw_weight"] and max(x["weight"] for x in w.values()) < 0.24


def test_report_date_and_calendar_parsing_from_live_shapes():
    nv = {"data": {"announcement": "Earnings announcement* for NVDA: Nov 18, 2026",
                   "reportText": "NVIDIA Corporation Common Stock is estimated to report earnings on  11/18/2026. The upcoming earnings date is derived from an algorithm"}}
    assert ea.parse_report_date(nv) == {"date": date(2026, 11, 18), "estimated": True}
    assert ea.parse_report_date({"data": {"announcement": "Earnings announcement* for MSFT: Oct 28, 2026", "reportText": "Microsoft will report on 10/28/2026."}}) \
        == {"date": date(2026, 10, 28), "estimated": False}
    assert ea.parse_report_date({"data": {}}) is None
    cal = {"data": {"rows": [{"symbol": "AMZN", "time": "time-after-hours"}, {"symbol": "XOM", "time": "time-pre-market"}, {"symbol": "ZZ", "time": "time-not-supplied"}]}}
    assert ea.parse_calendar(cal) == {"AMZN": "after_close", "XOM": "before_open", "ZZ": "unknown"}


def test_reaction_day():
    assert ea.reaction_day(date(2026, 11, 18), "after_close") == date(2026, 11, 19)
    assert ea.reaction_day(date(2026, 10, 30), "before_open") == date(2026, 10, 30)          # a Friday morning report trades that day
    assert ea.reaction_day(date(2026, 10, 30), "after_close") == date(2026, 11, 2)            # Friday night -> Monday
    assert ea.reaction_day(date(2026, 11, 25), "unknown") == date(2026, 11, 27)               # skips Thanksgiving


def _bs(S, K, T, s, right):
    d1 = (math.log(S / K) + 0.5 * s * s * T) / (s * math.sqrt(T)); d2 = d1 - s * math.sqrt(T)
    N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
    return S * N(d1) - K * N(d2) if right == "C" else K * N(-d2) - S * N(-d1)


def chain(now, spot, event_expiry, base_iv, event_move):
    """Synthetic chain: ordinary vol base_iv, plus one event of size event_move (1 sd) inside every expiry on/after event_expiry."""
    out = []
    for e in (date(2026, 11, 13), date(2026, 11, 20), date(2026, 11, 27)):
        T = (datetime(e.year, e.month, e.day, 21, tzinfo=UTC) - now).total_seconds() / (365.25 * 86400)
        iv = math.sqrt(base_iv ** 2 + (event_move ** 2 / T if e >= event_expiry else 0))
        for K in (205, 210, 215, 217.5, 220, 225):
            for r in "CP":
                p = _bs(spot, K, T, iv, r)
                out.append(OptionContract(ticker=f"NVDA{e:%y%m%d}{r}{int(K * 1000):08d}", right=r, strike=K, expiry=e, bid=p * 0.995, ask=p * 1.005, iv=iv, oi=100))
    return out


def test_implied_move_recovers_the_event():
    now = datetime(2026, 11, 10, 20, tzinfo=UTC)
    m = ea.implied_move(chain(now, 216.5, date(2026, 11, 20), 0.40, 0.07), 216.5, date(2026, 11, 19), now)
    assert m["available"] and m["expiry"] == "2026-11-20" and m["base_expiry"] == "2026-11-13"
    assert m["event_sd_pct"] == pytest.approx(0.07, rel=0.08)                  # the 7% event comes back out
    assert 0.07 < m["straddle_pct"] < 0.10 and m["headline_pct"] == m["straddle_pct"]
    assert not ea.implied_move(chain(now, 216.5, date(2026, 11, 20), 0.4, 0.07), 216.5, date(2026, 12, 30), now)["available"]


def test_table_converts_to_nq_points_and_adds_same_night_reports():
    w = ea.ndx_weights(members())
    today = date(2026, 10, 26)
    reps = {"MSFT": {"date": date(2026, 10, 28), "estimated": False}, "META": {"date": date(2026, 10, 28), "estimated": False},
            "NVDA": {"date": date(2026, 11, 18), "estimated": True}, "AAPL": {"date": date(2027, 1, 28), "estimated": True}}
    mv = {"MSFT": {"available": True, "headline_pct": 0.05}, "META": {"available": True, "headline_pct": 0.08}, "NVDA": {"available": True, "headline_pct": 0.07}}
    t = ea.build_table(["AAPL", "NVDA", "MSFT", "META"], w, reps, {"MSFT": "after_close", "META": "after_close"}, mv, 29500.0, today, 45, {"NVDA": 0.09})
    up = {r["symbol"]: r for r in t["upcoming"]}
    assert set(up) == {"MSFT", "META", "NVDA"} and [r["symbol"] for r in t["later"]] == ["AAPL"]
    assert up["MSFT"]["nq_points"] == pytest.approx(w["MSFT"]["weight"] * 0.05 * 29500)
    assert up["NVDA"]["weight"] == 0.09 and up["NVDA"]["weight_source"] == "yours" and up["NVDA"]["nq_points"] == pytest.approx(0.09 * 0.07 * 29500)
    c = t["clusters"][0]
    assert c["reaction_day"] == "2026-10-29" and set(c["symbols"]) == {"MSFT", "META"}
    assert c["nq_points"] == pytest.approx(math.hypot(up["MSFT"]["nq_points"], up["META"]["nq_points"]))


# ---- replay ----------------------------------------------------------------------------------------------------------------

def _t(m):
    return (datetime(2026, 10, 26, 14, 0, tzinfo=UTC) + timedelta(minutes=m)).isoformat()


def test_replay_frames_and_events():
    prof = [{"t": _t(2 * i + 1), "detail": [[29000, -50e6 - i * 1e6, 10e6, -60e6], [29500, 80e6 + i * 4e6, 90e6, -10e6]]} for i in range(6)]
    price = [{"t": _t(2 * i), "price": p} for i, p in enumerate([29420, 29440, 29460, 29490, 29505, 29480])]
    lines = {"gamma_flip": [{"t": _t(0), "value": 29450}], "call_wall": [{"t": _t(0), "value": 29500}, {"t": _t(8), "value": 29600}],
             "put_wall": [{"t": _t(0), "value": 29000}], "gamma_at_spot": [{"t": _t(0), "value": -1e6}, {"t": _t(6), "value": 2e6}]}
    out = rp.build_frames(prof, price, lines)
    f = out["frames"]
    assert len(f) == 6 and f[0]["price"] == 29420 and f[2]["price"] == 29460
    kinds = [(e["i"], e["kind"]) for e in out["events"]]
    assert (2, "cross") in kinds                                              # 29440 -> 29460 crosses the 29450 flip
    assert (3, "regime") in kinds and (4, "wall") in kinds                    # dealer gamma turned positive; call wall 29500 -> 29600
    assert any(k == "touch" for _, k in kinds)                                # 29490 -> 29500 reached the wall
    assert f[1]["biggest_changes"][0]["strike"] == 29500 and f[1]["biggest_changes"][0]["change"] == pytest.approx(4e6)
    assert out["strikes"] == [29000, 29500]


def test_replay_thinning_keeps_event_frames():
    prof = [{"t": _t(i), "detail": [[100, float(i), 0, 0]]} for i in range(900)]
    lines = {"call_wall": [{"t": _t(0), "value": 1}, {"t": _t(777), "value": 2}]}
    out = rp.build_frames(prof, [{"t": _t(0), "price": 1.5}], lines, max_frames=100)
    assert len(out["frames"]) <= 110 and any(e["text"].startswith("Call wall moved") for e in out["events"])
    ev = out["events"][0]
    assert out["frames"][ev["i"]]["t"] == _t(777)


# ---- feed + API end to end -------------------------------------------------------------------------------------------------

def nasdaq_list():
    return {"data": {"date": "Oct 26, 2026", "data": {"rows": members()}}}


def nvda_chain(now):
    opts = []
    for c in chain(now, 216.5, date(2026, 11, 20), 0.40, 0.07):
        opts.append({"option": c.ticker, "bid": round(c.bid, 2), "ask": round(c.ask, 2), "iv": c.iv, "open_interest": 100, "volume": 5, "delta": 0.5, "gamma": 0.01})
    return {"timestamp": "2026-11-10 20:00:00", "data": {"current_price": 216.5, "last_trade_time": "2026-11-10T14:59:00", "options": opts}}


def router(now, fail=()):
    def h(req):
        u = str(req.url)
        if any(f in u for f in fail):
            return httpx.Response(503)
        if "/quotes/" in u:
            k = u.rsplit("/", 1)[1].replace(".json", "")
            return httpx.Response(200, json=LIVE[k]) if k in LIVE else httpx.Response(404)
        if "daily_prices" in u:
            return httpx.Response(200, text="DATE,OPEN,HIGH,LOW,CLOSE\n" + "".join(f"{(date(2025, 1, 1) + timedelta(days=i)):%m/%d/%Y},1,1,1,{15 + i % 9}\n" for i in range(300)))
        if "list-type/nasdaq100" in u:
            return httpx.Response(200, json=nasdaq_list())
        if "/analyst/" in u:
            s = u.split("/analyst/")[1].split("/")[0]
            d = "Nov 18, 2026" if s == "NVDA" else "Jan 28, 2027"
            return httpx.Response(200, json={"data": {"announcement": f"Earnings announcement* for {s}: {d}", "reportText": "estimated by an algorithm"}})
        if "calendar/earnings" in u:
            return httpx.Response(200, json={"data": {"rows": [{"symbol": "NVDA", "time": "time-after-hours"}]}})
        if "/options/NVDA.json" in u:
            return httpx.Response(200, json=nvda_chain(now))
        return httpx.Response(404)
    return h


def test_feed_end_to_end_and_survives_restart():
    now = datetime(2026, 11, 10, 20, tzinfo=UTC)
    s = Settings(provider="cboe", underlyings=("_NDX",), earnings_names=5)
    db = Database(":memory:")
    x = Extras(s, db, httpx.Client(transport=httpx.MockTransport(router(now))), clock=lambda: now)
    x.run_due()
    assert all(v["last_ok"] for v in x.status.values()), x.status
    assert x.reports["NVDA"]["date"] == date(2026, 11, 18) and x.timings["NVDA"] == "after_close"
    assert x.moves["NVDA"]["available"] and x.moves["NVDA"]["reaction_day"] == "2026-11-19"
    assert len(db.price_history("_VIX", 10)) == 1
    x.run_due()                                                                # nothing due yet: no duplicate rows
    assert len(db.price_history("_VIX", 10)) == 1

    app = create_app(s, db, Collector(s, CboeProvider(s), db), lambda: now, extras=x)
    c = TestClient(app)
    v = c.get("/api/volatility").json()
    assert v["available"] and v["regime"]["label"] == "Normal" and len(v["history"]["VIX"]) == 252
    e = c.get("/api/earnings").json()
    nv = next(r for r in e["upcoming"] if r["symbol"] == "NVDA")
    assert nv["timing"] == "after_close" and nv["move_pct"] > 0.06 and nv["nq_points"] is None     # no NDX snapshot in this test, so no NQ price
    assert c.post("/api/earnings/weights", json={"weights": {"nvda": 8.5}}).json()["overrides"] == {"NVDA": 0.085}
    assert next(r for r in c.get("/api/earnings").json()["upcoming"] if r["symbol"] == "NVDA")["weight"] == 0.085
    assert c.post("/api/earnings/weights", json={"weights": {"NVDA": 99}}).status_code == 422

    y = Extras(s, db, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))), clock=lambda: now)
    assert y.quotes["_VIX"]["value"] == 18.39 and y.moves["NVDA"]["available"] and y.reports["NVDA"]["estimated"]   # reloaded from the database


def test_feed_failures_are_reported_per_job_and_do_not_stop_others():
    now = datetime(2026, 11, 10, 20, tzinfo=UTC)
    s = Settings(provider="cboe", underlyings=("_NDX",), earnings_names=5)
    x = Extras(s, Database(":memory:"), httpx.Client(transport=httpx.MockTransport(router(now, fail=("nasdaq.com",)))), clock=lambda: now)
    x.run_due()
    assert x.status["vol"]["last_ok"] and x.status["history"]["last_ok"]
    assert x.status["members"]["last_error"] and "503" in x.status["members"]["last_error"]["message"]
    c = TestClient(create_app(s, x.db, Collector(s, CboeProvider(s), x.db), lambda: now, extras=x))
    assert c.get("/api/volatility").json()["available"]
    e = c.get("/api/earnings").json()
    assert not e["available"] and "member list" in e["reason"]


def test_extras_off():
    s = Settings(provider="cboe", underlyings=("_NDX",), extras_enabled=False)
    db = Database(":memory:")
    x = Extras(s, db, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    x.start()
    assert x._thread is None
    c = TestClient(create_app(s, db, Collector(s, CboeProvider(s), db), extras=x))
    assert "MARKET_EXTRAS=0" in c.get("/api/volatility").json()["reason"]


def test_replay_endpoint_from_stored_session():
    s = Settings(provider="cboe", underlyings=("_NDX",))
    db = Database(":memory:")
    now = datetime(2026, 10, 26, 20, 30, tzinfo=UTC)
    for i in range(5):
        t = datetime(2026, 10, 26, 14, 0, tzinfo=UTC) + timedelta(minutes=2 * i)
        db.save_price("_NDX", 29400 + 30 * i, "cboe", t, t)
        db.save_metric(None, "_NDX", "gex_profile", 1.0, [[29400, 1e6 * i, 1e6, 0], [29500, 5e6, 5e6, 0]], t + timedelta(seconds=30))
        db.save_metric(None, "_NDX", "gamma_flip", 29450, None, t + timedelta(seconds=30))
        db.save_metric(None, "_NDX", "call_wall", 29500 if i < 3 else 29600, None, t + timedelta(seconds=30))
    c = TestClient(create_app(s, db, Collector(s, CboeProvider(s), db), lambda: now))
    j = c.get("/api/charts/replay", params={"underlying": "_NDX"}).json()
    assert j["available"] and j["day"] == "2026-10-26" and len(j["frames"]) == 5
    assert any(e["kind"] == "cross" for e in j["events"]) and any(e["kind"] == "wall" for e in j["events"])
    assert not c.get("/api/charts/replay", params={"underlying": "_NDX", "scope": "0dte"}).json()["available"]
    assert c.get("/api/charts/replay", params={"underlying": "_NDX", "scope": "x"}).status_code == 422
    empty = TestClient(create_app(s, Database(":memory:"), Collector(s, CboeProvider(s), db), lambda: now))
    assert not empty.get("/api/charts/replay", params={"underlying": "_NDX"}).json()["available"]


def test_replay_reports_a_slow_flip_drift_once_it_adds_up_not_every_snapshot():
    prof = [{"t": _t(i), "detail": [[29000, 1.0, 1.0, 0.0]]} for i in range(10)]
    flip = [{"t": _t(i), "value": 28900 - 30 * i} for i in range(10)]                # 30 points a snapshot, 270 in all
    out = rp.build_frames(prof, [{"t": _t(0), "price": 29400}], {"gamma_flip": flip})
    shifts = [e["text"] for e in out["events"] if e["kind"] == "flip"]
    assert shifts == ["Gamma flip shifted 28,900 -> 28,810", "Gamma flip shifted 28,810 -> 28,720", "Gamma flip shifted 28,720 -> 28,630"]
    # 0.25% of 29,400 = 73.5 points: three reports for the 270-point drift instead of nine
