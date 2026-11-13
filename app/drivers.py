"""
Link ufficiali per driver e BIOS in base all'hardware rilevato.

Per i produttori principali di schede madri si costruisce direttamente l'indirizzo
della pagina del modello (schemi verificati sui siti ufficiali); quando il modello
non è sicuro c'è sempre anche la pagina generale di supporto e una ricerca
limitata al sito ufficiale.
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse

q = urllib.parse.quote
qp = urllib.parse.quote_plus

GENERIC_NAMES = {"", "to be filled by o.e.m.", "default string", "system product name", "system manufacturer",
                 "not applicable", "none", "o.e.m.", "base board product name"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _is_generic(s: str) -> bool:
    return _clean(s).lower() in GENERIC_NAMES


def _site_search(domain: str, query: str) -> str:
    return "https://www.google.com/search?q=" + qp(f"site:{domain} {query}")


def board_vendor(manufacturer: str) -> str:
    m = (manufacturer or "").lower()
    for key, name in (("asus", "ASUS"), ("micro-star", "MSI"), ("msi", "MSI"), ("gigabyte", "Gigabyte"),
                      ("asrock", "ASRock"), ("biostar", "Biostar"), ("dell", "Dell"), ("hewlett", "HP"),
                      ("hp", "HP"), ("lenovo", "Lenovo"), ("acer", "Acer"), ("microsoft", "Microsoft"),
                      ("intel", "Intel"), ("nzxt", "NZXT"), ("evga", "EVGA")):
        if key in m:
            return name
    return _clean(manufacturer) or "Sconosciuto"


OEM = {"Dell", "HP", "Lenovo", "Acer", "Microsoft"}


# --------------------------------------------------------------------------- scheda madre
def _board_items(vendor: str, model: str, version: str, cpu_vendor: str) -> list[dict]:
    items: list[dict] = []
    if not model:
        return items
    if vendor == "ASUS":
        base = f"https://www.asus.com/supportonly/{q(model.lower())}"
        items += [
            {"title": "Driver e utility del modello", "url": f"{base}/helpdesk_download/", "kind": "driver",
             "desc": "Pagina ufficiale ASUS del tuo modello: chipset, audio, LAN, Wi-Fi e utility."},
            {"title": "Aggiornamenti BIOS", "url": f"{base}/helpdesk_bios/", "kind": "bios",
             "desc": "Ultime versioni BIOS con note di rilascio (supporto nuove CPU, fix sicurezza)."},
        ]
    elif vendor == "MSI":
        slug = re.sub(r"\s*\(MS-\w+\)\s*", "", model).strip().replace(" ", "-")
        items += [
            {"title": "Driver, BIOS e utility del modello", "url": f"https://www.msi.com/Motherboard/{slug}/support",
             "kind": "driver", "desc": "Pagina ufficiale MSI del tuo modello (schede Driver, BIOS e Utility)."},
            {"title": "Supporto schede madri MSI (Live Update)", "url": "https://www.msi.com/support/mb",
             "kind": "tool", "desc": "Download, MSI Center Live Update e verifica compatibilità CPU."},
        ]
    elif vendor == "Gigabyte":
        slug = model.strip().replace(" ", "-")
        m = re.fullmatch(r"(\d)\.(\d)", (version or "").strip())
        if m:
            items.append({"title": "Driver, BIOS e utility del modello",
                          "url": f"https://www.gigabyte.com/Motherboard/{slug}-rev-{m.group(1)}{m.group(2)}/support",
                          "kind": "driver", "desc": f"Pagina ufficiale Gigabyte del tuo modello (revisione {version})."})
        items.append({"title": "Cerca il modello sul sito Gigabyte",
                      "url": _site_search("gigabyte.com", f"{model} support"), "kind": "search",
                      "desc": "Gigabyte distingue le revisioni (rev. 1.0, 1.1…): la revisione è stampata sulla scheda, "
                              "vicino agli slot PCIe."})
    elif vendor == "ASRock":
        plat = "AMD" if cpu_vendor == "amd" else "Intel"
        items += [
            {"title": "Driver e BIOS del modello",
             "url": f"https://www.asrock.com/mb/{plat}/{q(model)}/index.asp#Download", "kind": "driver",
             "desc": "Pagina ufficiale ASRock del tuo modello, sezione Download."},
            {"title": "Ultimi driver pubblicati da ASRock", "url": "https://www.asrock.com/support/index.asp?cat=Drivers",
             "kind": "tool", "desc": "Elenco degli aggiornamenti più recenti per tutte le schede."},
        ]
    elif vendor == "Dell":
        items.append({"title": "Driver e BIOS Dell (rilevamento automatico)",
                      "url": "https://www.dell.com/support/drivers", "kind": "driver",
                      "desc": "Inserisci il Service Tag (etichetta sotto/dietro il PC) o usa il rilevamento automatico."})
    elif vendor == "HP":
        items.append({"title": "Driver e BIOS HP", "url": "https://support.hp.com/drivers", "kind": "driver",
                      "desc": "Identifica il PC con il numero di serie o con HP Support Assistant."})
    elif vendor == "Lenovo":
        items.append({"title": "Driver e BIOS Lenovo", "url": "https://support.lenovo.com", "kind": "driver",
                      "desc": "Usa «Rileva prodotto» oppure inserisci il numero di serie; per l'aggiornamento "
                              "automatico c'è Lenovo Vantage."})
    model = re.sub(r"\s*\(MS-\w+\)\s*", " ", model).strip()
    if vendor not in ("Dell", "HP", "Lenovo"):
        domain = {"ASUS": "asus.com", "MSI": "msi.com", "Gigabyte": "gigabyte.com", "ASRock": "asrock.com",
                  "Biostar": "biostar.com.tw", "Acer": "acer.com", "Microsoft": "microsoft.com",
                  "NZXT": "nzxt.com", "EVGA": "evga.com"}.get(vendor)
        if domain and vendor != "Gigabyte":
            items.append({"title": "Ricerca sul sito ufficiale", "url": _site_search(domain, f"{model} driver"),
                          "kind": "search", "desc": f"Se il link diretto non apre il modello giusto, cerca «{model}» "
                                                    f"solo su {domain}."})
    return items


# --------------------------------------------------------------------------- GPU
def gpu_vendor(name: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in ("nvidia", "geforce", "quadro", "rtx", "gtx")):
        return "NVIDIA"
    if any(k in n for k in ("radeon", "amd", " rx ")):
        return "AMD"
    if "intel" in n or " arc " in f" {n} ":
        return "Intel"
    return ""


def _gpu_items(vendor: str, laptop: bool) -> list[dict]:
    if vendor == "NVIDIA":
        items = [
            {"title": "Driver NVIDIA (ricerca manuale)", "url": "https://www.nvidia.com/it-it/drivers/", "kind": "driver",
             "desc": "Scegli la serie e il modello: «Game Ready» per giocare, «Studio» per editing e grafica."},
            {"title": "NVIDIA App (aggiornamenti automatici)", "url": "https://www.nvidia.com/it-it/geforce/geforce-experience/",
             "kind": "tool", "desc": "L'app ufficiale che avvisa e installa i nuovi driver, con impostazioni dei giochi."},
        ]
    elif vendor == "AMD":
        items = [
            {"title": "Driver AMD Software: Adrenalin Edition", "url": "https://www.amd.com/en/support/downloads/drivers.html",
             "kind": "driver", "desc": "Usa il tool di rilevamento automatico oppure scegli il modello Radeon dall'elenco."},
        ]
    elif vendor == "Intel":
        items = [
            {"title": "Driver grafici Intel (Arc / Iris Xe / UHD)", "url": "https://www.intel.com/support/graphics",
             "kind": "driver", "desc": "Driver ufficiali per schede Intel Arc e grafica integrata."},
            {"title": "Intel Driver & Support Assistant", "url": "https://www.intel.com/content/www/us/en/support/detect.html",
             "kind": "tool", "desc": "Rileva automaticamente i prodotti Intel e propone i driver aggiornati."},
        ]
    else:
        items = []
    return items


def _chipset_items(cpu_vendor: str) -> list[dict]:
    if cpu_vendor == "amd":
        return [{"title": "Driver chipset AMD Ryzen", "url": "https://www.amd.com/en/support/downloads/drivers.html",
                 "kind": "driver", "desc": "Seleziona «Chipsets» e il tuo socket (AM4/AM5): migliorano gestione "
                                          "energetica e prestazioni dei Ryzen."}]
    if cpu_vendor == "intel":
        return [{"title": "Intel Driver & Support Assistant", "url": "https://www.intel.com/content/www/us/en/support/detect.html",
                 "kind": "tool", "desc": "Chipset, Management Engine, Wi-Fi e Bluetooth Intel in un unico strumento."}]
    return []


def _bios_age_years(date_str: str) -> float | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%d/%m/%Y"):
        try:
            d = dt.datetime.strptime((date_str or "")[:10], fmt).date()
            return (dt.date.today() - d).days / 365.25
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- API
def driver_sections(report: dict, is_laptop: bool = False) -> list[dict]:
    mb = report.get("motherboard", {})
    sysi = report.get("system", {})
    cpu_name = (report.get("cpu", {}).get("name") or "").lower()
    cpu_vendor = "amd" if ("amd" in cpu_name or "ryzen" in cpu_name) else ("intel" if "intel" in cpu_name else "")
    sections = []

    # --- PC di marca / portatile: conviene il supporto del produttore del sistema
    sys_vendor = board_vendor(sysi.get("manufacturer", ""))
    sys_model = _clean(sysi.get("model", ""))
    b_vendor = board_vendor(mb.get("manufacturer", ""))
    b_model = _clean(mb.get("model", ""))
    use_system = (is_laptop or sys_vendor in OEM) and not _is_generic(sys_model)

    if use_system:
        vendor, model = sys_vendor, sys_model
        if vendor == "ASUS":
            code = re.findall(r"\b([A-Z]{1,3}\d{3,4}[A-Z]{0,3})\b", sys_model)
            model = code[-1] if code else sys_model
        items = _board_items(vendor, model, "", cpu_vendor)
        if not items:
            items = [{"title": "Supporto del produttore", "url": _site_search(vendor.lower() + ".com",
                                                                              f"{sys_model} driver"),
                      "kind": "search", "desc": "Ricerca del modello sul sito ufficiale del produttore."}]
        sections.append({
            "component": "Sistema" + (" portatile" if is_laptop else " di marca"), "vendor": vendor,
            "device": f"{sysi.get('manufacturer', '')} {sys_model}".strip(),
            "items": items,
            "note": "Su portatili e PC di marca usa prima i driver del produttore del sistema: sono "
                    "personalizzati per quel modello (tasti funzione, gestione energetica, audio).",
        })
    else:
        items = _board_items(b_vendor, b_model, mb.get("version", ""), cpu_vendor) if not _is_generic(b_model) else []
        note = None
        if not items:
            note = "Il modello della scheda madre non è stato letto in modo affidabile: cercalo stampato sulla " \
                   "scheda, tra gli slot PCIe o vicino al socket."
            if b_model and not _is_generic(b_model):
                items = [{"title": "Ricerca del modello", "url": "https://www.google.com/search?q=" +
                          qp(f"{mb.get('manufacturer', '')} {b_model} driver download"), "kind": "search",
                          "desc": "Ricerca web del modello rilevato: apri solo il risultato del sito ufficiale."}]
        sections.append({"component": "Scheda madre", "vendor": b_vendor,
                         "device": f"{b_vendor} {b_model}".strip(), "items": items, "note": note})

    # --- BIOS: età
    age = _bios_age_years(mb.get("bios_date", ""))
    bios_info = {"version": mb.get("bios_version", ""), "date": mb.get("bios_date", ""), "age_years": age,
                 "advice": None}
    if age is not None and age >= 2:
        bios_info["advice"] = (f"Il BIOS installato ha circa {age:.0f} anni: controlla se c'è una versione più recente "
                               "(spesso migliora compatibilità, stabilità e sicurezza). Aggiornalo solo con "
                               "alimentazione stabile e seguendo le istruzioni del produttore.")
    sections[0]["bios"] = bios_info

    # --- chipset
    ch = _chipset_items(cpu_vendor)
    if ch and not use_system:
        sections.append({"component": "Chipset e processore", "vendor": cpu_vendor.upper(),
                         "device": report.get("cpu", {}).get("name", ""), "items": ch,
                         "note": "Installa il driver chipset prima degli altri, poi riavvia."})

    # --- GPU
    seen, vendors = set(), set()
    for g in report.get("gpus", []):
        v = gpu_vendor(g.get("name", ""))
        if not v or g.get("name") in seen or (g.get("is_integrated") and v in vendors):
            continue   # l'integrata dello stesso produttore usa lo stesso pacchetto driver
        seen.add(g.get("name"))
        vendors.add(v)
        note = None
        if is_laptop:
            note = "Su un portatile i driver generici funzionano quasi sempre, ma se noti problemi (schermo, " \
                   "commutazione GPU integrata/dedicata) usa quelli del produttore del portatile."
        sections.append({"component": "Scheda video" + (" integrata" if g.get("is_integrated") else ""),
                         "vendor": v, "device": g.get("name", ""), "installed": g.get("driver", ""),
                         "items": _gpu_items(v, is_laptop), "note": note})
    return sections
