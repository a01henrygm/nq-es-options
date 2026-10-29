"""Q DATA as a desktop app (Windows and Mac): its own window, an icon in the system tray (Windows) or menu bar (Mac),
start at sign-in, and self-update.

The dashboard server is the same one the .bat files start; it runs inside this program on 127.0.0.1 and the window shows it.
Closing the window only hides it (data collection keeps running). Quit from the tray / menu bar icon to stop everything.
Run with --smoke-test to start everything, check the dashboard answers, and quit (exit code 0 = OK); the Mac build uses it.
"""
from __future__ import annotations
import logging
import os
import sys
import threading
import time
import json
import re
from datetime import datetime
from pathlib import Path

from backend.config import DATA, FROZEN, ROOT, ensure_data_dir

APP_NAME = "Q DATA"

from pydantic import BaseModel  # noqa: E402


class NewWindowIn(BaseModel):
    tab: str = ""        # which page the new window opens on
    u: str = ""          # which symbol
class SaveFileIn(BaseModel):
    name: str            # file name the page asked for, e.g. qdata_stack_map_NDX.pine
    text: str


def downloads_folder() -> Path:
    """The user's Downloads folder (Windows and Mac), or the home folder if there is none."""
    if os.environ.get("QDATA_SAVE_DIR"):                  # tests / the smoke test save somewhere harmless
        return Path(os.environ["QDATA_SAVE_DIR"])
    d = Path.home() / "Downloads"
    return d if d.is_dir() else Path.home()


def save_download(name: str, text: str, folder: Path | None = None) -> Path:
    """Saves a file the page made (an indicator, a CSV) into Downloads. The app window cannot do browser-style downloads, so the page
    sends the text here. A safe file name is kept; an existing file of the same name is not overwritten (name (2).pine, ...)."""
    folder = folder or downloads_folder()
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", Path(name or "qdata.txt").name).strip(" .") or "qdata.txt"
    stem, ext = os.path.splitext(base)
    p, n = folder / base, 2
    while p.exists():
        p = folder / f"{stem} ({n}){ext}"
        n += 1
    p.write_text(text, encoding="utf-8", newline="\n")
    return p


def set_clipboard(text: str) -> bool:
    """Put text on the system clipboard (Windows: the Win32 clipboard API, Unicode; Mac: pbcopy). True when it worked."""
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            u32.OpenClipboard.argtypes, u32.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
            u32.SetClipboardData.argtypes, u32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE
            k32.GlobalAlloc.argtypes, k32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HGLOBAL
            k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HGLOBAL], wintypes.LPVOID
            k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
            k32.GlobalFree.argtypes = [wintypes.HGLOBAL]
            data = (text.replace("\r\n", "\n").replace("\n", "\r\n") + "\0").encode("utf-16-le")
            for _ in range(10):                         # another program may hold the clipboard for a moment
                if u32.OpenClipboard(None):
                    break
                time.sleep(0.05)
            else:
                return False
            try:
                u32.EmptyClipboard()
                h = k32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
                if not h:
                    return False
                ptr = k32.GlobalLock(h)
                ctypes.memmove(ptr, data, len(data))
                k32.GlobalUnlock(h)
                if not u32.SetClipboardData(13, h):     # CF_UNICODETEXT; on success the clipboard owns the memory
                    k32.GlobalFree(h)
                    return False
                return True
            finally:
                u32.CloseClipboard()
        if sys.platform == "darwin":
            try:                                        # the Mac pasteboard directly; pbcopy below if that is not possible
                import AppKit
                pb = AppKit.NSPasteboard.generalPasteboard()
                pb.clearContents()
                if pb.setString_forType_(text, AppKit.NSPasteboardTypeString):
                    return True
            except Exception:
                logging.exception("clipboard (pasteboard)")
            import subprocess
            env = {**os.environ, "LANG": os.environ.get("LANG") or "en_US.UTF-8"}     # an app started from Finder has no LANG; pbcopy needs it for UTF-8
            subprocess.run(["/usr/bin/pbcopy"], input=text.encode("utf-8"), check=True, timeout=5, env=env)
            return True
    except Exception:
        logging.exception("clipboard")
    return False


def reveal(p: Path):
    """Show the saved file in Explorer / Finder. Never fails the save."""
    if os.environ.get("QDATA_NO_REVEAL"):
        return
    try:
        import subprocess
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(p)])
        elif sys.platform == "darwin":
            subprocess.Popen(["/usr/bin/open", "-R", str(p)])
    except Exception:
        pass


CHECK_EVERY = 4 * 3600                     # seconds between update checks
MAC = sys.platform == "darwin"
TRAY = "menu bar" if MAC else "tray"
log = logging.getLogger("desktop")


def _quiet_streams():
    """A windowed program has no console: give print() and the web server somewhere to write."""
    if sys.stdout is None or sys.stderr is None:
        f = open(DATA / "logs" / "desktop.log", "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def _single_instance() -> object | None:
    """Returns a handle while we are the only copy running, None if another copy already runs."""
    if sys.platform != "win32":
        import fcntl
        f = open(DATA / "desktop.lock", "a+")
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)        # released by the system when this copy exits
        except OSError:
            f.close()
            return None
        return f
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


def _on_main(fn):
    """Mac only lets the main thread touch the menu bar: hand the change over to it. Elsewhere just run it."""
    if not MAC:
        return fn()
    from PyObjCTools import AppHelper
    AppHelper.callAfter(fn)


def _open_folder(path: Path):
    if hasattr(os, "startfile"):
        os.startfile(str(path))
    elif MAC:
        import subprocess
        subprocess.Popen(["open", str(path)])


def _mac_add_edit_menu():
    """Mac: give the menu bar a standard Edit menu (Undo, Redo, Cut, Copy, Paste, Select All). Without it Cmd+C / Cmd+V / Cmd+A do
    nothing in the window: the window library's own shortcut handling does not work with the Mac web view. The items send the
    standard actions to whatever has focus, exactly like any Mac app. Safe to call more than once."""
    import AppKit
    app = AppKit.NSApplication.sharedApplication()
    main = app.mainMenu()
    if main is None:
        main = AppKit.NSMenu.alloc().init()
        app.setMainMenu_(main)
    for i in range(main.numberOfItems()):
        if main.itemAtIndex_(i).title() == "Edit":
            return False
    edit = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    for title, action, key, shift in (("Undo", "undo:", "z", False), ("Redo", "redo:", "z", True), (None, None, None, False),
                                      ("Cut", "cut:", "x", False), ("Copy", "copy:", "c", False), ("Paste", "paste:", "v", False),
                                      ("Select All", "selectAll:", "a", False)):
        if title is None:
            edit.addItem_(AppKit.NSMenuItem.separatorItem())
            continue
        item = edit.addItemWithTitle_action_keyEquivalent_(title, action, key)
        if shift:
            item.setKeyEquivalentModifierMask_(AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagShift)
    holder = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Edit", None, "")
    holder.setSubmenu_(edit)
    main.insertItem_atIndex_(holder, min(1, main.numberOfItems()))
    return True


def _mac_watch_system(on_power_off, on_activate):
    """Mac: quit cleanly when you shut down or log out (the window would otherwise refuse and stop the logout), and show the
    window when you click the Dock icon or open the app again while it runs hidden."""
    import AppKit
    import objc

    class QDataSystemWatcher(AppKit.NSObject):
        def powerOff_(self, _note):
            on_power_off()

        def activated_(self, _note):
            on_activate()

    w = QDataSystemWatcher.alloc().init()
    AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
        w, objc.selector(w.powerOff_, signature=b"v@:@"), AppKit.NSWorkspaceWillPowerOffNotification, None)
    AppKit.NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        w, objc.selector(w.activated_, signature=b"v@:@"), AppKit.NSApplicationDidBecomeActiveNotification, None)
    return w


def _icon_image():
    from PIL import Image
    for p in (ROOT / "assets" / "icon.png", ROOT / "assets" / "icon.ico"):
        if p.exists():
            return Image.open(p)
    return Image.new("RGB", (64, 64), "#2f8bf5")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    smoke = "--smoke-test" in argv
    background = "--background" in argv and not smoke
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
    os.environ["NQES_PORT"] = str(port)
    url = f"http://127.0.0.1:{port}"
    started = time.time()
    show_ev, quitting = threading.Event(), threading.Event()
    state = {"window": None, "icon": None, "visible": not background, "exit": 0}

    # ---- updates ----------------------------------------------------------------------------------------------------
    def changed(u):
        ic = state["icon"]
        if ic:
            _on_main(ic.update_menu)
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

    def restart():
        """Starts a fresh copy a moment after this one has quit (used after changing settings such as phone access)."""
        import subprocess
        can = FROZEN and sys.platform in ("win32", "darwin")
        if sys.platform == "win32" and FROZEN:
            exe = sys.executable
            subprocess.Popen(["cmd", "/c", f'timeout /t 3 /nobreak >nul & start "" "{exe}"'], creationflags=0x08000000 | 0x00000008, close_fds=True)
        elif MAC and FROZEN:
            from desktop.updater import mac_app_bundle
            bundle = mac_app_bundle()
            if bundle:
                subprocess.Popen(["/bin/sh", "-c", 'sleep 3; open -n "$0"', str(bundle)], start_new_session=True, close_fds=True)
            can = bool(bundle)
        threading.Timer(0.3, quit_app).start()
        return {"ok": True, "restarting": can}

    def install_now():
        if upd.state not in ("ready", "available"):
            return {"ok": False, "reason": "No update downloaded yet."}
        threading.Thread(target=install_and_quit, daemon=True).start()
        return {"ok": True}

    extra = []

    def new_window(w: NewWindowIn):
        """Another dashboard window in the same app (same server and data), opened on the page you were on."""
        from urllib.parse import urlencode
        n = len(extra) + 2
        q = urlencode({"w": n, "tab": re.sub(r"[^a-z]", "", w.tab or "")[:20], "u": re.sub(r"[^A-Za-z0-9_:]", "", w.u or "")[:20]})
        extra.append(webview.create_window(f"{APP_NAME} ({n})", url=f"{url}/?{q}", width=1280, height=860, min_size=(700, 500),
                                           text_select=True, background_color="#0b0d10"))
        return {"ok": True, "window": n}

    def save_file(f: SaveFileIn):
        if len(f.text) > 20_000_000:
            return {"ok": False, "reason": "File too large."}
        try:
            p = save_download(f.name, f.text)
        except OSError as e:
            return {"ok": False, "reason": str(e)}
        reveal(p)
        return {"ok": True, "path": str(p), "folder": str(p.parent), "name": p.name}

    def copy(f: SaveFileIn):
        if len(f.text) > 20_000_000:
            return {"ok": False, "reason": "Too large."}
        return {"ok": set_clipboard(f.text)}

    for path, fn, method in (("/api/desktop/copy", copy, "POST"), ("/api/desktop/save-file", save_file, "POST"), ("/api/desktop/info", info, "GET"), ("/api/desktop/show", show, "POST"), ("/api/desktop/new-window", new_window, "POST"),
                             ("/api/desktop/update/check", check_now, "POST"), ("/api/desktop/update/install", install_now, "POST"),
                             ("/api/desktop/restart", restart, "POST")):
        app.router.routes.insert(0, APIRoute(path, fn, methods=[method]))          # in front of the page files mounted at /

    # ---- server -----------------------------------------------------------------------------------------------------
    server = uvicorn.Server(uvicorn.Config(app, host=s.host, port=port, log_level="warning", log_config=None))

    def start_server():
        threading.Thread(target=server.run, name="server", daemon=True).start()
        for _ in range(150):
            if port_open(host, port):
                break
            time.sleep(0.1)
        for c in collectors:
            c.start()
        getattr(app.state, "start_tv_tracker", lambda: None)()
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
        threading.Timer(1.5, lambda: os._exit(state["exit"])).start()
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
        _on_main(state["icon"].update_menu)

    menu = pystray.Menu(
        pystray.MenuItem("Open", open_window, default=True),
        pystray.MenuItem(f"Version {__version__}", None, enabled=False),
        pystray.MenuItem(update_label, update_click, enabled=lambda i: upd.enabled and upd.state not in ("checking", "downloading")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(autostart.label(), toggle_autostart, checked=lambda i: autostart.is_enabled()),
        pystray.MenuItem("Open settings folder (.env, data, logs)", lambda *_: _open_folder(DATA)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit (stops data collection)", quit_app),
    )
    icon = pystray.Icon("nqes", _icon_image(), APP_NAME, menu)
    state["icon"] = icon
    icon.run_detached()
    try:                                                     # level-change alerts from the TradingView tracker show as tray notifications
        from backend import notify as _notify
        _notify.SENDER = lambda title, body: icon.notify(body[:250], title[:60])
    except Exception:
        log.exception("could not hook up level alerts")

    # ---- window -----------------------------------------------------------------------------------------------------
    from desktop.splash import splash_html
    splash = None if background else webview.create_window("Q DATA", html=splash_html(__version__), width=440, height=320, frameless=True,
                                                            resizable=False, on_top=True, background_color="#05070b")
    win = webview.create_window(APP_NAME, html="<body style='background:#0b0d10'></body>", width=1440, height=920, min_size=(900, 600),
                                hidden=True, text_select=True, background_color="#0b0d10")
    state["window"] = win

    def boot():
        """Behind the loading window: start the server and data collection, load the dashboard, then swap windows."""
        t0 = time.time()
        say = (lambda t: splash.evaluate_js(f"setStatus({t!r})")) if splash else (lambda t: None)
        try:
            say("Starting the data server...")
            start_server()
            say("Starting data collection...")
            win.load_url(url)
            say("Loading your dashboard...")
            time.sleep(max(0.0, 1.8 - (time.time() - t0)))           # long enough to read, never slower than the start itself
        except Exception:
            log.exception("start-up problem")
        if not background:
            win.show()
            state["visible"] = True
        if splash:
            splash.destroy()

    def on_closing():
        if quitting.is_set():
            return True
        win.hide()                                  # closing the window keeps the app running in the tray
        state["visible"] = False
        if not getattr(on_closing, "told", False):
            on_closing.told = True
            try:
                icon.notify(f"Still running in the {TRAY}, collecting data. Use the {TRAY} icon to quit." if MAC else
                            "Still running in the tray, collecting data. Right-click the tray icon to quit.", APP_NAME)
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

    def smoke_check():
        """--smoke-test: wait for the dashboard to answer, write the result to smoke.json, quit with exit code 0 or 1."""
        import httpx
        ok, detail = False, "no answer"
        for _ in range(90):
            try:
                r = httpx.get(f"{url}/api/desktop/info", timeout=3)
                ok, detail = r.status_code == 200 and r.json().get("desktop") is True, f"HTTP {r.status_code}"
                if ok:
                    break
            except Exception as e:
                detail = str(e)[:200]
            time.sleep(1)
        extra = {}
        if ok:                                              # the indicator buttons: copy, save to Downloads, and the indicator endpoints
            try:
                probe = "Q DATA copy test \u00b1 \u2713"
                r = httpx.post(f"{url}/api/desktop/copy", json={"name": "", "text": probe}, timeout=10).json()
                got = None
                if MAC:
                    import subprocess
                    got = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, timeout=5,
                                         env={**os.environ, "LANG": "en_US.UTF-8"}).stdout.decode("utf-8")
                extra["copy"] = bool(r.get("ok")) and (got is None or got == probe)
                r = httpx.post(f"{url}/api/desktop/save-file", json={"name": "qdata_smoke.pine", "text": "//@version=6"}, timeout=10).json()
                extra["save"] = bool(r.get("ok")) and Path(r["path"]).read_text() == "//@version=6"
                r = httpx.get(f"{url}/api/export/tab-pine/tabs", timeout=10)
                extra["indicators"] = r.status_code == 200 and len(r.json()["tabs"]) >= 14
            except Exception as e:
                extra["error"] = str(e)[:200]
            if os.environ.get("QDATA_SMOKE_STRICT") and not all(extra.get(k) for k in ("copy", "save", "indicators")):
                ok, detail = False, f"indicator features failed: {extra}"
        time.sleep(3)                                       # let the window and the tray / menu bar icon settle
        if MAC:                                             # the Edit menu that makes Cmd+C / Cmd+V / Cmd+A work in the window
            seen, got_menu = threading.Event(), {}

            def look():
                try:
                    import AppKit
                    m = AppKit.NSApplication.sharedApplication().mainMenu()
                    got_menu["ok"] = m is not None and any(m.itemAtIndex_(i).title() == "Edit" for i in range(m.numberOfItems()))
                finally:
                    seen.set()
            time.sleep(3)
            _on_main(look)
            seen.wait(10)
            extra["edit_menu"] = bool(got_menu.get("ok"))
            if os.environ.get("QDATA_SMOKE_STRICT") and ok and not extra["edit_menu"]:
                ok, detail = False, "the Edit menu is missing on Mac"
        (DATA / "smoke.json").write_text(json.dumps({"ok": ok, "detail": detail, "version": __version__, "tray": state["icon"] is not None, **extra,
                                                     "platform": sys.platform}))
        log.info("smoke test %s (%s)", "passed" if ok else "FAILED", detail)
        state["exit"] = 0 if ok else 1
        _on_main(quit_app) if MAC else quit_app()

    def add_edit_menu():
        try:
            _mac_add_edit_menu()
        except Exception:
            log.exception("could not add the Edit menu")

    def edit_menu_later():
        for wait in (1.0, 4.0):                             # after the window library has set up its own menus at first show
            time.sleep(wait)
            _on_main(add_edit_menu)

    def after_start():
        if MAC:
            threading.Thread(target=edit_menu_later, daemon=True).start()
        threading.Thread(target=boot, daemon=True).start()
        threading.Thread(target=watch_show, daemon=True).start()
        if smoke:
            threading.Thread(target=smoke_check, daemon=True).start()
        else:
            threading.Thread(target=update_loop, daemon=True).start()

    if MAC:
        def on_activate():
            if not state["visible"] and not quitting.is_set() and time.time() - started > 5:
                show_ev.set()
        try:
            state["watcher"] = _mac_watch_system(quit_app, on_activate)
        except Exception:
            log.exception("could not watch for shutdown / Dock clicks")

    webview.settings["ALLOW_DOWNLOADS"] = True
    (DATA / "webview").mkdir(exist_ok=True)
    webview.start(after_start, private_mode=False, storage_path=str(DATA / "webview"))   # keeps your page settings between runs
    quit_app()
    return state["exit"]
