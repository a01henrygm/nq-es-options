"""Configuration. Secrets are read from the backend-only .env file and never sent to the browser."""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

import sys

# ROOT: where the program files are (the page, the indicator). DATA: where your settings (.env), database and logs live.
# Run from the project folder both are that folder. In the installed desktop app the program folder is replaced by every
# update, so your own files live in %LOCALAPPDATA%\NQ-ES Options (Windows) or ~/Library/Application Support/Q DATA (Mac)
# instead and survive updates.
FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def installed_data_dir(platform: str = sys.platform, env=os.environ, home: Path | None = None) -> Path:
    home = home or Path.home()
    if platform == "darwin":
        return home / "Library" / "Application Support" / "Q DATA"
    return Path(env.get("LOCALAPPDATA") or home) / "NQ-ES Options"


DATA = Path(os.environ.get("NQES_DATA_DIR") or (installed_data_dir() if FROZEN else ROOT))


def ensure_data_dir() -> Path:
    """Creates the data folder with a default .env (Cboe data, no key needed) the first time."""
    for sub in ("", "data", "logs"):
        (DATA / sub).mkdir(parents=True, exist_ok=True)
    env, example = DATA / ".env", ROOT / ".env.example"
    if not env.exists() and example.exists():
        env.write_text(example.read_text())
    return DATA


@dataclass(frozen=True)
class Settings:
    provider: str = "cboe"                                   # cboe (free, no key) or massive (needs a paid options plan)
    api_key: str | None = field(default=None, repr=False)  # repr=False keeps the key out of logs
    cboe_base_url: str = "https://cdn.cboe.com/api/global/delayed_quotes/options"
    base_url: str = "https://api.massive.com"
    options_plan: str = "delayed"
    max_rpm: int = 60
    poll_seconds: int = 60
    underlyings: tuple = ("_NDX", "_SPX")
    max_dte: int = 30
    strike_window: float = 0.12
    futures_contracts: dict = field(default_factory=lambda: {"NQ": "NQZ6", "ES": "ESZ6"})
    db_path: Path = DATA / "data" / "analytics.db"
    host: str = "127.0.0.1"
    port: int = 8000
    retention_snapshots: int = 150
    access_password: str | None = field(default=None, repr=False)   # never printed
    access_local_bypass: bool = True

    @property
    def requires_key(self) -> bool:
        return self.provider == "massive"

    @property
    def key_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "YOUR_API_KEY_HERE"


PROVIDER_NAMES = ("cboe", "massive")
LABELS = {"cboe": "Cboe (free, about 15 min delayed)", "massive": "Massive / Polygon (your key)"}


def _listify(v) -> tuple:
    return tuple(u.strip().upper() for u in str(v).split(",") if u.strip())


def _settings_for(provider: str, env, default_provider: str) -> Settings:
    g = lambda k, d: (env.get(k) or d)
    legacy = env.get("UNDERLYINGS") if provider == default_provider else None      # old single-source setting
    base_db = Path(g("DB_PATH", "data/analytics.db"))
    base_db = base_db if base_db.is_absolute() else DATA / base_db
    if provider == "cboe":
        unders = _listify(g("CBOE_UNDERLYINGS", legacy or "_NDX,_SPX"))
        plan, poll = "delayed", max(60, int(g("POLL_SECONDS", 120)))
        db_path = base_db
    else:
        unders = _listify(g("MASSIVE_UNDERLYINGS", legacy or "QQQ,SPY"))
        plan = str(g("MASSIVE_OPTIONS_PLAN", "delayed")).lower()
        if plan not in ("delayed", "realtime"):
            raise ValueError("MASSIVE_OPTIONS_PLAN must be 'delayed' or 'realtime'")
        poll = max(5, int(g("MASSIVE_POLL_SECONDS", g("POLL_SECONDS", 60) if default_provider == "massive" else 60)))
        db_path = base_db.with_name(base_db.stem + "_massive" + base_db.suffix)
    return Settings(
        provider=provider,
        cboe_base_url=str(g("CBOE_BASE_URL", "https://cdn.cboe.com/api/global/delayed_quotes/options")).rstrip("/"),
        api_key=env.get("MASSIVE_API_KEY") or None,
        base_url=str(g("MASSIVE_BASE_URL", "https://api.massive.com")).rstrip("/"),
        options_plan=plan, max_rpm=max(1, int(g("MASSIVE_MAX_RPM", 60))), poll_seconds=poll, underlyings=unders,
        max_dte=int(g("MAX_DTE", 30)), strike_window=float(g("STRIKE_WINDOW", 0.12)),
        futures_contracts={"NQ": str(g("NQ_CONTRACT", "NQZ6")).upper(), "ES": str(g("ES_CONTRACT", "ESZ6")).upper()},
        db_path=db_path, host=str(g("HOST", "127.0.0.1")), port=int(g("PORT", 8000)),
        retention_snapshots=int(g("RETENTION_SNAPSHOTS", 150)),
        access_password=(env.get("ACCESS_PASSWORD") or "").strip() or None,
        access_local_bypass=str(g("ACCESS_LOCAL_BYPASS", "1")).strip() not in ("0", "false", "no"))


def _default_provider(env) -> str:
    d = str(env.get("DEFAULT_PROVIDER") or env.get("PROVIDER") or "cboe").lower()
    if d not in PROVIDER_NAMES:
        raise ValueError("DEFAULT_PROVIDER must be 'cboe' or 'massive'")
    return d


def load_settings(env: dict | None = None) -> Settings:
    """Settings of the default data source (kept for simple callers and tests)."""
    if env is None:
        load_dotenv(DATA / ".env")
        env = os.environ
    d = _default_provider(env)
    return _settings_for(d, env, d)


def load_sources(env: dict | None = None):
    """Returns (default_name, {name: Settings} for every provider listed in PROVIDERS, notes about disabled ones)."""
    if env is None:
        load_dotenv(DATA / ".env")
        env = os.environ
    default = _default_provider(env)
    names = [n for n in _listify(env.get("PROVIDERS") or "cboe,massive") if n.lower() in PROVIDER_NAMES]
    names = [n.lower() for n in names]
    if default not in names:
        names.insert(0, default)
    out, notes = {}, []
    for n in dict.fromkeys(names):
        st = _settings_for(n, env, default)
        if st.requires_key and not st.key_configured:
            notes.append({"name": n, "label": LABELS[n], "enabled": False, "reason": "No MASSIVE_API_KEY in your .env file yet."})
        else:
            out[n] = st
            notes.append({"name": n, "label": LABELS[n], "enabled": True, "reason": ""})
    if default not in out:                       # default source unusable: fall back to the first working one
        default = next(iter(out), default)
    return default, out, notes
