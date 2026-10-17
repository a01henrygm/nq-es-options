"""NQ-ES Options as a Windows desktop app: its own window, an icon in the system tray, start with Windows, and self-update.

The dashboard server is the same one the .bat files start; it runs inside this program on 127.0.0.1 and the window shows it.
Closing the window only hides it (data collection keeps running). Quit from the tray icon to stop everything.
"""
from __future__ import annotations
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from backend.config import DATA, ROOT, ensure_data_dir

APP_NAME = "NQ-ES Options"
CHECK_EVERY = 4 * 3600                     # seconds between update checks
log = logging.getLogger("desktop")


def _quiet_streams():
    """A windowed program has no console: give print() and the web server somewhere to write."""
    if sys.stdout is None or sys.stderr is None:
        f = open(DATA / "logs" / "desktop.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _single_instance() -> object | None:
    """Returns a handle while we are the only copy running, None if another copy already runs (Windows only)."""
    if sys.platform != "win32":
        return object()
    import ctypes
    h = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\NQESOptionsDesktop")
    return None if ctypes.windll.kernel32.GetLastError() == 183 else h      # 183 = already exists


def _wake_other_copy():
    import httpx
    try:
        port = int((DATA / "desktop.port").read_text().strip())
        httpx.post(f"http://127.0.0.1:{port}/api/desktop/show", timeout=3)
    except Exception:
        pass


def _free_port(host: str, wanted: int) -> int:
    from backend.main import port_open
    for p in range(wanted, wanted + 40):
        if not port_open(host, p):
            return p
    raise RuntimeError(f"Ports {wanted} to {wanted + 39} are all busy.")


def _market_hours(now: datetime | None = None) -> bool:
    """Weekdays 08:30 to 16:30 Eastern: the app does not restart itself for an update in this window."""
    from zoneinfo import ZoneInfo
    t = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    return t.weekday() < 5 and (8, 30) <= (t.hour, t.minute) < (16, 30)


def _icon_image():
    from PIL import Image
    for p in (ROOT / "assets" / "icon.png", ROOT / "assets" / "icon.ico"):
        if p.exists():
            return Image.open(p)
    return Image.new("RGB", (64, 64), "#2f8bf5")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    background = "--background" in argv
    ensure_data_dir()
    _quiet_streams()
    os.environ.setdefault("NQES_DATA_DIR", str(DATA))

    mutex = _single_instance()
    if mutex is None:
        _wake_other_copy()
        return 0

    import uvicorn
    import webview
    import pystray
    from fastapi.routing import APIRoute
    from backend.main import build, port_open
    from backend.version import __version__
    from desktop import autostart
    from desktop.updater import Updater, settings_from_env

    s, app, collectors = build()
    first_run_marker = DATA / ".desktop_first_run_done"
    if not first_run_marker.exists():
        autostart.remove_legacy_task()            # the old .bat autostart would start a second, older copy at sign-in
        first_run_marker.write_text(__version__)
    autostart.refresh_path()

    host = "127.0.0.1" if s.host in ("0.0.0.0", "::", "") else s.host
    port = _free_port(s.host, s.port)
    (DATA / "desktop.port").write_text(str(port))
    url = f"http://127.0.0.1:{port}"
    started = time.time()
    show_ev, quitting = threading.Event(), threading.Event()
    state = {"window": None, "icon": None, "visible": not background}

    # ---- updates ----------------------------------------------------------------------------------------------------
    def changed(u):
        ic = state["icon"]
        if ic:
            ic.update_menu()
            if u.state == "ready" and u.latest:
                try:
                    ic.notify(f"Version {u.latest['version']} is ready. It installs when you restart the app, or by itself after the market closes.", APP_NAME)
                except Exception:
                    pass

    cfg = settings_from_env()
    upd = Updater(__version__, cfg["repo"], cfg["token"], cfg["auto"], DATA / "updates", on_change=changed)

    def install_and_quit():
        if upd.install(background=not state["visible"]):
            quit_app()

    def update_loop():
        time.sleep(8)
        while not quitting.is_set():
            st = upd.check()
            if st == "ready" and cfg["auto"]:
                just_started = time.time() - started < 180
                if just_started or not _market_hours():
                    install_and_quit()
                    return
            for _ in range(CHECK_EVERY if st != "ready" else 900):     # when one is ready, look again every 15 min for the market to close
                if quitting.is_set():
                    return
                time.sleep(1)

    # ---- routes the page uses inside the desktop app ----------------------------------------------------------------
    def info():
        return {"desktop": True, "version": __version__, "update": upd.info(), "autostart": autostart.is_enabled(), "data_folder": str(DATA)}

    def show():
        show_ev.set()
        return {"ok": True}

    def check_now():
        threading.Thread(target=upd.check, daemon=True).start()
        return {"ok": True}

    def install_now():
        if upd.state not in ("ready", "available"):
            return {"ok": False, "reason": "No update downloaded yet."}
        threading.Thread(target=install_and_quit, daemon=True).start()
        return {"ok": True}

    for path, fn, method in (("/api/desktop/info", info, "GET"), ("/api/desktop/show", show, "POST"),
                             ("/api/desktop/update/check", check_now, "POST"), ("/api/desktop/update/install", install_now, "POST")):
        app.router.routes.insert(0, APIRoute(path, fn, methods=[method]))          # in front of the page files mounted at /

    # ---- server -----------------------------------------------------------------------------------------------------
    server = uvicorn.Server(uvicorn.Config(app, host=s.host, port=port, log_level="warning", log_config=None))
    threading.Thread(target=server.run, name="server", daemon=True).start()
    for _ in range(100):
        if port_open(host, port):
            break
        time.sleep(0.1)
    for c in collectors:
        c.start()
    log.info("desktop app %s on %s", __version__, url)

    # ---- quitting ---------------------------------------------------------------------------------------------------
    def quit_app(*_):
        if quitting.is_set():
            return
        quitting.set()
        for c in collectors:
            try:
                c.stop()
            except Exception:
                pass
        server.should_exit = True
        if state["icon"]:
            state["icon"].stop()
        threading.Timer(1.5, lambda: os._exit(0)).start()
        if state["window"]:
            state["window"].destroy()

    # ---- tray icon --------------------------------------------------------------------------------------------------
    def open_window(*_):
        show_ev.set()

    def update_label(_item):
        st, v = upd.state, upd.latest and upd.latest["version"]
        if not upd.enabled:
            return "Updates: not set up"
        return {"ready": f"Restart to update to {v}", "available": f"Download and install {v}", "downloading": f"Downloading {v}... {int(upd.progress * 100)}%",
                "checking": "Checking for updates...", "error": "Update check failed: try again"}.get(st, "Check for updates")

    def update_click(*_):
        if upd.state in ("ready", "available"):
            threading.Thread(target=install_and_quit, daemon=True).start()
        else:
            threading.Thread(target=upd.check, daemon=True).start()

    def toggle_autostart(*_):
        autostart.set_enabled(not autostart.is_enabled())
        state["icon"].update_menu()

    menu = pystray.Menu(
        pystray.MenuItem("Open", open_window, default=True),
        pystray.MenuItem(f"Version {__version__}", None, enabled=False),
        pystray.MenuItem(update_label, update_click, enabled=lambda i: upd.enabled and upd.state not in ("checking", "downloading")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda i: autostart.is_enabled()),
        pystray.MenuItem("Open settings folder (.env, data, logs)", lambda *_: os.startfile(str(DATA)) if hasattr(os, "startfile") else None),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit (stops data collection)", quit_app),
    )
    icon = pystray.Icon("nqes", _icon_image(), APP_NAME, menu)
    state["icon"] = icon
    icon.run_detached()

    # ---- window -----------------------------------------------------------------------------------------------------
    win = webview.create_window(APP_NAME, url, width=1440, height=920, min_size=(900, 600), hidden=background, text_select=True)
    state["window"] = win

    def on_closing():
        if quitting.is_set():
            return True
        win.hide()                                  # closing the window keeps the app running in the tray
        state["visible"] = False
        if not getattr(on_closing, "told", False):
            on_closing.told = True
            try:
                icon.notify("Still running in the tray, collecting data. Right-click the tray icon to quit.", APP_NAME)
            except Exception:
                pass
        return False

    win.events.closing += on_closing

    def watch_show():
        while not quitting.is_set():
            if show_ev.wait(0.5):
                show_ev.clear()
                try:
                    win.show()
                    win.restore()
                    state["visible"] = True
                except Exception:
                    log.exception("could not show the window")

    def after_start():
        threading.Thread(target=watch_show, daemon=True).start()
        threading.Thread(target=update_loop, daemon=True).start()

    webview.settings["ALLOW_DOWNLOADS"] = True
    (DATA / "webview").mkdir(exist_ok=True)
    webview.start(after_start, private_mode=False, storage_path=str(DATA / "webview"))   # keeps your page settings between runs
    quit_app()
    return 0
