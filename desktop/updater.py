"""Self-update from GitHub Releases.

Windows: every release carries a file named like  NQ-ES-Options-1.2.0-Setup.exe . The app asks GitHub for the latest release,
compares its version with its own, downloads that installer, and runs it silently. The installer closes the app, replaces the
program files and starts the app again.

Mac: every release also carries  Q-DATA-1.2.0-macOS-arm64.zip  (Apple Silicon) and  ...-macOS-x86_64.zip  (Intel). The app
downloads the one for this Mac, unpacks the new Q DATA.app next to its update folder, and a small script waits for the app to
quit, swaps the new app in where the old one was, and opens it again.

Your settings, database and logs are in a different folder and are never touched.

For a PRIVATE repository, put a read-only token in .env as UPDATE_TOKEN (a fine-grained token with "Contents: read" on that repo).
"""
from __future__ import annotations
import logging
import os
import platform
import re
import shutil
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


def mac_arch(machine: str | None = None) -> str:
    m = (machine or platform.machine() or "").lower()
    return "arm64" if m in ("arm64", "aarch64") else "x86_64"


def asset_pattern(plat: str | None = None, machine: str | None = None) -> re.Pattern:
    """Which release file is this computer's: the Windows installer, or the Mac zip for this Mac's chip."""
    if (plat or sys.platform) == "darwin":
        return re.compile(rf"-macOS-{mac_arch(machine)}\.zip$", re.I)
    return ASSET_RE


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


def latest_release(repo: str, token: str | None = None, client: httpx.Client | None = None, pattern: re.Pattern | None = None) -> dict | None:
    """The newest published (not draft, not pre-release) release with a file for this computer, or None."""
    pattern = pattern or asset_pattern()
    c = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        r = c.get(f"{API}/repos/{repo}/releases/latest", headers=_headers(token))
        if r.status_code == 404:
            return None                                   # no release yet, or a private repo without a token
        r.raise_for_status()
        j = r.json()
        asset = next((a for a in j.get("assets", []) if pattern.search(a.get("name", ""))), None)
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
    """Starts the update on its own (it outlives this app). It closes this app, updates, and starts it again
    (in the tray / menu bar only, when background is True)."""
    if sys.platform == "darwin":
        return run_mac_update(path, background)
    args = [str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"] + (["/relaunch=--background"] if background else [])
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True)


# ---- Mac --------------------------------------------------------------------------------------------------------------
MAC_SWAP = """#!/bin/sh
# Q DATA update: wait for the app to quit, put the new app where the old one was, open it again.
pid="$1"; new="$2"; dest="$3"; shift 3
i=0
while kill -0 "$pid" 2>/dev/null && [ $i -lt 60 ]; do sleep 1; i=$((i+1)); done
kill -9 "$pid" 2>/dev/null
sleep 1
rm -rf "$dest.old"
if mv "$dest" "$dest.old" && mv "$new" "$dest"; then
  rm -rf "$dest.old"
else
  [ -d "$dest" ] || mv "$dest.old" "$dest"
fi
xattr -dr com.apple.quarantine "$dest" 2>/dev/null
open "$dest" --args "$@"
"""


def mac_app_bundle(executable: str | None = None) -> Path | None:
    """The Q DATA.app this program runs from (.../Q DATA.app/Contents/MacOS/Q DATA), or None when run from source."""
    p = Path(executable or sys.executable).resolve()
    for parent in p.parents:
        if parent.suffix == ".app":
            return parent
    return None


def mac_update_problem(bundle: Path | None) -> str | None:
    """Why the app cannot replace itself where it is, or None when it can."""
    if bundle is None:
        return "Not running as the installed Q DATA app."
    s = str(bundle)
    if "/AppTranslocation/" in s or s.startswith("/Volumes/"):
        return "Move Q DATA into your Applications folder (drag it there from the download), open it from there, and updates will work."
    if not os.access(bundle.parent, os.W_OK):
        return f"Q DATA can't update itself in {bundle.parent}: that folder is not writable for your account."
    return None


def _unzip(zip_path: Path, out: Path):
    if shutil.which("ditto"):                                  # keeps the app's links, permissions and signature intact
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(out)], check=True, capture_output=True)
    else:                                                      # only for tests off a Mac
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(out)


def mac_stage(zip_path: Path, work: Path, unzip=_unzip) -> Path:
    """Unpacks the downloaded zip into work/staged and returns the new .app inside it."""
    staged = work / "staged"
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    unzip(zip_path, staged)
    app = next((p for p in staged.iterdir() if p.suffix == ".app"), None)
    if app is None:
        raise IOError("The update download does not contain Q DATA.app")
    return app


def run_mac_update(zip_path: Path, background: bool = False, bundle: Path | None = None, unzip=_unzip):
    bundle = bundle or mac_app_bundle()
    problem = mac_update_problem(bundle)
    if problem:
        raise RuntimeError(problem)
    work = zip_path.parent
    new_app = mac_stage(zip_path, work, unzip)
    script = work / "swap.sh"
    script.write_text(MAC_SWAP)
    args = ["/bin/sh", str(script), str(os.getpid()), str(new_app), str(bundle)] + (["--background"] if background else [])
    subprocess.Popen(args, start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
            problem = mac_update_problem(mac_app_bundle()) if sys.platform == "darwin" else None
            if problem:                                    # e.g. opened straight from Downloads: say how to fix it, don't download
                self._set(state="error", error=f"Version {rel['version']} is out. {problem}")
                return self.state
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
        try:
            run_installer(Path(self.path), background)
        except Exception as e:                             # Mac: app not in a writable place, or a broken download
            log.warning("update install failed: %s", e)
            self._set(state="error", error=str(e)[:300])
            return False
        return True


def settings_from_env(env=os.environ) -> dict:
    from backend.version import UPDATE_REPO
    return {"repo": (env.get("UPDATE_REPO") or UPDATE_REPO or "").strip(), "token": (env.get("UPDATE_TOKEN") or "").strip() or None,
            "auto": str(env.get("AUTO_UPDATE", "1")).strip().lower() not in ("0", "false", "no", "off")}
