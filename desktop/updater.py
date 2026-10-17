"""Self-update from GitHub Releases.

Every release on GitHub carries one file named like  NQ-ES-Options-1.2.0-Setup.exe . The app asks GitHub for the latest release,
compares its version with its own, downloads that installer, and runs it silently. The installer closes the app, replaces the
program files and starts the app again. Your settings, database and logs are in a different folder and are never touched.

For a PRIVATE repository, put a read-only token in .env as UPDATE_TOKEN (a fine-grained token with "Contents: read" on that repo).
"""
from __future__ import annotations
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("updater")
API = "https://api.github.com"
ASSET_RE = re.compile(r"-Setup\.exe$", re.I)


def parse_version(v: str) -> tuple:
    """'v1.2.3' or '1.2' -> (1, 2, 3) / (1, 2, 0). Anything unreadable -> (0, 0, 0)."""
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", str(v or ""))
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _headers(token: str | None, accept="application/vnd.github+json") -> dict:
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "NQ-ES-Options-updater"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def latest_release(repo: str, token: str | None = None, client: httpx.Client | None = None) -> dict | None:
    """The newest published (not draft, not pre-release) release with an installer, or None."""
    c = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        r = c.get(f"{API}/repos/{repo}/releases/latest", headers=_headers(token))
        if r.status_code == 404:
            return None                                   # no release yet, or a private repo without a token
        r.raise_for_status()
        j = r.json()
        asset = next((a for a in j.get("assets", []) if ASSET_RE.search(a.get("name", ""))), None)
        if not asset:
            return None
        return {"version": ".".join(map(str, parse_version(j.get("tag_name")))), "tag": j.get("tag_name"), "notes": (j.get("body") or "")[:2000],
                "name": asset["name"], "size": asset.get("size") or 0, "api_url": asset["url"], "browser_url": asset["browser_download_url"]}
    finally:
        if client is None:
            c.close()


def download(rel: dict, dest: Path, token: str | None = None, client: httpx.Client | None = None, progress=None) -> Path:
    """Downloads the installer to dest/<name>. A private repo needs the API URL with the token; GitHub then redirects to the file
    (httpx drops the token on that redirect to another host, which is what the file host expects)."""
    dest.mkdir(parents=True, exist_ok=True)
    out, part = dest / rel["name"], dest / (rel["name"] + ".part")
    if out.exists() and rel["size"] and out.stat().st_size == rel["size"]:
        return out
    url, hdr = (rel["api_url"], _headers(token, "application/octet-stream")) if token else (rel["browser_url"], _headers(None, "application/octet-stream"))
    c = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        with c.stream("GET", url, headers=hdr) as r:
            r.raise_for_status()
            got = 0
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(1 << 16):
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(got, rel["size"])
        if rel["size"] and part.stat().st_size != rel["size"]:
            raise IOError(f"Download incomplete: {part.stat().st_size} of {rel['size']} bytes")
        part.replace(out)
        return out
    finally:
        if client is None:
            c.close()


def run_installer(path: Path, background: bool = False):
    """Starts the installer on its own (it outlives this app) in silent mode. It closes this app, updates, and starts it again
    (in the tray only, when background is True)."""
    args = [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"] + (["/relaunch=--background"] if background else [])
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True)


class Updater:
    """Checks now and then, downloads in the background, and reports its state for the tray menu and the page."""

    def __init__(self, current: str, repo: str, token: str | None = None, auto: bool = True, folder: Path | None = None, on_change=None):
        self.current, self.repo, self.token, self.auto = current, (repo or "").strip(), token, auto
        self.folder = folder or Path(tempfile.gettempdir()) / "NQ-ES-Options-update"
        self.on_change = on_change or (lambda u: None)
        self.state, self.latest, self.path, self.error, self.checked_at, self.progress = "idle", None, None, None, None, 0.0
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.repo)

    def info(self) -> dict:
        return {"current": self.current, "state": self.state if self.enabled else "off", "latest": self.latest and self.latest["version"],
                "notes": self.latest and self.latest["notes"], "error": self.error, "checked_at": self.checked_at, "progress": round(self.progress, 3),
                "repo": self.repo or None}

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        try:
            self.on_change(self)
        except Exception:                                  # a tray refresh must never stop the updater
            log.exception("update notification failed")

    def check(self, client: httpx.Client | None = None) -> str:
        """One check. Returns the new state: off, up_to_date, ready (installer downloaded), available (auto off) or error."""
        if not self.enabled:
            return "off"
        if not self._lock.acquire(blocking=False):
            return self.state
        try:
            self._set(state="checking", error=None)
            rel = latest_release(self.repo, self.token, client)
            self.checked_at = time.time()
            if not rel or not is_newer(rel["version"], self.current):
                self._set(state="up_to_date", latest=rel)
                return self.state
            self._set(latest=rel)
            if not self.auto:
                self._set(state="available")
                return self.state
            self._set(state="downloading", progress=0.0)
            p = download(rel, self.folder, self.token, client, progress=lambda g, t: setattr(self, "progress", g / t if t else 0.0))
            self._set(state="ready", path=p, progress=1.0)
            return self.state
        except Exception as e:                             # network down, GitHub limit, bad token: try again later
            log.warning("update check failed: %s", e)
            self._set(state="error", error=str(e)[:300])
            return self.state
        finally:
            self._lock.release()

    def install(self, background: bool = False) -> bool:
        """Runs the downloaded installer. The caller then quits the app."""
        if self.state == "available" and self.latest:
            self._set(state="downloading")
            self.path = download(self.latest, self.folder, self.token)
        if not self.path or not Path(self.path).exists():
            return False
        log.info("installing update %s", self.latest and self.latest["version"])
        run_installer(Path(self.path), background)
        return True


def settings_from_env(env=os.environ) -> dict:
    from backend.version import UPDATE_REPO
    return {"repo": (env.get("UPDATE_REPO") or UPDATE_REPO or "").strip(), "token": (env.get("UPDATE_TOKEN") or "").strip() or None,
            "auto": str(env.get("AUTO_UPDATE", "1")).strip().lower() not in ("0", "false", "no", "off")}
