"""Chart read: screenshot in, marked-up calls out. The Anthropic API is never called here; its replies are scripted (TEST DATA)."""
import base64
import json

import httpx
import pytest

import backend.api_quant as aq
from backend.services import chart_read as cr
from tests.test_session_features import simulated_day

PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


def test_data_url_is_checked():
    assert cr.parse_data_url(PNG)[0] == "image/png"
    for bad in ("hello", "data:text/plain;base64,aGk=", "data:image/svg+xml;base64,PHN2Zz4="):
        with pytest.raises(ValueError):
            cr.parse_data_url(bad)


def good_reading(last=30300.0):
    return {"symbol": "NQ1!", "timeframe": "1m", "last_price": last, "axis": {"p1": 30400.0, "y1": 0.2, "p2": 30200.0, "y2": 0.8},
            "last_candle_x": 0.7, "candle_spacing": 0.01, "plot_right_x": 0.92, "structure": "Range between two levels.", "levels_seen": [], "readable": True}


def test_reading_sanity_checks():
    assert cr.check_reading(good_reading()) == []
    flipped = {**good_reading(), "axis": {"p1": 30400.0, "y1": 0.8, "p2": 30200.0, "y2": 0.2}}
    assert "upside down" in " ".join(cr.check_reading(flipped))
    assert cr.check_reading({**good_reading(), "readable": False, "problem": "scale cropped"})[-1] == "scale cropped"
    assert cr.check_reading({**good_reading(), "last_candle_x": 1.4})


def test_api_request_shape_and_errors():
    seen = {}

    def handler(req):
        seen["body"], seen["key"] = json.loads(req.content), req.headers["x-api-key"]
        return httpx.Response(200, json={"content": [{"type": "tool_use", "name": "chart_read", "input": good_reading()}]})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    out = cr.read_chart("sk-ant-test", "image/png", "AAAA", [{"price": 30300.0, "label": "wall", "call": "RESPECT"}], "Long gamma", "NQ", client=c)
    assert out["last_price"] == 30300.0 and seen["key"] == "sk-ant-test"
    b = seen["body"]
    assert b["tool_choice"] == {"type": "tool", "name": "chart_read"} and b["messages"][0]["content"][0]["type"] == "image"
    assert "30300.00  wall  (app call: RESPECT)" in b["messages"][0]["content"][1]["text"]
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})))
    with pytest.raises(RuntimeError, match="not accepted"):
        cr.read_chart("sk-ant-x", "image/png", "AAAA", [], "", "NQ", client=bad)


def test_chart_read_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(aq, "DATA", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    c, db, now = simulated_day()
    assert c.get("/api/chart-read/status").json()["configured"] is False
    r = c.post("/api/chart-read", json={"image": PNG, "underlying": "_NDX"})
    assert r.status_code == 400 and r.json()["detail"]["need_key"]
    assert c.post("/api/chart-read/key", json={"key": "nope"}).status_code == 422
    assert c.post("/api/chart-read/key", json={"key": "sk-ant-api03-" + "a" * 30}).json()["saved"]
    assert "ANTHROPIC_API_KEY=sk-ant-api03-" in (tmp_path / ".env").read_text()
    spot = c.get("/api/analytics/hodlod", params={"underlying": "_NDX"}).json()["data"]["hodlod"]["spot"]
    monkeypatch.setattr(cr, "read_chart", lambda *a, **k: good_reading(last=spot + 30))
    j = c.post("/api/chart-read", json={"image": PNG, "underlying": "_NDX"}).json()
    assert j["problems"] == [] and j["levels"] and all(l["call"] in ("RESPECT", "CHOP", "DISRESPECT") for l in j["levels"])
    assert j["warnings"] and "basis" in j["warnings"][0]                                  # no futures price saved: scaled to the chart
    assert j["projection"]["main"]["candles"] and j["projection"]["start_x"] == 0.7
    monkeypatch.setattr(cr, "read_chart", lambda *a, **k: good_reading(last=6800.0))     # an ES chart against NDX levels
    j = c.post("/api/chart-read", json={"image": PNG, "underlying": "_NDX"}).json()
    assert j["problems"] and j["projection"] is None
