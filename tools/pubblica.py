"""
Pubblica un aggiornamento di PC Analyzer su GitHub.

Uso (dalla cartella PCAnalyzer):  python tools\\pubblica.py   oppure doppio clic su pubblica_aggiornamento.bat

Cosa fa:
 - la prima volta collega la cartella al tuo repository GitHub (git init + remote);
 - chiede il nuovo numero di versione e le novità;
 - aggiorna version.json e app/__init__.py;
 - esegue git add / commit / push (e crea il tag vX.Y.Z).
Gli utenti con l'aggiornamento automatico attivo riceveranno la nuova versione al prossimo avvio.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VFILE = ROOT / "version.json"
INIT = ROOT / "app" / "__init__.py"


GIT = "git"


def find_git() -> str | None:
    g = shutil.which("git")
    if g:
        return g
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        cand = os.path.join(base, "Git", "cmd", "git.exe")
        if base and os.path.exists(cand):
            return cand
    return None


def run(*args, check=True, capture=False):
    args = [GIT if a == "git" else a for a in args]
    print("  $", " ".join(args))
    r = subprocess.run(list(args), cwd=ROOT, text=True, capture_output=capture)
    if check and r.returncode != 0:
        if capture:
            print(r.stdout, r.stderr)
        sys.exit(f"\nErrore durante: {' '.join(args)}")
    return r


def ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


def bump(v: str) -> str:
    p = [int(x) for x in re.findall(r"\d+", v)] or [1, 0, 0]
    while len(p) < 3:
        p.append(0)
    p[2] += 1
    return ".".join(map(str, p[:3]))


def main():
    global GIT
    print("=== Pubblica aggiornamento PC Analyzer ===\n")
    GIT = find_git()
    if not GIT:
        sys.exit("Git non è installato (o non è stato trovato).\n"
                 "Scaricalo da https://git-scm.com/download/win, installalo con le opzioni predefinite e riprova.")

    # nome ed email per firmare le versioni (chiesti una sola volta)
    for key, label in (("user.name", "Il tuo nome (per firmare le versioni)"),
                       ("user.email", "Email del tuo account GitHub")):
        cur = subprocess.run([GIT, "config", "--global", key], capture_output=True, text=True).stdout.strip()
        if not cur:
            val = ask(label)
            if not val:
                sys.exit("Valore obbligatorio.")
            subprocess.run([GIT, "config", "--global", key, val])

    info = json.loads(VFILE.read_text(encoding="utf-8"))

    # --- prima configurazione
    if not (ROOT / ".git").exists():
        print("Prima pubblicazione: collego la cartella a GitHub.")
        print("Crea prima un repository VUOTO e PUBBLICO su https://github.com/new (es. PCAnalyzer).\n")
        url = ask("Indirizzo del repository (es. https://github.com/tuonome/PCAnalyzer)")
        m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
        if not m:
            sys.exit("Indirizzo non valido.")
        info["repo"] = m.group(1)
        run("git", "init")
        run("git", "branch", "-M", info.get("branch", "main"))
        run("git", "remote", "add", "origin", f"https://github.com/{info['repo']}.git")
    elif not info.get("repo"):
        r = run("git", "remote", "get-url", "origin", check=False, capture=True)
        m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", r.stdout.strip())
        if m:
            info["repo"] = m.group(1)

    # --- nuova versione
    cur = info.get("version", "1.0.0")
    print(f"\nVersione attuale: {cur}")
    new = ask("Nuova versione", bump(cur))
    print("Novità di questa versione (una per riga, riga vuota per finire):")
    notes = []
    while True:
        line = input("  - ").strip()
        if not line:
            break
        notes.append(line)
    if not notes:
        notes = ["Miglioramenti e correzioni"]

    info.update({"version": new, "date": dt.date.today().isoformat(), "notes": notes})
    VFILE.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    txt = INIT.read_text(encoding="utf-8")
    INIT.write_text(re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{new}"', txt), encoding="utf-8")

    # --- commit e push
    run("git", "add", "-A")
    # check=False: se un tentativo precedente si era fermato al push, non c'è nulla da committare e si prosegue
    run("git", "commit", "-m", f"Versione {new}: " + "; ".join(notes), check=False)
    run("git", "tag", f"v{new}", check=False)
    run("git", "push", "-u", "origin", info.get("branch", "main"))
    run("git", "push", "origin", f"v{new}", check=False)
    print(f"\nFatto! Versione {new} pubblicata su https://github.com/{info.get('repo')}")
    print("Le altre installazioni la riceveranno al prossimo controllo degli aggiornamenti.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAnnullato.")
    except SystemExit as e:          # errori previsti: mostra il messaggio senza chiudere la finestra
        if e.code not in (None, 0):
            print(f"\nERRORE: {e.code}")
    except Exception as e:           # errori imprevisti
        import traceback
        traceback.print_exc()
        print(f"\nERRORE imprevisto: {e}")
    input("\nPremi Invio per chiudere…")
