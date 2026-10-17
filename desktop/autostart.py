"""Start with Windows: one value under HKCU\\...\\Run (no admin rights needed). The installer and the tray menu use the same value."""
from __future__ import annotations
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "NQ-ES Options"
LEGACY_TASK = "NQ-ES Options Analytics"          # the scheduled task made by the old install_autostart.bat


def command() -> str:
    return f'"{sys.executable}" --background'


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, NAME)[0])
    except OSError:
        return False


def set_enabled(on: bool):
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
    """After an update the program may sit in the same place, but re-write the value so it always points at this exe."""
    if is_enabled():
        set_enabled(True)


def remove_legacy_task() -> bool:
    """Removes the old .bat autostart so the old version does not also start at sign-in. Silent if it is not there."""
    if sys.platform != "win32":
        return False
    r = subprocess.run(["schtasks", "/Delete", "/TN", LEGACY_TASK, "/F"], capture_output=True, creationflags=0x08000000)   # no console window
    return r.returncode == 0
