"""
Listino prezzi componenti: file locale (cartella utente) aggiornabile da
 1) un URL remoto con un prices.json nello stesso formato (es. file raw su GitHub);
 2) l'IA (Claude con ricerca web) che cerca i prezzi correnti sul mercato italiano.
"""
from __future__ import annotations

import datetime as dt
import urllib.parse

import requests

from .paths import load_json, resource_dir, save_json, user_file

PRICES_FILE = "prices.json"


def load() -> dict:
    data = load_json(user_file(PRICES_FILE))
    if not data or "items" not in data:
        data = load_json(resource_dir() / PRICES_FILE, {"items": []})
    return data


def save(data: dict) -> None:
    save_json(user_file(PRICES_FILE), data)


def items(category: str | None = None, data: dict | None = None) -> list[dict]:
    data = data or load()
    return [i for i in data.get("items", []) if category is None or i.get("category") == category]


def age_days(data: dict | None = None) -> int:
    data = data or load()
    try:
        return (dt.date.today() - dt.date.fromisoformat(data.get("updated", ""))).days
    except ValueError:
        return 999


def search_links(name: str) -> dict:
    q = urllib.parse.quote_plus(name)
    return {
        "Amazon.it": f"https://www.amazon.it/s?k={q}",
        "Idealo": f"https://www.idealo.it/MainSearchProductCategory.html?q={q}",
        "Trovaprezzi": f"https://www.trovaprezzi.it/categoria.aspx?libera={q}&id=-1",
    }


def _merge(data: dict, new_items: list[dict], source: str) -> int:
    by_id = {i["id"]: i for i in data.get("items", [])}
    changed = 0
    for ni in new_items:
        if "id" not in ni:
            continue
        if ni["id"] in by_id:
            cur = by_id[ni["id"]]
            if ni.get("price_eur") and ni["price_eur"] != cur.get("price_eur"):
                cur["prev_price_eur"] = cur.get("price_eur")
                changed += 1
            cur.update({k: v for k, v in ni.items() if v not in (None, "")})
        elif ni.get("category") and ni.get("name") and ni.get("price_eur"):
            data["items"].append(ni)
            changed += 1
    data["updated"] = dt.date.today().isoformat()
    data["source"] = source
    return changed


def update_from_url(url: str, timeout: int = 20) -> tuple[int, str]:
    """Scarica un prices.json remoto e lo fonde con quello locale."""
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    remote = r.json()
    data = load()
    n = _merge(data, remote.get("items", []), f"URL: {url}")
    save(data)
    return n, f"Aggiornati {n} prezzi da URL remoto."


def update_with_ai(settings: dict, progress=None) -> tuple[int, str]:
    """Chiede a Claude (con ricerca web) i prezzi attuali per ogni voce del listino."""
    from .ai_advisor import fetch_market_prices  # import locale per evitare cicli

    data = load()
    cats = ["cpu", "gpu", "ram", "ssd", "hdd", "mobo", "psu"]
    total = 0
    notes = []
    for i, cat in enumerate(cats):
        group = [it for it in data["items"] if it.get("category") == cat]
        if not group:
            continue
        if progress:
            progress(f"Ricerca prezzi {cat.upper()}… ({i + 1}/{len(cats)})", (i) / len(cats))
        res = fetch_market_prices(settings, group)
        updates = []
        for it in group:
            p = res.get(it["id"])
            if isinstance(p, dict) and p.get("price_eur"):
                try:
                    price = round(float(p["price_eur"]))
                except (TypeError, ValueError):
                    continue
                # scarta valori palesemente anomali (oltre ±60% del precedente)
                old = it.get("price_eur") or price
                if 0.4 * old <= price <= 1.6 * old:
                    updates.append({"id": it["id"], "price_eur": price, "price_source": p.get("source", "")})
                else:
                    notes.append(f"{it['name']}: valore {price}€ scartato (anomalo)")
        total += _merge(data, updates, "IA con ricerca web")
    save(data)
    if progress:
        progress("Prezzi aggiornati", 1.0)
    msg = f"Aggiornati {total} prezzi tramite IA."
    if notes:
        msg += "\n" + "\n".join(notes[:10])
    return total, msg


def reset_to_default() -> None:
    save(load_json(resource_dir() / PRICES_FILE, {"items": []}))
