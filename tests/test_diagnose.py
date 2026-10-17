"""diagnose.bat output for a Massive key. Responses below are SYNTHETIC TEST DATA scripted by the test."""
import httpx
import pytest

from backend import diagnose
from backend.config import Settings
from tests.conftest import massive_item

S = Settings(provider="massive", api_key="SECRET-KEY-123", underlyings=("QQQ",))


def script(monkeypatch, routes):
    def fake_get(url, params=None, headers=None, timeout=None, **kw):
        assert headers["Authorization"] == "Bearer SECRET-KEY-123" and "SECRET-KEY-123" not in url
        for frag, (code, body) in routes.items():
            if frag in url:
                return httpx.Response(code, json=body, request=httpx.Request("GET", url))
        return httpx.Response(404, json={}, request=httpx.Request("GET", url))
    monkeypatch.setattr(diagnose.httpx, "get", fake_get)


def test_full_access_reports_net_drift_possible(monkeypatch, capsys):
    script(monkeypatch, {"/v3/reference/options/contracts": (200, {"results": [{}]}),
                         "/v3/snapshot/options/QQQ": (200, {"results": [massive_item()]}),
                         "/v3/trades/": (200, {"results": [{"price": 1}]}), "/v3/quotes/": (200, {"results": [{"bid": 1}]})})
    samples = diagnose.diagnose_massive(S)
    out = capsys.readouterr().out
    assert "Key accepted" in out and "Works on your plan" in out and "Greeks: yes" in out
    assert "[trades]" in out and "[quotes]" in out and "true net drift looks possible" in out
    assert "SECRET-KEY-123" not in out and "SECRET-KEY-123" not in str(samples)


def test_snapshot_only_plan_says_net_drift_not_possible(monkeypatch, capsys):
    script(monkeypatch, {"/v3/reference/options/contracts": (200, {"results": []}),
                         "/v3/snapshot/options/QQQ": (200, {"results": [massive_item()]}),
                         "/v3/trades/": (403, {"message": "not entitled"}), "/v3/quotes/": (403, {"message": "not entitled"})})
    diagnose.diagnose_massive(S)
    out = capsys.readouterr().out
    assert "NOT on your plan" in out and "not possible with this key" in out


def test_rejected_key_stops_early(monkeypatch, capsys):
    script(monkeypatch, {"/v3/reference/options/contracts": (401, {"message": "bad key"})})
    assert diagnose.diagnose_massive(S) == {}
    assert "REJECTED" in capsys.readouterr().out


def test_plan_without_options_snapshot_is_explained(monkeypatch, capsys):
    script(monkeypatch, {"/v3/reference/options/contracts": (200, {"results": []}), "/v3/snapshot/options/QQQ": (403, {"message": "NOT_AUTHORIZED"})})
    diagnose.diagnose_massive(S)
    out = capsys.readouterr().out
    assert "Not allowed" in out and "free Basic plan" in out and "skipped: no option contract" in out
