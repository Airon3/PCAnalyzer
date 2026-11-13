"""
Integrazione IA opzionale (Claude API di Anthropic).

- analisi approfondita della build e consigli di upgrade con prezzi correnti
  (lo strumento di ricerca web lato server permette di controllare il mercato);
- domande libere sulla build;
- aggiornamento del listino prezzi.

Serve una API key (https://console.anthropic.com). Senza chiave l'app funziona
comunque con l'algoritmo locale.
"""
from __future__ import annotations

import json
import re

import requests

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AIError(RuntimeError):
    pass


def _web_search_tool(max_uses: int = 5) -> dict:
    return {
        "type": "web_search_20250305", "name": "web_search", "max_uses": max_uses,
        "user_location": {"type": "approximate", "country": "IT", "timezone": "Europe/Rome"},
    }


def call_claude(settings: dict, messages: list[dict], system: str = "", web_search: bool = False,
                max_tokens: int = 3000, timeout: int = 180) -> str:
    key = (settings.get("anthropic_api_key") or "").strip()
    if not key:
        raise AIError("Nessuna API key configurata. Inseriscila in Impostazioni.")
    headers = {"x-api-key": key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    msgs = list(messages)
    body = {"model": settings.get("ai_model") or "claude-sonnet-5-5", "max_tokens": max_tokens,
            "messages": msgs}
    if system:
        body["system"] = system
    if web_search:
        body["tools"] = [_web_search_tool()]

    texts: list[str] = []
    for _ in range(4):  # gestisce 'pause_turn' delle ricerche lunghe
        try:
            r = requests.post(API_URL, headers=headers, json=body, timeout=timeout)
        except requests.RequestException as e:
            raise AIError(f"Errore di rete: {e}") from e
        if r.status_code != 200:
            try:
                err = r.json().get("error", {}).get("message", r.text)
            except ValueError:
                err = r.text
            raise AIError(f"API Anthropic ({r.status_code}): {err}")
        data = r.json()
        content = data.get("content", [])
        texts += [b.get("text", "") for b in content if b.get("type") == "text"]
        if data.get("stop_reason") == "pause_turn":
            msgs = msgs + [{"role": "assistant", "content": content}]
            body["messages"] = msgs
            continue
        break
    return "".join(texts).strip()


# --------------------------------------------------------------------------- contesto build
def build_summary(report: dict, ev: dict | None = None, an: dict | None = None) -> str:
    cpu, ram = report.get("cpu", {}), report.get("ram", {})
    mb = report.get("motherboard", {})
    lines = [
        f"Tipo: {'Portatile' if report.get('system', {}).get('is_laptop') else 'Desktop'}",
        f"Sistema operativo: {report.get('os', {}).get('name', '')}",
        f"CPU: {cpu.get('name')} ({cpu.get('cores')} core / {cpu.get('threads')} thread)",
        f"Scheda madre: {mb.get('manufacturer', '')} {mb.get('model', '')} (BIOS {mb.get('bios_version', '')} "
        f"del {mb.get('bios_date', '')})",
        f"RAM: {ram.get('total_gb')} GB {ram.get('type', '')} a {ram.get('configured_mhz') or '?'} MT/s, "
        f"{ram.get('modules_count')} moduli, slot totali {ram.get('slots_total') or '?'}, {ram.get('channel', '')}",
    ]
    for g in report.get("gpus", []):
        lines.append(f"GPU: {g.get('name')} ({g.get('vram_gb')} GB VRAM){' [integrata]' if g.get('is_integrated') else ''}")
    for d in report.get("disks", []):
        line = f"Disco: {d.get('model')} - {d.get('media')} {d.get('bus')} {d.get('size_gb')} GB"
        if d.get("is_system"):
            line += " [sistema]"
        if d.get("free_gb") is not None:
            line += f", liberi {d['free_gb']} GB"
        lines.append(line)
    if ev:
        r = ev["ratings"]
        lines.append(f"Voti algoritmo locale (1-5): gaming {r['gaming']}, ufficio {r['office']}, "
                     f"produttività {r['productivity']}, complessivo {r['overall']}")
    if an:
        lines.append(f"Bilanciamento algoritmo: {an['balance_score']}/100 ({an['verdict']})")
        for i in an["issues"]:
            lines.append(f"- Problema [{i['severity']}] {i['title']}")
        for u in an["upgrades"]:
            lines.append(f"- Upgrade proposto: {u['name']} ~{u.get('price_eur')} €")
    return "\n".join(lines)


SYSTEM_ADVISOR = (
    "Sei un esperto di hardware PC che lavora per un'app di diagnostica italiana. Rispondi sempre in italiano, "
    "in modo chiaro e pratico. Quando suggerisci componenti verifica compatibilità (socket, tipo di RAM, "
    "alimentatore, dimensioni) e, se puoi usare la ricerca web, controlla i prezzi attuali sul mercato italiano "
    "(Amazon.it, negozi italiani, comparatori come Trovaprezzi o Idealo) indicando prezzo indicativo e fonte. "
    "Non inventare prezzi: se non li trovi dillo."
)


def analyze_build(settings: dict, report: dict, ev: dict, an: dict, budget: str = "", use: str = "") -> str:
    prompt = (
        "Analizza questa configurazione PC.\n\n" + build_summary(report, ev, an) + "\n\n"
        f"Utilizzo principale indicato dall'utente: {use or 'non specificato'}.\n"
        f"Budget per eventuali upgrade: {budget or 'non specificato'}.\n\n"
        "Fornisci:\n"
        "1. Giudizio sintetico sulla build e se è bilanciata (spiega eventuali colli di bottiglia).\n"
        "2. Voto 1-5 (anche mezzi voti) per gaming, ufficio e produttività, confrontandolo con quello dell'algoritmo.\n"
        "3. Upgrade consigliati in ordine di priorità, con modello preciso, prezzo attuale in euro e fonte, "
        "guadagno atteso e note di compatibilità.\n"
        "4. Eventuali ottimizzazioni gratuite (BIOS, XMP/EXPO, driver, impostazioni Windows).\n"
        "Usa titoli brevi ed elenchi puntati, massimo ~450 parole."
    )
    return call_claude(settings, [{"role": "user", "content": prompt}], SYSTEM_ADVISOR, web_search=True,
                       max_tokens=3500)


def ask(settings: dict, report: dict, ev: dict, an: dict, history: list[dict], question: str) -> str:
    ctx = "Configurazione del PC dell'utente:\n" + build_summary(report, ev, an)
    msgs = [{"role": "user", "content": ctx}, {"role": "assistant", "content": "Ho letto la configurazione."}]
    msgs += history[-10:] + [{"role": "user", "content": question}]
    return call_claude(settings, msgs, SYSTEM_ADVISOR, web_search=True, max_tokens=2500)


def fetch_market_prices(settings: dict, items: list[dict]) -> dict:
    """Restituisce {id: {"price_eur": float, "source": str}} per gli articoli richiesti."""
    lst = "\n".join(f'- id "{i["id"]}": {i["name"]} (prezzo precedente {i.get("price_eur")} €)' for i in items)
    prompt = (
        "Cerca sul web il prezzo attuale più basso ragionevole (prodotto nuovo, venditore affidabile, "
        "spedizione in Italia) per ciascuno di questi componenti:\n" + lst + "\n\n"
        "Rispondi SOLO con un oggetto JSON nel formato "
        '{"<id>": {"price_eur": <numero>, "source": "<negozio o comparatore>"}, ...}. '
        "Se per un articolo non trovi un prezzo affidabile omettilo."
    )
    txt = call_claude(settings, [{"role": "user", "content": prompt}],
                      "Sei un assistente che rileva prezzi di componenti PC sul mercato italiano. "
                      "Rispondi solo con JSON valido.", web_search=True, max_tokens=2000)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def test_key(settings: dict) -> str:
    return call_claude(settings, [{"role": "user", "content": "Rispondi solo: OK"}], max_tokens=10, timeout=30)
