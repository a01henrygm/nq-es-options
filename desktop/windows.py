"""Which Q DATA windows are open and which page each one shows, kept in windows.json in the data folder (1.33.0).

When the app quits (tray > Quit, an update restart, shutting down the computer) the list stays as it was, so the next start opens
the same extra windows on the same pages, and the main window on the page it was last on. Closing an extra window yourself while
the app keeps running removes it from the list. Pure logic with a file, no window library, so it can be tested anywhere.
"""
from __future__ import annotations
import json
import re
import threading
from pathlib import Path

MAX_EXTRA = 8


def clean_tab(t) -> str:
    return re.sub(r"[^a-z]", "", str(t or ""))[:20]


def clean_u(u) -> str:
    return re.sub(r"[^A-Za-z0-9_:]", "", str(u or ""))[:20]


class WindowStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.main = {"tab": "", "u": ""}
        self.extra: list[dict] = []
        try:
            j = json.loads(self.path.read_text(encoding="utf-8"))
            m = j.get("main") or {}
            self.main = {"tab": clean_tab(m.get("tab")), "u": clean_u(m.get("u"))}
            seen = set()
            for w in j.get("extra") or []:
                n = int(w.get("n") or 0)
                if n >= 2 and n not in seen and len(self.extra) < MAX_EXTRA:
                    seen.add(n)
                    self.extra.append({"n": n, "tab": clean_tab(w.get("tab")), "u": clean_u(w.get("u"))})
        except (OSError, ValueError, TypeError, AttributeError):
            pass                                              # no file yet, or a damaged one: start fresh

    def _save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"main": self.main, "extra": self.extra}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def next_number(self) -> int:
        used = {w["n"] for w in self.extra}
        n = 2
        while n in used:
            n += 1
        return n

    def add(self, tab, u, n: int | None = None) -> dict | None:
        with self.lock:
            if len(self.extra) >= MAX_EXTRA:
                return None
            n = n or self.next_number()
            w = next((x for x in self.extra if x["n"] == n), None)
            if w is None:
                w = {"n": n, "tab": clean_tab(tab), "u": clean_u(u)}
                self.extra.append(w)
            self._save()
            return dict(w)

    def remove(self, n: int):
        with self.lock:
            self.extra = [w for w in self.extra if w["n"] != n]
            self._save()

    def update(self, which, tab, u) -> bool:
        """which: 'main' or the extra window's number. Called by each page whenever it shows a page."""
        tab, u = clean_tab(tab), clean_u(u)
        with self.lock:
            if str(which) in ("", "main", "1"):
                target = self.main
            else:
                try:
                    n = int(which)
                except (TypeError, ValueError):
                    return False
                target = next((w for w in self.extra if w["n"] == n), None)
                if target is None:
                    return False
            if tab:
                target["tab"] = tab
            if u:
                target["u"] = u
            self._save()
            return True

    def to_restore(self) -> list[dict]:
        with self.lock:
            return [dict(w) for w in self.extra]
