"""
Algoritmo di bilanciamento: individua colli di bottiglia e propone upgrade
compatibili con prezzi dal listino, simulando il nuovo voto della build.
"""
from __future__ import annotations

import copy
import re

from . import prices as prices_mod
from .scoring import CPU_GAMING, GPU_GAMING, cpu_era, cpu_perf, evaluate, gpu_era, gpu_perf, interp

SEV_ORDER = {"alta": 0, "media": 1, "bassa": 2, "info": 3}


# --------------------------------------------------------------------------- simulazioni
def _sim(report: dict, kind: str, item: dict) -> dict:
    r = copy.deepcopy(report)
    if kind == "cpu":
        r["cpu"]["name"] = item["name"]
    elif kind == "gpu":
        gp = gpu_perf(item["name"])
        new = {"name": item["name"], "vram_gb": gp["vram"], "is_integrated": False}
        r["gpus"] = [new] + [g for g in r.get("gpus", []) if g.get("is_integrated")]
    elif kind == "ram":
        r["ram"].update({"total_gb": item["capacity_gb"], "type": item["mem"], "configured_mhz": item["speed"],
                         "rated_mhz": item["speed"], "modules_count": 2})
    elif kind == "ram_add":
        r["ram"].update({"total_gb": r["ram"]["total_gb"] * 2, "modules_count": 2})
    elif kind == "ssd":
        disks = r.get("disks", [])
        for d in disks:
            d["is_system"] = False
        disks.insert(0, {"model": item["name"], "media": "SSD", "bus": item.get("bus", "NVMe"),
                         "size_gb": item.get("capacity_gb", 1000), "is_system": True})
        r["disks"] = disks
    elif kind == "platform":
        cpu_i, mobo_i, ram_i = item["parts"]
        r["cpu"]["name"] = cpu_i["name"]
        r["ram"].update({"total_gb": max(ram_i["capacity_gb"], r["ram"].get("total_gb", 0)),
                         "type": ram_i["mem"], "configured_mhz": ram_i["speed"], "rated_mhz": ram_i["speed"],
                         "modules_count": 2})
    return r


def _gain(base_eval: dict, report_after: dict) -> dict:
    after = evaluate(report_after)
    return {k: {"before": base_eval["ratings"][k], "after": after["ratings"][k],
                "delta_raw": round(after["raw"][k] - base_eval["raw"][k], 2) if k in after["raw"] else 0}
            for k in ("gaming", "office", "productivity", "overall")}


# --------------------------------------------------------------------------- helpers
def _xmp_speed_from_part(part: str) -> int:
    """Molti part number contengono la velocità XMP (es. CMK16GX4M2B3200C16)."""
    for m in re.finditer(r"(\d{4})", part or ""):
        v = int(m.group(1))
        if 2400 <= v <= 8800 and v % 100 in (0, 33, 66, 67):
            return v
    return 0


def _psu_needed(cpu_tdp: float | None, gpu_tdp: float | None) -> int:
    w = (cpu_tdp or 95) * 1.3 + (gpu_tdp or 150) + 100
    w *= 1.3
    for s in (550, 650, 750, 850, 1000, 1200):
        if w <= s:
            return s
    return 1200


def _cat(data: dict, cat: str) -> list[dict]:
    return prices_mod.items(cat, data)


# --------------------------------------------------------------------------- analisi
def analyze(report: dict, ev: dict | None = None, price_data: dict | None = None) -> dict:
    ev = ev or evaluate(report)
    data = price_data or prices_mod.load()
    cr = ev["component_ratings"]
    plat = ev["platform"]
    laptop = ev["is_laptop"]
    gp, cp = ev["gpu_perf"], ev["cpu_perf"]
    ram = report.get("ram", {})
    ram_gb = ev["ram_info"]["gb"]
    ram_type = ev["ram_info"]["type"] or plat.get("mem", "")

    issues: list[dict] = []
    free_fixes: list[dict] = []
    upgrades: list[dict] = []
    penalty = 0.0

    def issue(sev, comp, title, detail):
        issues.append({"severity": sev, "component": comp, "title": title, "detail": detail})

    # ---------------- CPU vs GPU
    gap = cr["gpu_gaming"] - cr["cpu_gaming"]
    if not gp["integrated"]:
        if gap >= 1.0:
            issue("alta" if gap >= 1.5 else "media", "CPU", "Collo di bottiglia della CPU nel gaming",
                  f"La GPU (voto {cr['gpu_gaming']:.1f}) è molto più potente della CPU (voto {cr['cpu_gaming']:.1f}): "
                  "nei giochi la scheda video non verrà sfruttata a pieno, soprattutto in 1080p e titoli competitivi.")
        elif gap <= -1.5 and cr["gpu_gaming"] < 4:
            issue("media", "GPU", "La scheda video limita il gaming",
                  f"La CPU (voto {cr['cpu_gaming']:.1f}) può gestire una GPU molto più potente di quella attuale "
                  f"(voto {cr['gpu_gaming']:.1f}). " + ("Su un portatile la GPU non è sostituibile." if laptop else
                  "L'upgrade della scheda video darà il guadagno maggiore nei giochi."))
        penalty += 18 * max(0.0, abs(gap) - 0.5)
    else:
        issue("info", "GPU", "Nessuna scheda video dedicata",
              "La grafica integrata va bene per ufficio e multimedia, ma non per il gaming moderno o il rendering GPU.")
        if cr["cpu_gaming"] >= 3.5 and not laptop:
            penalty += 10

    # ---------------- RAM
    if ram_gb and ram_gb < 8:
        issue("alta", "RAM", f"RAM insufficiente ({ram_gb:g} GB)",
              "Con meno di 8 GB Windows e il browser andranno in swap su disco: rallentamenti evidenti.")
        penalty += 30
    elif ram_gb and ram_gb < 16:
        issue("media", "RAM", f"RAM limitata ({ram_gb:g} GB)",
              "16 GB sono oggi il minimo consigliato per gaming e multitasking, 32 GB per produttività.")
        penalty += 15
    elif ram_gb and ram_gb < 32 and cp["mt"] >= 50:
        issue("bassa", "RAM", "RAM sottodimensionata rispetto alla CPU",
              f"La CPU è adatta a carichi pesanti: con {ram_gb:g} GB editing video, VM e rendering saranno limitati. "
              "Consigliati 32 GB.")
        penalty += 6
    if ev["ram_info"]["single_channel"]:
        issue("media", "RAM", "Memoria in single channel",
              "È installato un solo modulo: la banda di memoria è dimezzata (fino a -20% FPS e prestazioni grafiche "
              "integrate molto ridotte). Meglio 2 moduli identici.")
        penalty += 8
    if ram.get("mixed_kits"):
        issue("bassa", "RAM", "Moduli RAM diversi tra loro",
              "Moduli di marche/capacità diverse possono costringere a frequenze più basse o causare instabilità.")

    # XMP / EXPO (fix gratuito)
    conf = ram.get("configured_mhz") or 0
    parts = [m.get("part_number", "") for m in ram.get("modules", [])]
    xmp = max([_xmp_speed_from_part(p) for p in parts] or [0])
    if conf and not laptop:
        if xmp and conf < xmp - 150:
            free_fixes.append({"title": "Attiva il profilo XMP/EXPO nel BIOS",
                               "detail": f"La RAM supporta {xmp} MT/s ma sta lavorando a {conf} MT/s. "
                                         "Attivando XMP (Intel) o EXPO/DOCP (AMD) guadagni prestazioni gratis."})
        elif not xmp and (("DDR4" in ram_type and conf <= 2666) or ("DDR5" in ram_type and conf <= 4800)):
            free_fixes.append({"title": "Verifica il profilo XMP/EXPO nel BIOS",
                               "detail": f"La RAM lavora a {conf} MT/s, velocità base JEDEC. Se i moduli supportano "
                                         "frequenze superiori e la scheda madre lo consente (chipset Intel serie H/B "
                                         "più vecchi limitano la RAM), attiva XMP/EXPO nel BIOS."})

    # ---------------- Storage
    st = ev["storage"]
    if st["system_type"] == "HDD":
        issue("alta", "Archiviazione", "Sistema operativo su disco meccanico (HDD)",
              "È il collo di bottiglia più evidente nell'uso quotidiano: avvio, apertura programmi e caricamenti "
              "fino a 10-20 volte più lenti rispetto a un SSD.")
        penalty += 25
    elif st["ssd_total_gb"] and st["ssd_total_gb"] < 250:
        issue("bassa", "Archiviazione", "SSD molto piccolo",
              "Meno di 256 GB si riempiono rapidamente con Windows, aggiornamenti e un paio di giochi.")
        penalty += 5
    for d in report.get("disks", []):
        if d.get("free_gb") is not None and d.get("volumes_gb"):
            if d["free_gb"] / max(d["volumes_gb"], 1) < 0.1:
                free_fixes.append({"title": f"Libera spazio su {d.get('model')}",
                                   "detail": f"Restano solo {d['free_gb']:g} GB liberi: sotto il 10% gli SSD rallentano "
                                             "e Windows può avere problemi con gli aggiornamenti."})
        if d.get("health") and d["health"] not in ("Healthy", "", "0"):
            issue("alta", "Archiviazione", f"Stato disco: {d['health']}",
                  f"Il disco {d.get('model')} segnala problemi di salute: fai subito un backup dei dati.")

    # ---------------- epoca: età, funzionalità, Windows 11
    era = ev.get("era", {})
    g_era, c_era = era.get("gpu", {}), era.get("cpu", {})
    if g_era.get("penalty", 0) >= 0.25:
        issue("bassa" if g_era["penalty"] < 0.6 else "media", "GPU",
              f"Scheda video datata per gli standard del {era.get('year')}",
              ". ".join(g_era["notes"]) + f". Il voto gaming della GPU è stato ridotto di {g_era['penalty']:.2f} punti.")
    if c_era.get("win11") is False:
        issue("media", "CPU", "CPU non compatibile con Windows 11",
              "Windows 10 non riceve più aggiornamenti di sicurezza gratuiti da ottobre 2025: per usare il PC in "
              "sicurezza conviene cambiare piattaforma (o valutare Linux).")
        penalty += 8
    if era.get("decay", 1) < 1:
        issue("info", "Database", f"Database prestazioni del {era.get('db_year')}",
              f"Siamo nel {era.get('year')}: i voti sono stati ridotti automaticamente per tenere conto dei "
              "requisiti più alti di giochi e software. Aggiorna l'app/il database per includere i modelli nuovi.")
    if cr["cpu_office"] < 2.5:
        issue("media", "CPU", "CPU datata anche per uso quotidiano",
              "Il processore è lento in single-thread: navigazione con molte schede e app moderne risulteranno lente.")
        penalty += 8
    if cp.get("year") and cp["year"] <= 2015:
        issue("info", "Piattaforma", "Piattaforma datata",
              "CPU e scheda madre hanno diversi anni: per salti di prestazioni importanti conviene cambiare piattaforma "
              "(CPU + scheda madre + RAM). Windows 11 potrebbe non essere supportato ufficialmente.")

    # ================================================================== UPGRADE
    base = ev

    # --- SSD
    if st["system_type"] == "HDD" or (st["ssd_total_gb"] and st["ssd_total_gb"] < 250):
        nvme_ok = not laptop and ((cp.get("year") or 2018) >= 2017)
        pick = next((i for i in _cat(data, "ssd") if i.get("bus") == ("NVMe" if nvme_ok else "SATA")), None)
        if pick:
            upgrades.append(_upgrade("Archiviazione", pick, 1,
                                     "Installa Windows su SSD (o clona il disco attuale): è l'upgrade più percepibile.",
                                     _gain(base, _sim(report, "ssd", pick)),
                                     note=None if nvme_ok else "Verifica che la scheda madre/portatile abbia uno slot "
                                                               "M.2 NVMe: in quel caso preferisci un SSD NVMe."))

    # --- RAM
    mem = "DDR5" if "DDR5" in ram_type else ("DDR4" if "DDR4" in ram_type else (plat.get("mem") or ""))
    want = 32 if (cp["mt"] >= 45 or gp["idx"] >= 35 or mem == "DDR5") else 16
    if mem in ("DDR4", "DDR5") and (ram_gb < 16 or (ram_gb < 32 and want == 32 and cp["mt"] >= 50)):
        kits = [k for k in _cat(data, "ram") if k.get("mem") == mem and bool(k.get("laptop")) == laptop
                and k.get("capacity_gb", 0) >= max(want, ram_gb + 8)]
        kits.sort(key=lambda k: k["price_eur"])
        if kits:
            k = kits[0]
            note = "Nei portatili la RAM può essere saldata: verifica che ci siano slot SO-DIMM." if laptop else None
            upgrades.append(_upgrade("RAM", k, 1 if ram_gb < 16 else (2 if ev["ram_info"]["single_channel"] else 3),
                                     f"Porta la memoria a {k['capacity_gb']} GB in dual channel.",
                                     _gain(base, _sim(report, "ram", k)), note=note))
    elif ev["ram_info"]["single_channel"] and ram_gb >= 16:
        upgrades.append({"component": "RAM", "priority": 2, "name": f"Secondo modulo identico da {ram_gb:g} GB",
                         "price_eur": None, "reason": "Aggiungi un modulo uguale per passare in dual channel.",
                         "gain": _gain(base, _sim(report, "ram_add", {})), "note": "Prezzo variabile: cerca lo stesso "
                         "part number dei moduli installati.", "links": prices_mod.search_links(
                             (ram.get("modules") or [{}])[0].get("part_number") or f"{mem} {ram_gb:g}GB")})

    # --- GPU (solo desktop)
    gpu_rating = cr["gpu_gaming"]
    cpu_rating = cr["cpu_gaming"]
    if not laptop:
        target = min(5.0, cpu_rating + 0.5)
        cands = []
        for g in _cat(data, "gpu"):
            perf = gpu_perf(g["name"])
            rr = interp(perf["idx"], GPU_GAMING) - gpu_era(perf)["penalty"]
            if rr >= gpu_rating + 0.75:
                cands.append((rr, g, perf))
        if cands and gpu_rating < target - 0.4:
            reach = [c for c in cands if c[0] >= target - 0.25 and c[0] <= target + 0.6]
            if reach:
                rr, g, perf = min(reach, key=lambda c: c[1]["price_eur"])
            else:
                rr, g, perf = max([c for c in cands if c[0] <= target + 0.6] or cands,
                                  key=lambda c: c[0] / c[1]["price_eur"])
            prio = 3 if gp["integrated"] else (1 if gap <= -1.5 else (2 if gap <= -0.75 else 3))
            why = f"Bilanciamento ideale con la tua CPU (voto gaming GPU {gpu_rating:.1f} → {rr:.1f})."
            if gp["integrated"]:
                why = "Solo se vuoi usare il PC anche per gaming/rendering. " + why
            psu = _psu_needed(cp.get("tdp"), g.get("tdp") or perf.get("tdp"))
            upgrades.append(_upgrade("Scheda video", g, prio, why, _gain(base, _sim(report, "gpu", g)),
                                     note=f"Verifica l'alimentatore: consigliato almeno {psu} W di qualità "
                                          "(80+ Gold) e lo spazio nel case."))
            shown = {g["id"]}
            # miglior rapporto guadagno/prezzo
            val = [c for c in cands if c[0] >= max(gpu_rating + 1.0, target - 1.0) and c[1]["id"] not in shown
                   and c[1]["price_eur"] < g["price_eur"]]
            if val:
                rr2, g2, _ = max(val, key=lambda c: (c[0] - gpu_rating) / c[1]["price_eur"])
                shown.add(g2["id"])
                upgrades.append(_upgrade("Scheda video", g2, max(prio, 3),
                                         f"Miglior rapporto prestazioni/prezzo (voto GPU {gpu_rating:.1f} → {rr2:.1f}).",
                                         _gain(base, _sim(report, "gpu", g2))))
            cheap = [c for c in cands if c[1]["id"] not in shown and c[1]["price_eur"] < g["price_eur"] * 0.7]
            if cheap:
                rr3, g3, _ = min(cheap, key=lambda c: c[1]["price_eur"])
                upgrades.append(_upgrade("Scheda video", g3, 4,
                                         f"Opzione economica (voto GPU {gpu_rating:.1f} → {rr3:.1f}).",
                                         _gain(base, _sim(report, "gpu", g3))))

    # --- CPU / piattaforma
    need_cpu = (gap >= 0.75 and not gp["integrated"]) or cr["cpu_office"] < 3 or (
        cr["cpu_prod"] < 2.5 and gpu_rating >= 3.5)
    if need_cpu and not laptop:
        target = max(cpu_rating + 0.75, min(5.0, gpu_rating - 0.25))
        same = []
        if plat["cpu_upgradable"]:
            for c in _cat(data, "cpu"):
                if c.get("socket") != plat["socket"]:
                    continue
                pp = cpu_perf(c["name"])
                rr = interp(pp["gaming"], CPU_GAMING) - cpu_era(pp, c["name"])["penalty"]
                if rr >= cpu_rating + 0.5:
                    same.append((rr, c))
        if same:
            ok = [s for s in same if s[0] >= target - 0.25]
            rr, c = min(ok, key=lambda s: s[1]["price_eur"]) if ok else max(same, key=lambda s: s[0])
            bios = ""
            if plat["socket"] == "AM4":
                bios = "Su schede madri B350/B450/X370 potrebbe servire un aggiornamento del BIOS prima del montaggio."
            elif plat["socket"] == "LGA1700":
                bios = "Su schede serie 600 aggiorna il BIOS per le CPU di 13ª/14ª gen. (e per i fix di stabilità Intel)."
            upgrades.append(_upgrade("CPU", c, 1 if gap >= 1.5 else 2,
                                     f"CPU compatibile con il socket {plat['socket']} (voto gaming CPU "
                                     f"{cpu_rating:.1f} → {rr:.1f}), nessun cambio di scheda madre.",
                                     _gain(base, _sim(report, "cpu", c)), note=bios or None))
        else:
            bundle = _platform_bundle(data, target)
            if bundle:
                b_item = {"name": " + ".join(p["name"] for p in bundle), "parts": bundle,
                          "price_eur": sum(p["price_eur"] for p in bundle)}
                upgrades.append({
                    "component": "Piattaforma", "priority": 2 if gap >= 1.5 else 3,
                    "name": b_item["name"], "price_eur": b_item["price_eur"],
                    "reason": f"Il socket attuale ({plat['socket']}) non offre CPU sufficientemente più veloci: "
                              "serve cambiare CPU + scheda madre + RAM.",
                    "gain": _gain(base, _sim(report, "platform", b_item)),
                    "note": "Prezzo complessivo dei 3 componenti. Verifica dissipatore (attacco socket) e case.",
                    "parts": [{"name": p["name"], "price_eur": p["price_eur"],
                               "links": prices_mod.search_links(p["name"])} for p in bundle],
                    "links": {},
                })

    upgrades.sort(key=lambda u: (u["priority"], -(u["gain"]["overall"]["delta_raw"] if u.get("gain") else 0)))
    issues.sort(key=lambda i: SEV_ORDER[i["severity"]])

    score = max(0, min(100, round(100 - penalty)))
    verdict = "Bilanciata" if score >= 80 else ("Leggermente sbilanciata" if score >= 60 else "Sbilanciata")
    main_ups = [u for u in upgrades if u["priority"] <= 2 and u.get("price_eur")]
    return {
        "balance_score": score,
        "verdict": verdict,
        "issues": issues,
        "free_fixes": free_fixes,
        "upgrades": upgrades,
        "recommended_total_eur": sum(u["price_eur"] for u in main_ups),
        "prices_updated": data.get("updated"),
        "prices_source": data.get("source"),
        "prices_age_days": prices_mod.age_days(data),
    }


def _upgrade(component: str, item: dict, priority: int, reason: str, gain: dict, note: str | None = None) -> dict:
    return {"component": component, "priority": priority, "name": item["name"], "price_eur": item.get("price_eur"),
            "prev_price_eur": item.get("prev_price_eur"), "reason": reason, "gain": gain, "note": note,
            "links": prices_mod.search_links(item["name"]), "item_id": item.get("id")}


def _platform_bundle(data: dict, target_rating: float) -> list[dict] | None:
    """Sceglie la combinazione CPU+scheda madre+RAM più economica che raggiunge il voto CPU richiesto."""
    mobos = {m["socket"]: m for m in _cat(data, "mobo")}
    rams: dict[str, dict] = {}
    for r in sorted(_cat(data, "ram"), key=lambda r: r["price_eur"]):
        if not r.get("laptop") and r["capacity_gb"] >= 32:
            rams.setdefault(r["mem"], r)
    best = None
    for c in _cat(data, "cpu"):
        sock = c.get("socket")
        if sock not in ("AM5", "LGA1851") or sock not in mobos:
            continue
        m = mobos[sock]
        r = rams.get(m.get("mem", "DDR5"))
        if not r:
            continue
        pp = cpu_perf(c["name"])
        rr = interp(pp["gaming"], CPU_GAMING) - cpu_era(pp, c["name"])["penalty"]
        cost = c["price_eur"] + m["price_eur"] + r["price_eur"]
        ok = rr >= target_rating - 0.25
        key = (0 if ok else 1, cost if ok else -rr)
        if best is None or key < best[0]:
            best = (key, [c, m, r])
    return best[1] if best else None
