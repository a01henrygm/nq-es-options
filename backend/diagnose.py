"""Checks that your data source works and shows which fields it really supplies. Run diagnose.bat first.

For Cboe (default, no key): downloads each configured file and reports what it contains.
For Massive: makes one tiny request per underlying and explains what your plan allows.
A REDACTED sample goes to logs\\diagnose_sample.json so field names can be verified.
"""
from __future__ import annotations
import json

import httpx

from .config import DATA, load_sources
from .providers.cboe import UA, normalize_option
from .providers.massive import normalize_contract
from .timeutil import parse_et


def redact(obj, key):
    return json.loads(json.dumps(obj).replace(key, "***")) if key else obj


def diagnose_cboe(s):
    print(f"Provider: Cboe delayed quotes (no key needed)   Source: {s.cboe_base_url}\n")
    samples = {}
    for u in s.underlyings:
        url = f"{s.cboe_base_url}/{u}.json"
        try:
            r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
        except httpx.HTTPError as e:
            print(f"[{u}] could not connect: {type(e).__name__}. Check your internet connection or firewall.")
            continue
        print(f"[{u}] HTTP {r.status_code}, {len(r.content) / 1e6:.1f} MB")
        if r.status_code != 200:
            print("   Not available. Index options need a leading underscore (_NDX, _SPX); ETFs use the plain ticker (QQQ, SPY).")
            continue
        try:
            j = r.json(); d = j["data"]; opts = d["options"]
        except (ValueError, KeyError, TypeError):
            print("   The file did not have the expected data.options list. Send logs\\diagnose_sample.json for a fix.")
            continue
        n = len(opts)
        norm = [normalize_option(o) for o in opts]
        ok = [c for c in norm if c]
        has = lambda f: sum(1 for c in ok if getattr(c, f) not in (None, 0))
        print(f"   Underlying price: {d.get('current_price')}   Contracts in file: {n}   Read OK: {len(ok)}")
        ts = j.get("timestamp"); lt = d.get("last_trade_time")
        print(f"   File timestamp: {ts!r} ({'read as Eastern Time' if parse_et(ts) else 'NOT USABLE'})   Underlying last trade time: {lt!r} ({'ok' if parse_et(lt) else 'not usable'})")
        if not parse_et(ts) and not parse_et(lt):
            print("   WARNING: no usable timestamp, so freshness will show 'no source time'.")
        print("   Fields filled (contracts with a non-zero value): " + ", ".join(f"{f} {has(f)}" for f in ("bid", "ask", "iv", "delta", "gamma", "oi", "volume")))
        if has("gamma") == 0:
            print("   Gamma is missing; the app will compute it from IV and label it 'model'.")
        top = {k: v for k, v in d.items() if k != "options"}
        samples[u] = {"top_level": {k: v for k, v in j.items() if k != "data"}, "data_fields": top, "first_options": opts[:3]}
    return samples


def _msg(r):
    try:
        j = r.json()
        return str(j.get("message") or j.get("error") or j.get("status") or "")[:160]
    except ValueError:
        return r.text[:120]


def diagnose_massive(s):
    print(f"Provider: Massive {s.base_url}   (key present, value hidden)\n")
    hdr = {"Authorization": f"Bearer {s.api_key}"}
    get = lambda path, params=None: httpx.get(f"{s.base_url}{path}", params=params, headers=hdr, timeout=25)
    samples, first_ticker = {}, None
    # 1. Is the key accepted at all?
    try:
        r = get("/v3/reference/options/contracts", {"underlying_ticker": "QQQ", "limit": 1})
    except httpx.HTTPError as e:
        print(f"Could not connect to Massive: {type(e).__name__}. Check your internet connection or firewall.")
        return samples
    verdict = {200: "Key accepted.", 401: "Key REJECTED. Check that it was copied correctly into .env (no spaces or quotes).",
               403: "Key recognized, but this basic lookup is not on your plan.", 429: "Rate limit reached. Wait a minute and run this again."}
    print(f"[key check] HTTP {r.status_code}: {verdict.get(r.status_code, 'Unexpected: ' + _msg(r))}")
    if r.status_code == 401:
        return samples
    # 2. Chain snapshot for each configured underlying
    for u in s.underlyings:
        try:
            r = get(f"/v3/snapshot/options/{u}", {"limit": 3})
        except httpx.HTTPError as e:
            print(f"[{u}] could not connect: {type(e).__name__}.")
            continue
        print(f"[{u}] chain snapshot: HTTP {r.status_code}")
        if r.status_code == 200:
            j = r.json(); res = j.get("results") or []; samples[u] = redact(j, s.api_key)
            if not res:
                print("   Connected, but no contracts returned. For index options use the I: prefix (I:NDX, I:SPX).")
                continue
            c = res[0]
            first_ticker = first_ticker or (c.get("details") or {}).get("ticker")
            print("   Works on your plan. Normalizer:", "ok" if normalize_contract(c) else "FAILED - send logs\\diagnose_sample.json")
            print("   Greeks:", "yes" if c.get("greeks") else "NO", "| IV:", "yes" if c.get("implied_volatility") else "NO",
                  "| open interest:", "yes" if c.get("open_interest") is not None else "NO",
                  "| underlying timestamp:", "yes" if (c.get("underlying_asset") or {}).get("last_updated") else "NO")
        elif r.status_code in (401, 403):
            print(f"   Not allowed: {_msg(r)}. Your plan likely does not include the options chain snapshot (not part of the free Basic plan).")
        elif r.status_code == 429:
            print("   Rate limit reached. Wait a minute and try again.")
        else:
            print("   Unexpected response:", _msg(r))
    # 3. Trade-level data (needed for a true Net Drift)
    print()
    if not first_ticker:
        print("[trades and quotes] skipped: no option contract was available to test with.")
        return samples
    seen = {}
    for label, path in (("trades", f"/v3/trades/{first_ticker}"), ("quotes", f"/v3/quotes/{first_ticker}")):
        try:
            r = get(path, {"limit": 1})
        except httpx.HTTPError as e:
            print(f"[{label}] could not connect: {type(e).__name__}.")
            continue
        n = len(r.json().get("results") or []) if r.status_code == 200 else 0
        seen[label] = (r.status_code, n)
        says = {200: "included on your plan" + (" (data returned)" if n else " (endpoint allowed, but nothing came back for this contract right now)"),
                401: "not allowed", 403: "NOT on your plan", 404: "endpoint or contract not found", 429: "rate limited"}
        print(f"[{label}] {first_ticker}: HTTP {r.status_code}, {says.get(r.status_code, _msg(r))}")
    ok = all(seen.get(k, (0, 0))[0] == 200 for k in ("trades", "quotes"))
    print("\nNet Drift needs both trades and quotes:", "both are available, so a true net drift looks possible to build." if ok
          else "at least one is not available on this plan, so a true net drift is not possible with this key.")
    return samples


def main():
    default, sources, notes = load_sources()
    samples = {}
    for n in notes:
        if not n["enabled"]:
            print(f"[{n['label']}] skipped: {n['reason']}\n")
    for name, st in sources.items():
        print("=" * 60)
        samples[name] = diagnose_cboe(st) if name == "cboe" else diagnose_massive(st)
        print()
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    (DATA / "logs" / "diagnose_sample.json").write_text(json.dumps(samples, indent=1, default=str)[:300000])
    print("Saved a sample to logs\\diagnose_sample.json (market data only, no secrets).")


if __name__ == "__main__":
    main()
