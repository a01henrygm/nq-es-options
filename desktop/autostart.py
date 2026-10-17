"""Start the app when you sign in, in the background (tray / menu bar only).

Windows: one value under HKCU\\...\\Run (no admin rights needed). The installer and the tray menu use the same value.
Mac: a login item file in ~/Library/LaunchAgents that starts the app with --background when you log in.
"""
from __future__ import annotations
import plistlib
import subprocess
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "NQ-ES Options"
LEGACY_TASK = "NQ-ES Options Analytics"          # the scheduled task made by the old install_autostart.bat
MAC_LABEL = "com.qdata.app"


def label() -> str:
    """The tray / menu bar wording."""
    return "Open at login" if sys.platform == "darwin" else "Start with Windows"


def command() -> str:
    return f'"{sys.executable}" --background'


def mac_plist_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"


def mac_plist(executable: str) -> bytes:
    return plistlib.dumps({"Label": MAC_LABEL, "ProgramArguments": [executable, "--background"], "RunAtLoad": True,
                           "ProcessType": "Interactive", "LimitLoadToSessionType": "Aqua"})


def is_enabled() -> bool:
    if sys.platform == "darwin":
        return mac_plist_path().exists()
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, NAME)[0])
    except OSError:
        return False


def set_enabled(on: bool):
    if sys.platform == "darwin":
        p = mac_plist_path()
        if on:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(mac_plist(sys.executable))       # macOS reads it at the next login; nothing to load now
        else:
            p.unlink(missing_ok=True)
        return
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, NAME)
            except FileNotFoundError:
                pass


def refresh_path():
    """After an update the program may sit in the same place, but re-write the entry so it always points at this program."""
    if is_enabled():
        set_enabled(True)


def remove_legacy_task() -> bool:
    """Removes the old .bat autostart so the old version does not also start at sign-in. Silent if it is not there."""
    if sys.platform != "win32":
        return False
    r = subprocess.run(["schtasks", "/Delete", "/TN", LEGACY_TASK, "/F"], capture_output=True, creationflags=0x08000000)   # no console window
    return r.returncode == 0
