"""Desktop notifications and alert sounds. The desktop app sets SENDER (a tray notification) at start-up; without it (a plain
browser or tests) only the in-app banner shows. Three sounds, one per tier, so you can tell them apart without looking:
  2 = GEX levels changed, 1 = another important level (HOD/LOD, stack zone, top setup), 0 = any other level."""
from __future__ import annotations
import logging
import subprocess
import sys
import threading

log = logging.getLogger("notify")
SENDER = None          # callable(title, body) set by the desktop app
MAC_SOUNDS = {2: "Glass", 1: "Hero", 0: "Pop"}
WIN_SOUNDS = {2: "SystemExclamation", 1: "SystemQuestion", 0: "SystemAsterisk"}


def available() -> bool:
    return SENDER is not None


def play(tier: int):
    def run():
        try:
            if sys.platform == "darwin":
                subprocess.run(["afplay", f"/System/Library/Sounds/{MAC_SOUNDS.get(tier, 'Pop')}.aiff"], timeout=10, check=False)
            elif sys.platform.startswith("win"):
                import winsound
                winsound.PlaySound(WIN_SOUNDS.get(tier, "SystemAsterisk"), winsound.SND_ALIAS)
                if tier == 2:                                   # GEX: the same sound twice, so it stands out
                    winsound.PlaySound(WIN_SOUNDS[2], winsound.SND_ALIAS)
        except Exception:
            log.debug("could not play the alert sound", exc_info=True)
    threading.Thread(target=run, daemon=True).start()


def send(title: str, body: str, tier: int = 0, sound: bool = True, popup: bool = True):
    if SENDER is None:
        return False
    if popup:
        try:
            SENDER(title, body)
        except Exception:
            log.exception("desktop notification failed")
    if sound:
        play(tier)
    return True
