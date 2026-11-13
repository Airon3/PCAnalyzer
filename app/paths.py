"""Percorsi: risorse incluse nell'app e cartella dati utente scrivibile."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PCAnalyzer"


def resource_dir() -> Path:
    """Cartella 'data' inclusa (funziona anche dentro l'exe PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "data"


def asset_path(name: str) -> Path:
    """File nella cartella 'assets' (icona), anche dentro l'exe."""
    return resource_dir().parent / "assets" / name


def user_dir() -> Path:
    if sys.platform.startswith("win"):
        root = Path(os.environ.get("APPDATA", Path.home()))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = root / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_file(name: str) -> Path:
    """File nella cartella utente; al primo avvio viene copiato da quello incluso."""
    p = user_dir() / name
    if not p.exists() and (resource_dir() / name).exists():
        shutil.copy(resource_dir() / name, p)
    return p


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


# ------------------------------------------------------------------ impostazioni
DEFAULT_SETTINGS = {
    "anthropic_api_key": "",
    "ai_model": "claude-sonnet-5-5",
    "prices_url": "",            # URL di un prices.json remoto (es. raw GitHub)
    "appearance": "dark",
    "speedtest_engine": "cloudflare",   # cloudflare | ookla
    "update_repo": "",           # utente/nome del repository GitHub (vuoto = quello in version.json)
    "update_branch": "",
    "check_updates": True,       # controlla gli aggiornamenti all'avvio
    "skip_version": "",          # versione che l'utente ha scelto di ignorare
}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    s.update(load_json(user_dir() / "settings.json", {}) or {})
    if not s.get("anthropic_api_key"):
        s["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
    return s


def save_settings(s: dict) -> None:
    save_json(user_dir() / "settings.json", s)
