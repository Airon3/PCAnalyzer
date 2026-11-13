"""
Aggiornamento automatico dai sorgenti pubblicati su GitHub.

Funzionamento:
 1. legge `version.json` dal ramo del repository (raw.githubusercontent.com);
 2. se la versione remota è più recente scarica lo zip del ramo (codeload.github.com);
 3. salva una copia di backup dei file attuali in `_backup/<versione>`;
 4. sostituisce i file dell'app (impostazioni, prezzi e speed test restano in %APPDATA%);
 5. se `requirements.txt` è cambiato installa le nuove dipendenze;
 6. riavvia l'app.

Sulla copia di sviluppo (cartella con `.git`) non sovrascrive nulla: propone `git pull`.
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from . import __version__

ROOT = Path(__file__).resolve().parent.parent
# file e cartelle dell'app che l'aggiornamento può sostituire
MANAGED = ["app", "data", "assets", "tools", "main.py", "requirements.txt", "avvia.bat", "build_exe.bat",
           "pubblica_aggiornamento.bat", "README.md", "version.json", ".gitignore"]
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


class UpdateError(RuntimeError):
    pass


# --------------------------------------------------------------------------- versioni
def parse_version(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def local_info() -> dict:
    try:
        info = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        info = {}
    info.setdefault("version", __version__)
    return info


def repo_config(settings: dict) -> tuple[str, str]:
    """(owner/repo, branch): le impostazioni hanno la precedenza su version.json."""
    info = local_info()
    repo = (settings.get("update_repo") or info.get("repo") or "").strip()
    repo = re.sub(r"^https?://github\.com/", "", repo).strip("/").removesuffix(".git")
    branch = (settings.get("update_branch") or info.get("branch") or "main").strip()
    return repo, branch


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_dev_copy() -> bool:
    return (ROOT / ".git").exists()


# --------------------------------------------------------------------------- controllo
def check(settings: dict, timeout: int = 8) -> dict:
    repo, branch = repo_config(settings)
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        raise UpdateError("Repository GitHub non configurato (formato utente/nome) in Impostazioni › Aggiornamenti.")
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/version.json"
    try:
        r = requests.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"})
    except requests.RequestException as e:
        raise UpdateError(f"Impossibile contattare GitHub: {e}") from e
    if r.status_code == 404:
        raise UpdateError(f"version.json non trovato su {repo} (ramo {branch}). Il repository è pubblico?")
    r.raise_for_status()
    remote = r.json()
    loc = local_info()
    return {
        "available": parse_version(remote.get("version", "0")) > parse_version(loc.get("version", "0")),
        "local": loc.get("version"), "remote": remote.get("version"),
        "date": remote.get("date", ""), "notes": remote.get("notes", []),
        "repo": repo, "branch": branch,
    }


# --------------------------------------------------------------------------- installazione
def _download(repo: str, branch: str, dest: Path, progress) -> None:
    url = f"https://codeload.github.com/{repo}/zip/refs/heads/{branch}"
    with requests.get(url, stream=True, timeout=30) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress("Download dell'aggiornamento…", min(0.6, 0.6 * done / total) if total else 0.3)


def _safe_extract(zpath: Path, out: Path) -> Path:
    with zipfile.ZipFile(zpath) as z:
        for m in z.namelist():
            target = (out / m).resolve()
            if not str(target).startswith(str(out.resolve())):
                raise UpdateError("Archivio non valido (percorsi sospetti).")
        z.extractall(out)
    # la radice è la cartella che contiene main.py e app/
    for cand in [out] + [p for p in out.iterdir() if p.is_dir()]:
        if (cand / "main.py").exists() and (cand / "app").is_dir():
            return cand
    raise UpdateError("L'archivio scaricato non contiene PC Analyzer (main.py / app mancanti).")


def _backup(version: str) -> Path:
    bdir = ROOT / "_backup" / f"v{version}"
    if bdir.exists():
        shutil.rmtree(bdir, ignore_errors=True)
    bdir.mkdir(parents=True)
    for name in MANAGED:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, bdir / name, ignore=shutil.ignore_patterns("__pycache__"))
        elif src.exists():
            shutil.copy2(src, bdir / name)
    # tiene solo gli ultimi 3 backup
    olds = sorted((ROOT / "_backup").iterdir(), key=lambda p: p.stat().st_mtime)
    for p in olds[:-3]:
        shutil.rmtree(p, ignore_errors=True)
    return bdir


def _install_tree(src_root: Path) -> None:
    for name in MANAGED:
        src, dst = src_root / name, ROOT / name
        if not src.exists():
            continue
        if src.is_dir():
            if name == "app" and dst.exists():
                # elimina i moduli che non esistono più nella nuova versione
                for old in dst.glob("*.py"):
                    if not (src / old.name).exists():
                        old.unlink()
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dst)


def _pip_install(req: Path, progress) -> None:
    if progress:
        progress("Installazione nuove dipendenze…", 0.85)
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req)], capture_output=True,
                   creationflags=NO_WINDOW, timeout=600)


def git_pull() -> str:
    if not shutil.which("git"):
        raise UpdateError("Git non è installato.")
    r = subprocess.run(["git", "-C", str(ROOT), "pull"], capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise UpdateError(r.stderr.strip() or "git pull non riuscito")
    return r.stdout.strip()


def apply(settings: dict, progress=None) -> dict:
    """Scarica e installa l'ultima versione. Restituisce {'version', 'backup'}."""
    if is_frozen():
        raise UpdateError("Stai usando l'eseguibile: l'aggiornamento automatico funziona sulla versione con i "
                          "sorgenti (avvia.bat). Aggiorna i sorgenti e rilancia build_exe.bat.")
    if is_dev_copy():
        if progress:
            progress("Copia di sviluppo: eseguo git pull…", 0.3)
        out = git_pull()
        return {"version": local_info().get("version"), "backup": None, "git": out}
    repo, branch = repo_config(settings)
    with tempfile.TemporaryDirectory(prefix="pcanalyzer_upd_") as tmp:
        tmp = Path(tmp)
        zpath = tmp / "update.zip"
        _download(repo, branch, zpath, progress)
        if progress:
            progress("Estrazione…", 0.65)
        new_root = _safe_extract(zpath, tmp / "x")
        new_info = json.loads((new_root / "version.json").read_text(encoding="utf-8"))
        req_changed = not (ROOT / "requirements.txt").exists() or not filecmp.cmp(
            new_root / "requirements.txt", ROOT / "requirements.txt", shallow=False)
        if progress:
            progress("Backup della versione attuale…", 0.72)
        bdir = _backup(local_info().get("version", "0"))
        if progress:
            progress("Installazione dei nuovi file…", 0.8)
        try:
            _install_tree(new_root)
        except Exception as e:  # ripristino in caso di errore a metà
            _install_tree(bdir)
            raise UpdateError(f"Installazione non riuscita, ripristinata la versione precedente: {e}") from e
        if req_changed and (ROOT / "requirements.txt").exists():
            _pip_install(ROOT / "requirements.txt", progress)
    if progress:
        progress("Aggiornamento completato", 1.0)
    return {"version": new_info.get("version"), "backup": str(bdir)}


def restart() -> None:
    """Avvia una nuova istanza dell'app (senza console) e termina quella attuale."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    cmd = [str(pyw if pyw.exists() else exe), str(ROOT / "main.py")]
    flags = 0
    if sys.platform.startswith("win"):
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd, cwd=str(ROOT), creationflags=flags, close_fds=True)
    os._exit(0)
