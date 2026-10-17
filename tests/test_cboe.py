"""Cboe provider tests. The JSON below is SYNTHETIC TEST DATA shaped like Cboe's delayed-quote file."""
import json
import threading
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.collector import Collector
from backend.config import Settings, load_settings
from backend.database import Database
from backend.providers.base import ProviderError
from backend.providers.cboe import CboeProvider, normalize_option
from backend.timeutil import UTC, parse_et

TODAY = date(2026, 10, 14)
S = Settings(provider="cboe", cboe_base_url="https://cboe.test/opts", underlyings=("_NDX",))


def opt(strike, right="C", days=2, **kw):
    e = TODAY + timedelta(days=days)
    d = {"option": f"NDXP{e:%y%m%d}{right}{int(strike * 1000):08d}", "bid": 10.0, "ask": 11.0, "iv": 0.22, "delta": 0.5 if right == "C" else -0.5,
         "gamma": 0.001, "vega": 1.0, "theta": -2.0, "open_interest": 500, "volume": 40, "last_trade_price": 10.5,
         "last_trade_time": "2026-10-14T10:58:00"}
    d.update(kw)
    return d


def file(options, ts="2026-10-14 11:00:00", price=30000.0):
    j = {"data": {"current_price": price, "last_trade_time": "2026-10-14T10:59:59", "options": options}}
    if ts: j["timestamp"] = ts
    return j


def prov(handler):
    return CboeProvider(S, httpx.Client(transport=httpx.MockTransport(handler)), today_fn=lambda: TODAY)


def serve(j, status=200):
    return lambda req: httpx.Response(status, json=j)


def test_et_timestamps_convert_with_dst():
    assert parse_et("2026-07-14 11:00:00") == datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
    assert parse_et("2026-12-14 11:00:00") == datetime(2026, 12, 14, 16, 0, tzinfo=UTC)
    assert parse_et("2026-10-14T11:00:00") == datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    assert parse_et("2025-06-25 15:59:57 ET (Delayed)") == datetime(2025, 6, 25, 19, 59, 57, tzinfo=UTC)     # how Cboe labels its pages
    assert parse_et("2026-10-14 11:00") == datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    assert parse_et("2026-13-45 99:99:99 ET") is None
    assert parse_et(None) is None and parse_et("garbage") is None and parse_et("") is None


def test_normalize_option_fields():
    c = normalize_option(opt(29740, "P"))
    assert c.right == "P" and c.strike == 29740.0 and c.expiry == date(2026, 10, 16) and c.multiplier == 100
    assert c.iv == 0.22 and c.gamma == 0.001 and c.oi == 500 and c.volume == 40 and c.mid == 10.5 and c.trade_ts is not None


def test_zero_iv_means_no_iv_and_no_greeks_not_zero():
    c = normalize_option(opt(29740, iv=0.0, delta=0.0, gamma=0.0))
    assert c.iv is None and c.delta is None and c.gamma is None


def test_bad_symbols_skipped():
    assert normalize_option({"option": "NOTANOPTION"}) is None and normalize_option({}) is None
    assert normalize_option({"option": "NDXP269999C00030000"}) is None          # impossible date


def test_fetch_filters_and_timestamps():
    j = file([opt(30000), opt(30100, "P"), opt(20000), opt(30000, days=90), opt(30000, days=-5)])
    snap = prov(serve(j)).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert snap.provider == "cboe" and snap.spot == 30000.0
    assert sorted(c.strike for c in snap.contracts) == [30000.0, 30100.0]       # far strike, far expiry, expired all dropped
    assert snap.source_ts == datetime(2026, 10, 14, 15, 0, tzinfo=UTC)         # file timestamp, read as Eastern Time


def test_timestamp_fallback_and_no_invention():
    j = file([opt(30000)], ts=None)
    assert prov(serve(j)).fetch_chain("_NDX", max_dte=14, strike_window=0.08).spot_ts == datetime(2026, 10, 14, 14, 59, 59, tzinfo=UTC)
    j2 = file([opt(30000)], ts=None); j2["data"].pop("last_trade_time")
    assert prov(serve(j2)).fetch_chain("_NDX", max_dte=14, strike_window=0.08).source_ts is None


@pytest.mark.parametrize("code,kind", [(404, "not_found"), (429, "rate_limit"), (500, "server"), (403, "server")])
def test_http_errors(code, kind):
    with pytest.raises(ProviderError) as e:
        prov(lambda r: httpx.Response(code)).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert e.value.kind == kind


def test_schema_and_network_errors():
    with pytest.raises(ProviderError) as e:
        prov(serve({"nothing": 1})).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert e.value.kind == "schema"
    def boom(req): raise httpx.ConnectError("x")
    with pytest.raises(ProviderError) as e2:
        prov(boom).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert e2.value.kind == "network"


def test_config_defaults_need_no_key():
    s = load_settings({})
    assert s.provider == "cboe" and not s.requires_key and s.underlyings == ("_NDX", "_SPX") and s.options_plan == "delayed" and s.poll_seconds >= 120
    assert load_settings({"POLL_SECONDS": "5"}).poll_seconds == 60               # never hammer Cboe
    with pytest.raises(ValueError): load_settings({"PROVIDER": "nope"})


class _H(BaseHTTPRequestHandler):
    payload = b"{}"
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(self.payload)
    def log_message(self, *a): pass


def test_end_to_end_with_local_server_serving_synthetic_cboe_file():
    """Whole pipeline: HTTP download -> normalize -> SQLite -> analytics -> API, using a local server (TEST DATA)."""
    opts = []
    for k in range(29000, 31001, 50):
        opts += [opt(k, "C", open_interest=3000 if k >= 30000 else 200),
                 opt(k, "P", open_interest=3000 if k < 30000 else 200)]
    _H.payload = json.dumps(file(opts)).encode()
    srv = HTTPServer(("127.0.0.1", 0), _H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = Settings(provider="cboe", cboe_base_url=f"http://127.0.0.1:{srv.server_port}", underlyings=("_NDX",), strike_window=0.1)
        now = datetime(2026, 10, 14, 15, 1, tzinfo=UTC)
        db = Database(":memory:")
        col = Collector(s, CboeProvider(s, today_fn=lambda: TODAY), db, lambda: now)
        assert col.run_once("_NDX") is True and col.run_once("_NDX") is False          # second identical download is not new data
        c = TestClient(create_app(s, db, col, lambda: now))
        st = c.get("/api/status").json()
        assert st["provider"] == "cboe" and st["api_key_configured"] is None and st["requires_key"] is False
        assert st["underlyings"]["_NDX"]["data_status"] == "delayed"
        j = c.get("/api/analytics/gex", params={"underlying": "_NDX"}).json()
        assert j["meta"]["provider"] == "cboe" and j["meta"]["data_status"] == "delayed" and j["data"]["strikes"]
        c.post("/api/futures-price", json={"root": "NQ", "price": 30120.0, "as_of": "2026-10-14T14:59:59+00:00"})
        lv = c.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()
        m = lv["levels"][0]["mapped"]
        assert m["method"] == "basis" and m["mapped"] == pytest.approx(lv["levels"][0]["value"] + 120.0)
        assert c.get("/api/options/chain", params={"underlying": "_NDX", "limit": 5}).json()["contracts"]
    finally:
        srv.shutdown()


# ---- port handling: the "address already in use" error must never reach the user -----------------------
def test_choose_port_free_ours_and_foreign():
    import socket
    from backend.main import choose_port, port_open
    sk = socket.socket(); sk.bind(("127.0.0.1", 0)); free = sk.getsockname()[1]; sk.close()
    assert choose_port("127.0.0.1", free) == (free, False)

    class H(BaseHTTPRequestHandler):
        body = b'{"ok": true}'
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(self.body)
        def log_message(self, *a): pass
    ours = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=ours.serve_forever, daemon=True).start()
    try:
        assert port_open("127.0.0.1", ours.server_port)
        assert choose_port("127.0.0.1", ours.server_port) == (ours.server_port, True)      # already running: reuse, do not start twice
    finally:
        ours.shutdown()
    H.body = b"<html>some other program</html>"
    other = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=other.serve_forever, daemon=True).start()
    try:
        p, running = choose_port("127.0.0.1", other.server_port)
        assert running is False and p != other.server_port and not port_open("127.0.0.1", p)   # another program: pick the next free port
    finally:
        other.shutdown()


def test_levels_use_typed_basis_for_nq_end_to_end():
    from tests.test_api import build, KEY
    from tests.conftest import NOW
    c, col, db = build(with_data=False)
    # rebuild with an index underlying so the basis path applies
    from backend.models import ChainSnapshot
    from backend.providers.massive import content_hash
    from tests.conftest import make_chain
    cons = make_chain(spot=30000.0, n_strikes=41, step=50.0)
    snap = ChainSnapshot("cboe", "_NDX", NOW, 30000.0, NOW, cons, content_hash(cons))
    st2 = Settings(provider="cboe", underlyings=("_NDX",))
    col2 = Collector(st2, None, db, lambda: NOW); col2.state["_NDX"]["snapshot"] = snap
    c2 = TestClient(create_app(st2, db, col2, lambda: NOW))
    j0 = c2.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()
    assert j0["mapping"]["available"] is False and all("mapped" not in l for l in j0["levels"])
    assert c2.post("/api/basis", json={"root": "NQ", "basis": 99999}).status_code == 422
    assert c2.post("/api/basis", json={"root": "XX", "basis": 5}).status_code == 422
    assert c2.post("/api/basis", json={"root": "NQ", "basis": 262.5}).json()["saved"]
    j = c2.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()               # auto picks the typed basis
    assert j["mapping"]["available"] and j["mapping"]["typed_basis"]["value"] == 262.5
    for l in j["levels"]:
        assert l["mapped"]["method"] == "typed_basis" and l["mapped"]["mapped"] == pytest.approx(l["value"] + 262.5)
    forced = c2.get("/api/analytics/levels", params={"underlying": "_NDX", "method": "typed_basis"}).json()
    assert forced["levels"][0]["mapped"]["method"] == "typed_basis"
    # whichever you typed LAST wins in auto mode: a futures price saved afterwards takes over, a newer basis takes it back
    c2.post("/api/futures-price", json={"root": "NQ", "price": 30300.0, "as_of": NOW.isoformat()})
    assert c2.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()["levels"][0]["mapped"]["method"] == "basis"
    later = TestClient(create_app(st2, db, col2, lambda: NOW + timedelta(minutes=10)))
    later.post("/api/basis", json={"root": "NQ", "basis": 270.0})
    top = later.get("/api/analytics/levels", params={"underlying": "_NDX"}).json()["levels"][0]
    assert top["mapped"]["method"] == "typed_basis" and top["mapped"]["mapped"] == pytest.approx(top["value"] + 270.0)


# ---- "No data received": price fallbacks and clear reasons ------------------------------------------
def test_price_field_fallback_and_parity_estimate():
    j = file([opt(30000), opt(30000, "P")]); j["data"].pop("current_price"); j["data"]["price"] = 29990.0
    s = prov(serve(j)).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert s.spot == 29990.0 and "price" in s.spot_note
    # no price anywhere: estimated from call and put mids at the same strike (call 10.5 - put 10.5 -> spot = strike)
    j2 = file([opt(30000), opt(30000, "P"), opt(30500), opt(30500, "P", bid=510.0, ask=511.0)]); j2["data"].pop("current_price")
    s2 = prov(serve(j2)).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert s2.spot == pytest.approx(30000.0) and "put-call parity" in s2.spot_note
    j3 = file([opt(30000)]); j3["data"].pop("current_price")                      # only a call: cannot estimate, stays None
    assert prov(serve(j3)).fetch_chain("_NDX", max_dte=14, strike_window=0.08).spot is None


def test_everything_filtered_out_is_an_error_not_an_empty_dashboard():
    j = file([opt(30000, days=200), opt(20000)])
    with pytest.raises(ProviderError) as e:
        prov(serve(j)).fetch_chain("_NDX", max_dte=14, strike_window=0.08)
    assert e.value.kind == "schema" and "none fell inside the filters" in str(e.value) and "MAX_DTE" in str(e.value)


def test_503_explains_why_there_is_no_data():
    from tests.test_api import build
    from tests.conftest import NOW
    c, col, _ = build(with_data=False)
    r = c.get("/api/analytics/gex", params={"underlying": "QQQ"})
    assert r.status_code == 503 and "first download has not finished" in r.json()["detail"]["reason"]
    col.state["QQQ"]["last_attempt"] = NOW
    assert "finished but returned nothing" in c.get("/api/analytics/gex", params={"underlying": "QQQ"}).json()["detail"]["reason"]
    col.state["QQQ"]["last_error"] = {"kind": "network", "message": "down", "at": NOW.isoformat(), "status": None}
    j = c.get("/api/analytics/gex", params={"underlying": "QQQ"}).json()["detail"]
    assert "failed" in j["reason"] and j["last_error"]["kind"] == "network"
