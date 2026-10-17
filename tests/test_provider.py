import httpx
import pytest

from backend.config import Settings
from backend.providers.base import ProviderError
from backend.providers.massive import MassiveProvider, RateLimiter, normalize_contract, content_hash
from tests.conftest import massive_item

S = Settings(api_key="SECRET-KEY-123", base_url="https://api.test", max_rpm=6000)


def provider(handler):
    return MassiveProvider(S, httpx.Client(transport=httpx.MockTransport(handler)), RateLimiter(6000), sleep=lambda s: None)


def test_normalize_contract_fields_and_timestamps():
    c = normalize_contract(massive_item())
    assert c.right == "C" and c.strike == 500.0 and c.oi == 1234 and c.iv == 0.21 and c.gamma == 0.02 and c.multiplier == 100
    assert c.quote_ts is not None and c.mid == pytest.approx(1.1)


def test_missing_fields_stay_none():
    item = massive_item(); item["greeks"] = {}; item.pop("implied_volatility"); item["last_quote"] = {}
    c = normalize_contract(item)
    assert c.gamma is None and c.iv is None and c.bid is None and c.quote_ts is None and c.mid is None


def test_bad_items_are_skipped():
    assert normalize_contract({"details": {"strike_price": "x"}}) is None
    assert normalize_contract({}) is None


def test_pagination_and_key_not_in_url():
    seen = []

    def h(req):
        seen.append(req)
        assert "SECRET-KEY-123" not in str(req.url)
        assert req.headers["Authorization"] == "Bearer SECRET-KEY-123"
        if "cursor" in str(req.url):
            return httpx.Response(200, json={"results": [massive_item(505.0)]})
        if req.url.params.get("limit") == "1":
            return httpx.Response(200, json={"results": [massive_item()]})
        return httpx.Response(200, json={"results": [massive_item(500.0), massive_item(500.0, "put")], "next_url": "https://api.test/v3/snapshot/options/QQQ?cursor=abc"})
    snap = provider(h).fetch_chain("QQQ", max_dte=7, strike_window=0.05)
    assert len(snap.contracts) == 3 and snap.spot == pytest.approx(500.12) and snap.spot_ts is not None and len(seen) == 3


def test_rate_limit_retry_then_success():
    n = {"i": 0}

    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"Retry-After": "0"}) if n["i"] < 3 else httpx.Response(200, json={"results": [massive_item()]})
    assert provider(h)._get("https://api.test/x") == {"results": [massive_item()]}


def test_rate_limit_gives_up():
    with pytest.raises(ProviderError) as e:
        provider(lambda r: httpx.Response(429))._get("https://api.test/x")
    assert e.value.kind == "rate_limit"


@pytest.mark.parametrize("code,kind", [(401, "auth"), (403, "plan"), (404, "not_found")])
def test_error_kinds_and_no_key_leak(code, kind):
    with pytest.raises(ProviderError) as e:
        provider(lambda r: httpx.Response(code, json={"message": "nope"}))._get("https://api.test/x")
    assert e.value.kind == kind and "SECRET-KEY-123" not in str(e.value)


def test_network_error_is_wrapped():
    def h(req): raise httpx.ConnectError("boom")
    with pytest.raises(ProviderError) as e:
        provider(h)._get("https://api.test/x")
    assert e.value.kind == "network"


def test_missing_key():
    p = MassiveProvider(Settings(api_key=None), httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))))
    with pytest.raises(ProviderError) as e:
        p._get("https://x")
    assert e.value.kind == "auth"


def test_content_hash_changes_only_with_content():
    a, b = normalize_contract(massive_item()), normalize_contract(massive_item())
    assert content_hash([a]) == content_hash([b])
    b.bid = 9.9
    assert content_hash([a]) != content_hash([b])


def test_rate_limiter_spaces_calls():
    t, slept = {"now": 0.0}, []
    rl = RateLimiter(60, clock=lambda: t["now"], sleep=lambda s: (slept.append(s), t.__setitem__("now", t["now"] + s)))
    rl.wait(); rl.wait()
    assert slept and slept[0] == pytest.approx(1.0)
