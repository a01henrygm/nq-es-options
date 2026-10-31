"""Several data sources side by side (Cboe and Massive), chosen per request. All data below is SYNTHETIC TEST DATA."""
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings, load_sources
from backend.database import Database
from backend.models import ChainSnapshot
from backend.providers.massive import content_hash
from tests.conftest import NOW, make_chain
from tests.test_database_collector import FakeProvider


def test_load_sources_without_key_disables_massive_but_keeps_cboe():
    default, src, notes = load_sources({})
    assert default == "cboe" and list(src) == ["cboe"]
    m = next(n for n in notes if n["name"] == "massive")
    assert m["enabled"] is False and "MASSIVE_API_KEY" in m["reason"]


def test_load_sources_with_key_enables_both_with_separate_symbols_and_databases():
    default, src, notes = load_sources({"MASSIVE_API_KEY": "abc"})
    assert set(src) == {"cboe", "massive"} and all(n["enabled"] for n in notes)
    assert src["cboe"].underlyings == ("_NDX", "_SPX", "QQQ") and src["massive"].underlyings == ("QQQ", "SPY")
    assert src["cboe"].db_path != src["massive"].db_path and "massive" in src["massive"].db_path.name
    assert src["cboe"].options_plan == "delayed" and src["massive"].requires_key


def test_load_sources_overrides_and_default_choice():
    env = {"MASSIVE_API_KEY": "abc", "DEFAULT_PROVIDER": "massive", "MASSIVE_UNDERLYINGS": "I:NDX", "CBOE_UNDERLYINGS": "_NDX"}
    default, src, _ = load_sources(env)
    assert default == "massive" and src["massive"].underlyings == ("I:NDX",) and src["cboe"].underlyings == ("_NDX",)
    d2, s2, notes = load_sources({"DEFAULT_PROVIDER": "massive"})                  # default has no key: fall back to a working source
    assert d2 == "cboe" and list(s2) == ["cboe"]
    with pytest.raises(ValueError): load_sources({"DEFAULT_PROVIDER": "nope"})


def make_source(name, symbol, spot):
    s = Settings(provider=name, api_key="k" if name == "massive" else None, underlyings=(symbol,))
    db, p = Database(":memory:"), FakeProvider()
    col = Collector(s, p, db, lambda: NOW)
    cons = make_chain(spot=spot, n_strikes=21, step=5.0)
    p.queue = [ChainSnapshot(name, symbol, NOW, spot, NOW, cons, content_hash(cons))]
    col.run_once(symbol)
    return s, db, col


def build_two():
    cs, cdb, ccol = make_source("cboe", "_NDX", 500.0)
    ms, mdb, mcol = make_source("massive", "QQQ", 400.0)
    app = create_app(cs, cdb, ccol, lambda: NOW, extra_sources={"massive": (ms, mdb, mcol)},
                     source_notes=[{"name": "cboe", "label": "Cboe", "enabled": True, "reason": ""}, {"name": "massive", "label": "Massive", "enabled": True, "reason": ""}])
    return TestClient(app), cdb, mdb


def test_each_request_follows_the_selected_source():
    c, _, _ = build_two()
    d = c.get("/api/analytics/oi", params={"underlying": "_NDX"}).json()["meta"]
    assert d["provider"] == "cboe" and d["spot"] == 500.0                                   # default source
    m = c.get("/api/analytics/oi", params={"underlying": "QQQ", "source": "massive"}).json()["meta"]
    assert m["provider"] == "massive" and m["spot"] == 400.0
    assert c.get("/api/analytics/oi", params={"underlying": "QQQ"}).status_code == 404       # QQQ is not a Cboe symbol here
    assert c.get("/api/analytics/oi", params={"underlying": "_NDX", "source": "massive"}).status_code == 404


def test_unknown_source_and_status_listing():
    c, _, _ = build_two()
    r = c.get("/api/status", params={"source": "nope"})
    assert r.status_code == 404 and "Available" in r.json()["detail"]
    s = c.get("/api/status").json()
    assert s["source"] == "cboe" and s["default_source"] == "cboe" and [n["name"] for n in s["available_sources"]] == ["cboe", "massive"]
    sm = c.get("/api/status", params={"source": "massive"}).json()
    assert sm["source"] == "massive" and list(sm["underlyings"]) == ["QQQ"] and sm["requires_key"] is True
    assert "k" not in str(sm.get("api_key", "")) and "api_key" not in sm                    # the key itself is never returned


def test_typed_futures_price_and_basis_are_shared_between_sources():
    c, cdb, mdb = build_two()
    assert c.post("/api/futures-price", json={"root": "NQ", "price": 21000.0, "as_of": NOW.isoformat()}).json()["saved"]
    assert c.post("/api/basis", json={"root": "NQ", "basis": 255.0}).json()["saved"]
    for db in (cdb, mdb):
        assert db.latest_price("NQ")["price"] == 21000.0 and db.latest_price("NQ_BASIS")["price"] == 255.0
    j = c.get("/api/analytics/levels", params={"underlying": "QQQ", "source": "massive", "method": "ratio"}).json()
    assert j["levels"][0]["mapped"]["method"] == "ratio" and j["meta"]["provider"] == "massive"
