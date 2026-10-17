"""Optional password for reaching the dashboard from another device (for example your phone on the same Wi-Fi).

Design, kept simple on purpose:
* If ACCESS_PASSWORD is empty nothing changes: the app is only reachable from this PC (HOST=127.0.0.1).
* If a password is set, any request that does not come from this PC must have signed in. The PC itself is not asked (switch that off
  with ACCESS_LOCAL_BYPASS=0).
* The password is compared in constant time, failed attempts are rate limited, and the sign-in cookie is signed with a secret kept in
  data\\.session_secret, HttpOnly and SameSite=Strict.
* Traffic on your Wi-Fi is NOT encrypted (plain http). That is acceptable on a trusted home network; never expose this port to the internet.
"""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import time
from collections import defaultdict, deque
from html import escape
from pathlib import Path
from urllib.parse import parse_qs

from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "nq_session"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in</title><style>body{background:#0b0d10;color:#e8eaed;font:16px -apple-system,Segoe UI,Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#14181d;border:1px solid #262c34;border-radius:10px;padding:24px;width:min(360px,90vw)}h1{font-size:20px;margin:0 0 12px}
input{width:100%;box-sizing:border-box;padding:12px;border-radius:8px;border:1px solid #262c34;background:#0b0d10;color:#e8eaed;font-size:16px;margin:6px 0 12px}
button{width:100%;padding:12px;border-radius:8px;border:0;background:#2f8bf5;color:#fff;font-size:16px}.err{color:#ff6b6b;margin:0 0 10px}.dim{color:#98a2ad;font-size:13px}</style></head>
<body><form method="post" action="/login"><h1>NQ / ES options analytics</h1>__MSG__<label>Password<input type="password" name="password" autofocus autocomplete="current-password"></label>
<button type="submit">Sign in</button><p class="dim">Only people on your network who know the password can see this.</p></form></body></html>"""


def exposure_problem(host: str, password: str | None) -> str | None:
    """Returns a message if the settings would expose the dashboard to the network without a password."""
    if host not in LOOPBACK and host != "localhost" and not password:
        return (f"HOST is set to {host}, which lets other devices on your network open the dashboard, but ACCESS_PASSWORD is empty.\n"
                "Set ACCESS_PASSWORD in .env (at least 8 characters), or set HOST=127.0.0.1 to keep it on this PC only.")
    if password and len(password) < 8:
        return "ACCESS_PASSWORD must be at least 8 characters."
    return None


class Auth:
    def __init__(self, password: str, secret_path: Path | None = None, local_bypass: bool = True, max_fails: int = 5, window: int = 300, ttl: int = 30 * 86400):
        self.password, self.local_bypass, self.max_fails, self.window, self.ttl = password, local_bypass, max_fails, window, ttl
        self.fails = defaultdict(deque)
        self.secret = self._load_secret(secret_path)

    @staticmethod
    def _load_secret(path):
        if path:
            try:
                p = Path(path)
                if p.exists():
                    return bytes.fromhex(p.read_text().strip())
                p.parent.mkdir(parents=True, exist_ok=True)
                s = secrets.token_bytes(32)
                p.write_text(s.hex())
                return s
            except (OSError, ValueError):
                pass
        return secrets.token_bytes(32)           # not persisted: sessions end when the app restarts

    def token(self, now=None) -> str:
        exp = int((now or time.time()) + self.ttl)
        return f"{exp}.{hmac.new(self.secret, str(exp).encode(), hashlib.sha256).hexdigest()}"

    def valid(self, tok, now=None) -> bool:
        try:
            exp, sig = tok.split(".", 1)
            good = hmac.new(self.secret, exp.encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(sig, good) and int(exp) > (now or time.time())
        except (ValueError, AttributeError):
            return False

    def blocked(self, ip, now=None) -> int:
        """Seconds the address must wait, or 0."""
        q, t = self.fails[ip], now or time.time()
        while q and t - q[0] > self.window:
            q.popleft()
        return int(self.window - (t - q[0])) if len(q) >= self.max_fails else 0

    def check(self, supplied: str, ip: str, now=None) -> bool:
        ok = hmac.compare_digest(supplied.encode(), self.password.encode())
        if not ok:
            self.fails[ip].append(now or time.time())
        return ok


def install_auth(app, auth: Auth):
    """Must be added LAST so it wraps every other middleware."""
    @app.middleware("http")
    async def gate(request, call_next):
        ip, path = (request.client.host if request.client else ""), request.url.path
        if (auth.local_bypass and ip in LOOPBACK) or path == "/api/health":
            return await call_next(request)
        if path == "/login":
            if request.method == "POST":
                wait = auth.blocked(ip)
                if wait:
                    return HTMLResponse(PAGE.replace("__MSG__", f'<p class="err">Too many wrong passwords. Try again in {wait // 60 + 1} minutes.</p>'), status_code=429)
                form = parse_qs((await request.body()).decode("utf-8", "ignore"))
                if auth.check(form.get("password", [""])[0], ip):
                    r = RedirectResponse("/", status_code=303)
                    r.set_cookie(COOKIE, auth.token(), max_age=auth.ttl, httponly=True, samesite="strict", path="/")
                    return r
                return HTMLResponse(PAGE.replace("__MSG__", '<p class="err">Wrong password.</p>'), status_code=401)
            return HTMLResponse(PAGE.replace("__MSG__", ""))
        if path == "/logout":
            r = RedirectResponse("/login", status_code=303)
            r.delete_cookie(COOKIE, path="/")
            return r
        if auth.valid(request.cookies.get(COOKIE, "")):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Sign in required."}, status_code=401)
        return RedirectResponse("/login", status_code=303)
