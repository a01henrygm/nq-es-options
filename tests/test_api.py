import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings, ROOT
from backend.database import Database
from backend.providers.base import ProviderError
from tests.conftest import NOW
from tests.test_database_collector import FakeProvider, snap

KEY = "SUPER-SECRET-KEY-999"


def build(now=NOW, with_data=True):
    s = Settings(provider="massive", api_key=KEY, underlyings=("QQQ", "SPY"), poll_seconds=30)
    db, p = Database(":memory:"), FakeProvider()
    col = Collector(s, p, db, lambda: now)
    if with_data:
        p.queue = [snap()]
        col.run_once("QQQ")
    return TestClient(create_app(s, db, col, lambda: now)), col, db


def test_health_and_status_do_not_expose_key():
    c, _, _ = build()
    for path in ("/api/health", "/api/status", "/api/markets", "/api/openapi.json"):
        r = c.get(path)
        assert r.status_code == 200 and KEY not in r.text
    assert c.get("/api/status").json()["api_key_configured"] is True


def test_no_data_is_reported_not_faked():
    c, col, _ = build(with_data=False)
    r = c.get("/api/analytics/gex", params={"underlying": "QQQ"})
    assert r.status_code == 503 and r.json()["detail"]["available"] is False
    assert c.get("/api/analytics/gex", params={"underlying": "ZZZ"}).status_code == 404


def test_analytics_endpoints_carry_metadata_and_freshness():
    c, _, _ = build()
    for path in ("gex", "gamma-flip", "delta-exposure", "expected-move", "oi", "volume", "levels"):
        r = c.get(f"/api/analytics/{path}", params={"underlying": "QQQ"})
        assert r.status_code == 200, path
        m = r.json()["meta"]
        assert m["provider"] == "fake" and m["data_status"] in ("live", "delayed") and m["source_timestamp"] and m["retrieved_at"] and m["calculated_at"]
    assert c.get("/api/analytics/gex", params={"underlying": "QQQ", "convention": "bad"}).status_code == 422


def test_stale_data_is_labeled_stale():
    c, col, _ = build()
    later = NOW + timedelta(minutes=45)                                       # still market hours, nothing new arrived
    c2 = TestClient(create_app(col.s, col.db, col, lambda: later))
    assert c2.get("/api/analytics/gex", params={"underlying": "QQQ"}).json()["meta"]["data_status"] == "stale"


def test_weekend_shows_last_session_not_live():
    c, col, _ = build()
    sat = NOW.replace(day=17, hour=15)
    # data from Friday close region
    col.state["QQQ"]["snapshot"].spot_ts = NOW.replace(day=16, hour=19, minute=55)
    for k in col.state["QQQ"]["snapshot"].contracts: k.quote_ts = NOW.replace(day=16, hour=19, minute=55)
    c2 = TestClient(create_app(col.s, col.db, col, lambda: sat))
    assert c2.get("/api/analytics/gex", params={"underlying": "QQQ"}).json()["meta"]["data_status"] == "closed_last_session"


def test_database_snapshot_served_after_restart_is_flagged():
    c, col, db = build()
    s = Settings(api_key=KEY, underlyings=("QQQ",))
    fresh = Collector(s, FakeProvider(), db, lambda: NOW + timedelta(days=2))
    c2 = TestClient(create_app(s, db, fresh, lambda: NOW + timedelta(days=2)))
    m = c2.get("/api/analytics/oi", params={"underlying": "QQQ"}).json()["meta"]
    assert m["served_from"].startswith("database") and m["data_status"] == "stale"


def test_chain_filters_and_missing_values_remain_null():
    c, col, _ = build()
    col.state["QQQ"]["snapshot"].contracts[0].gamma = None
    j = c.get("/api/options/chain", params={"underlying": "QQQ", "right": "C", "strike_min": 500, "strike_max": 510}).json()
    assert {x["right"] for x in j["contracts"]} == {"C"} and all(500 <= x["strike"] <= 510 for x in j["contracts"])
    j2 = c.get("/api/options/chain", params={"underlying": "QQQ", "limit": 1000}).json()
    assert any(x["gamma"] is None for x in j2["contracts"])


def test_flow_is_honestly_unavailable():
    c, _, _ = build()
    assert c.get("/api/options/flow").json()["available"] is False


def test_futures_price_entry_validation_and_levels_mapping():
    c, _, _ = build()
    assert c.post("/api/futures-price", json={"root": "NQ", "price": 5}).status_code == 422
    assert c.post("/api/futures-price", json={"root": "NQ", "price": 21000, "as_of": (NOW + timedelta(hours=2)).isoformat()}).status_code == 422
    assert c.post("/api/futures-price", json={"root": "NQ", "price": 21000, "contract": "NQZ6", "as_of": NOW.isoformat()}).json()["saved"]
    j = c.get("/api/analytics/levels", params={"underlying": "QQQ"}).json()
    assert j["mapping"]["available"] and j["levels"] and all("mapped" in l for l in j["levels"])
    x = j["levels"][0]["mapped"]
    assert x["method"] == "ratio" and x["status"] == "ok" and x["futures_price_manual"] is True and x["calculated_at"]
    assert x["mapped"] == pytest.approx(j["levels"][0]["value"] * 21000 / 500.0)


def test_levels_without_futures_price_say_so():
    c, _, _ = build()
    j = c.get("/api/analytics/levels", params={"underlying": "QQQ"}).json()
    assert j["mapping"]["available"] is False and all("mapped" not in l for l in j["levels"])


def test_frontend_integration_every_api_call_exists():
    """Static check: each endpoint the dashboard JavaScript calls is a real route."""
    c, _, _ = build()
    paths = set(c.get("/api/openapi.json").json()["paths"])
    js = (ROOT / "frontend" / "app.js").read_text()
    called = set(re.findall(r'api\("(/[a-z/\-]+)"', js)) | {"/futures-price"}
    assert called and all(("/api" + p) in paths for p in called), called - {p[4:] for p in paths}


def test_frontend_contains_no_secrets_or_provider_urls():
    for f in (ROOT / "frontend").iterdir():
        if not f.is_file() or f.suffix not in (".js", ".html", ".css"):
            continue
        text = f.read_text()
        assert "massive.com" not in text and "polygon.io" not in text and "apiKey" not in text and "MASSIVE_API_KEY" not in text
    assert "MASSIVE_API_KEY=YOUR_API_KEY_HERE" in (ROOT / ".env.example").read_text()
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()


def test_iv_and_surface_endpoints_return_clean_data():
    from datetime import timedelta
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    from tests.conftest import make_chain
    cons = []
    for i in range(4):
        cons += make_chain(spot=500.0, n_strikes=21, step=5.0, iv=0.20 + 0.01 * i, expiry=NOW.date() + timedelta(days=2 + 5 * i))
    cons[0].bid = 0.0
    c, col, _ = build(with_data=False)
    col.state["QQQ"]["snapshot"] = ChainSnapshot("fake", "QQQ", NOW, 500.0, NOW, cons, content_hash(cons))
    j = c.get("/api/analytics/iv", params={"underlying": "QQQ"}).json()
    assert len(j["smiles"]) == 4 and j["cleaning"]["stats"]["zero_bid"] == 1 and len(j["term_structure"]) == 4
    assert j["meta"]["data_status"] in ("live", "delayed")
    one = c.get("/api/analytics/iv", params={"underlying": "QQQ", "expiration": j["smiles"][1]["expiry"]}).json()
    assert [s["expiry"] for s in one["smiles"]] == [j["smiles"][1]["expiry"]]
    s = c.get("/api/analytics/surface", params={"underlying": "QQQ"}).json()
    d = s["data"]
    assert d["available"] and len(d["z"]) == 4 and len(d["z"][0]) == len(d["strikes"]) and s["meta"]["provider"] == "fake"
    thin = c.get("/api/analytics/surface", params={"underlying": "QQQ", "min_points": 40}).json()["data"]
    assert thin["available"] is False


def test_volume_unusual_flag_history_prices_and_expected_vs_actual():
    from datetime import timedelta
    c, col, db = build()
    # unusual volume rides along with the volume endpoint
    snap_ = col.state["QQQ"]["snapshot"]
    for i, k in enumerate(snap_.contracts): k.volume = 100.0 + (i % 5) * 10
    big = next(k for k in snap_.contracts if k.strike == 500.0 and k.right == "C"); big.volume = 7000.0
    v = c.get("/api/analytics/volume", params={"underlying": "QQQ"}).json()
    assert v["unusual_volume"]["available"] and v["unusual_volume"]["flagged"][0]["strike"] == 500.0
    # no price history yet -> honest
    em = c.get("/api/analytics/expected-move", params={"underlying": "QQQ"}).json()
    assert em["actual"]["available"] is False
    # store observations from the same Eastern-time session
    db.save_price("QQQ", 497.0, "fake", NOW - timedelta(minutes=40), NOW - timedelta(minutes=40))
    db.save_price("QQQ", 499.0, "fake", NOW - timedelta(minutes=20), NOW - timedelta(minutes=20))
    db.save_price("NQ", 21000.0, "manual entry", NOW - timedelta(minutes=40), NOW, "NQZ6", manual=True)
    db.save_price("NQ", 21050.0, "manual entry", NOW - timedelta(minutes=5), NOW, "NQZ6", manual=True)
    db.save_price("QQQ", 480.0, "fake", NOW - timedelta(days=3), NOW - timedelta(days=3))              # another day: must be excluded
    hp = c.get("/api/history/prices", params={"underlying": "QQQ"}).json()
    assert [p["price"] for p in hp["points"]] == [497.0, 499.0, 500.0] and [p["price"] for p in hp["futures_points"]] == [21000.0, 21050.0]
    a = c.get("/api/analytics/expected-move", params={"underlying": "QQQ"}).json()["actual"]
    assert a["available"] and a["reference_price"] == 497.0 and a["move_points"] == pytest.approx(500.0 - 497.0)
    assert a["fraction_of_expected"] == pytest.approx(abs(a["move_points"]) / a["expected_move"]) and a["futures"]["move_points"] == 50.0


def test_delta_endpoint_includes_profile():
    c, _, _ = build()
    d = c.get("/api/analytics/delta-exposure", params={"underlying": "QQQ"}).json()["data"]
    assert d["profile"]["available"] and len(d["profile"]["grid"]) == 41


def test_heatmap_endpoint_and_validation():
    c, _, _ = build()
    j = c.get("/api/analytics/heatmap", params={"underlying": "QQQ", "field": "oi", "side": "net", "window": 0.1}).json()
    assert j["meta"]["provider"] == "fake" and j["data"]["strikes"] and len(j["data"]["z"]) == len(j["data"]["strikes"])
    assert "previous day" in j["meta"]["field_note"]
    assert c.get("/api/analytics/heatmap", params={"underlying": "QQQ", "field": "bad"}).status_code == 422
    assert c.get("/api/analytics/heatmap", params={"underlying": "QQQ", "side": "bad"}).status_code == 422
