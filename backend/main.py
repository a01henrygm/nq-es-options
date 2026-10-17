"""Entry point: python -m backend.main"""
from __future__ import annotations
import logging
import logging.handlers
import socket
import sys
import threading
import webbrowser

import httpx
import uvicorn

from .api import create_app
from .collector import Collector
from .config import DATA, load_sources
from .database import Database
from .security import LOOPBACK, exposure_problem
from .services.events_seed import seed_events
from .providers.cboe import CboeProvider
from .providers.massive import MassiveProvider


class RedactKey(logging.Filter):
    """Belt and braces: remove the API key from any log line."""

    def __init__(self, key):
        super().__init__()
        self.key = key

    def filter(self, record):
        if self.key:
            record.msg = str(record.msg).replace(self.key, "***")
            record.args = tuple(str(a).replace(self.key, "***") if isinstance(a, str) else a for a in (record.args or ()))
        return True


def build():
    default, sources, notes = load_sources()
    s = sources[default]
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(DATA / "logs" / "app.log", maxBytes=2_000_000, backupCount=3)
    for h in (handler, logging.StreamHandler()):
        h.addFilter(RedactKey(s.api_key))
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)   # keep the log free of one line per request
    built = {}
    for name, st in sources.items():
        db = Database(st.db_path)
        built[name] = (st, db, Collector(st, CboeProvider(st) if name == "cboe" else MassiveProvider(st), db))
    ps, pdb, pcol = built[default]
    seed_events(pdb)
    app = create_app(ps, pdb, pcol, extra_sources={k: v for k, v in built.items() if k != default}, source_notes=notes)
    return s, app, [v[2] for v in built.values()]


def probe(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


def lan_ip():
    """This PC's address on the local network, for the phone URL."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("10.255.255.255", 1))
            return sk.getsockname()[0]
    except OSError:
        return None


def port_open(host: str, port: int) -> bool:
    with socket.socket() as sk:
        sk.settimeout(0.5)
        return sk.connect_ex((probe(host), port)) == 0


def is_ours(host: str, port: int) -> bool:
    """True if the program on that port is this dashboard (its health endpoint answers)."""
    try:
        r = httpx.get(f"http://{probe(host)}:{port}/api/health", timeout=2)
        return r.status_code == 200 and r.json().get("ok") is True
    except (httpx.HTTPError, ValueError):
        return False


def choose_port(host: str, port: int):
    """Returns (port, already_running). Never raises the 'address already in use' error."""
    if not port_open(host, port):
        return port, False
    if is_ours(host, port):
        return port, True
    for p in range(port + 1, port + 21):
        if not port_open(host, p):
            return p, False
    raise RuntimeError(f"Ports {port} to {port + 20} are all busy. Close other programs or set PORT in .env.")


def main():
    _d, _src, _n = load_sources()
    problem = exposure_problem(_src[_d].host, _src[_d].access_password)
    if problem:
        print("\n" + problem + "\n")
        return 1
    s, app, collectors = build()
    try:
        port, running = choose_port(s.host, s.port)
    except RuntimeError as e:
        print(f"\n{e}\n")
        return 1
    url = f"http://127.0.0.1:{port}"
    if running:
        print(f"\nThe dashboard is already running at {url}. Opening it now.\n"
              "(To restart it, close the other black window or run stop.bat, then start again.)\n")
        if "--no-browser" not in sys.argv:
            webbrowser.open(url)
        return 0
    if port != s.port:
        print(f"\nPort {s.port} is used by another program, so this run uses port {port} instead.")
    for c in collectors:
        c.start()
    print("Data sources running: " + ", ".join(c.s.provider for c in collectors))
    print(f"\nDashboard on this PC: http://127.0.0.1:{port}")
    if s.host not in LOOPBACK:
        ip = lan_ip()
        print(f"Phone or tablet on the same Wi-Fi: http://{ip or '<this PC address>'}:{port}  (password required)")
    print("It opens in your browser in a few seconds. Press Ctrl+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(4.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=s.host, port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
