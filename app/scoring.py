"""
Identificazione delle prestazioni dei componenti e calcolo dei voti (1-5, con mezzi voti)
per Gaming, Ufficio e Produttività.
"""
from __future__ import annotations

import datetime as dt
import re
from functools import lru_cache

from .paths import load_json, resource_dir, user_dir

# --------------------------------------------------------------------------- database
@lru_cache(maxsize=1)
def _db() -> dict:
    # un components_db.json in cartella utente (se presente) ha la precedenza
    db = load_json(user_dir() / "components_db.json") or load_json(resource_dir() / "components_db.json", {})
    for key in ("cpus", "gpus"):
        for e in db.get(key, []):
            e["_re"] = re.compile(r"(?<![a-z0-9])" + re.escape(e["token"]) + r"(?![a-z0-9])")
        # token più lunghi/specifici per primi ("rtx 4060 ti" prima di "rtx 4060")
        db[key] = sorted(db.get(key, []), key=lambda e: -len(e["token"]))
    return db


def _norm(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\((r|tm)\)|®|™", " ", s)
    s = re.sub(r"@.*$", "", s)                     # "@ 3.60GHz"
    s = re.sub(r"\b\d+-core\b|\bprocessor\b|\bcpu\b", " ", s)
    s = re.sub(r"w/|with", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def interp(x: float, pts: list[tuple[float, float]]) -> float:
    """Interpolazione lineare a tratti, saturata agli estremi."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def half_round(x: float) -> float:
    return max(1.0, min(5.0, round(x * 2) / 2))


# --------------------------------------------------------------------------- epoca
def current_year() -> int:
    return dt.date.today().year


def db_year() -> int:
    try:
        return int(str(_db().get("version", "2026"))[:4])
    except ValueError:
        return 2026


def era_decay() -> float:
    """Se il database non viene aggiornato, ogni anno che passa tutto l'hardware 'perde' il 15%:
    i nuovi giochi e software alzano l'asticella anche senza nuovi modelli nel database."""
    return 0.85 ** max(0, current_year() - db_year())


def gpu_era(gp: dict) -> dict:
    """Penalità per età e funzionalità mancanti rispetto agli standard attuali."""
    if gp.get("integrated"):
        return {"age": None, "penalty": 0.0, "notes": []}
    tok = gp.get("matched") or ""
    notes, pen = [], 0.0
    age = current_year() - gp["year"] if gp.get("year") else None
    if age is not None and age > 2:
        a = min(0.5, (age - 2) * 0.1)
        pen += a
        notes.append(f"Ha {age} anni: driver e ottimizzazioni dei giochi nuovi la privilegiano sempre meno")
    if tok.startswith(("gtx", "gt ")) or re.match(r"rx (5\d{2}|5\d{3}|vega)|radeon vii", tok):
        pen += 0.35
        notes.append("Niente ray tracing hardware né upscaling IA (DLSS/FSR 4): alcuni giochi recenti richiedono il ray tracing")
    elif re.match(r"rx 6\d{3}", tok):
        pen += 0.25
        notes.append("Ray tracing debole e niente FSR 4 (upscaling IA solo su RX 9000)")
    elif re.match(r"rx 7\d{3}", tok):
        pen += 0.15
        notes.append("Niente FSR 4 ufficiale: l'upscaling resta di qualità inferiore a DLSS 4 / FSR 4")
    vram = gp.get("vram") or 0
    if 0 < vram < 8 and gp["idx"] >= 12:
        pen += 0.3
        notes.append(f"{vram:g} GB di VRAM sono sotto il minimo attuale (8 GB) per i giochi recenti")
    elif vram == 8 and gp["idx"] >= 28:
        pen += 0.15
        notes.append("8 GB di VRAM limitano texture alte e 1440p in diversi giochi del " + str(current_year()))
    return {"age": age, "penalty": round(min(pen, 1.0), 2), "notes": notes}


def cpu_era(cp: dict, name: str) -> dict:
    notes, pen = [], 0.0
    age = current_year() - cp["year"] if cp.get("year") else None
    if age is not None and age > 3:
        pen += min(0.4, (age - 3) * 0.08)
        notes.append(f"Ha {age} anni")
    w11 = windows11_supported(name)
    if w11 is False:
        notes.append("Non supportata ufficialmente da Windows 11 (Windows 10 non riceve più aggiornamenti "
                     "gratuiti da ottobre 2025)")
    return {"age": age, "penalty": round(pen, 2), "notes": notes, "win11": w11}


def windows11_supported(name: str):
    """True/False se determinabile, None se sconosciuto. Requisiti: Intel 8ª gen+ / Ryzen 2000+ (Zen+)."""
    n = _norm(name)
    m = re.search(r"i[3579]-(\d{4,5})", n)
    if m:
        num = m.group(1)
        gen = int(num[:2]) if len(num) == 5 else int(num[0])
        return gen >= 8
    if re.search(r"ultra [579]", n):
        return True
    m = re.search(r"ryzen (?:\d|threadripper) (?:pro )?(\d)(\d{3})", n)
    if m:
        series, rest = int(m.group(1)), m.group(2)
        if series == 1:
            return False
        if series == 2 and re.search(r"2\d00(g|ge|u|h)\b", n):
            return False  # APU 2000 sono Zen 1
        return True
    if re.search(r"core2|core 2|pentium d|athlon (64|ii)|phenom|fx-\d{4}", n):
        return False
    return None


# --------------------------------------------------------------------------- CPU
def cpu_perf(name: str, cores: int = 0, threads: int = 0, base_mhz: int = 0) -> dict:
    n = _norm(name)
    vendor = "amd" if ("amd" in n or "ryzen" in n) else ("intel" if "intel" in n or "core" in n else "")
    for e in _db().get("cpus", []):
        if e["vendor"] != vendor:
            continue
        m = e["_re"].search(n)
        if not m and vendor == "intel":
            # 12400F / 14600KF / 12400T -> stessa famiglia
            m = re.search(r"(?<![a-z0-9])" + re.escape(e["token"]) + r"[ft](?![a-z0-9])", n)
        if m:
            gaming = e.get("gaming") or (0.75 * e["st"] + 0.25 * min(e["mt"] * 1.6, 100))
            k = era_decay()
            return {"st": e["st"] * k, "mt": e["mt"] * k, "gaming": gaming * k, "year": e.get("year"),
                    "tdp": e.get("tdp"), "matched": e["token"], "estimated": False, "vendor": vendor}
    return _cpu_estimate(n, vendor, cores, threads, base_mhz)


def _cpu_estimate(n: str, vendor: str, cores: int, threads: int, base_mhz: int) -> dict:
    """Stima euristica per CPU non presenti nel database."""
    st = 35.0
    year = None
    mobile_pen = 0
    m = re.search(r"i([3579])-(\d{4,5})([a-z]*)", n)
    if m:
        tier, num, suf = int(m.group(1)), m.group(2), m.group(3)
        gen = int(num[:2]) if len(num) == 5 else int(num[0])
        base = {2: 30, 3: 33, 4: 40, 5: 42, 6: 45, 7: 50, 8: 52, 9: 54, 10: 56, 11: 68, 12: 82, 13: 90, 14: 93}
        st = base.get(gen, 35) + {3: -6, 5: -3, 7: 0, 9: 3}[tier]
        year = 2010 + gen if gen >= 2 else None
        if suf.startswith(("u", "y", "g")):
            mobile_pen = 10
        elif suf.startswith("h"):
            mobile_pen = 3
    m = re.search(r"ultra ([579]) (\d)(\d{2})([a-z]*)", n)
    if m:
        st = {1: 78, 2: 95}.get(int(m.group(2)), 85) + {5: -4, 7: 0, 9: 3}[int(m.group(1))]
        if m.group(4).startswith(("u", "v")):
            mobile_pen = 8
    m = re.search(r"ryzen (?:ai )?\d (?:pro )?(\d)(\d{3})([a-z0-9]*)", n)
    if m:
        series = int(m.group(1))
        st = {1: 40, 2: 46, 3: 56, 4: 55, 5: 68, 6: 70, 7: 86, 8: 80, 9: 95}.get(series, 50)
        suf = m.group(3)
        if suf.startswith("u"):
            mobile_pen = 8
        elif suf.startswith("h"):
            mobile_pen = 3
    if "celeron" in n or "pentium" in n or "athlon" in n or re.search(r"\bn\d{3,4}\b", n):
        st = 30
    st = max(15, st - mobile_pen)
    cores = cores or 4
    threads = threads or cores
    eff = cores + 0.25 * max(0, threads - cores)
    mt = min(100, st * eff * 0.045)
    gaming = 0.75 * st + 0.25 * min(mt * 1.6, 100)
    k = era_decay()
    st, mt, gaming = st * k, mt * k, gaming * k
    return {"st": round(st, 1), "mt": round(mt, 1), "gaming": round(gaming, 1), "year": year, "tdp": None,
            "matched": None, "estimated": True, "vendor": vendor}


def cpu_platform(name: str, ram_type: str = "", is_laptop: bool = False) -> dict:
    """Socket, tipo memoria e possibilità di upgrade CPU."""
    n = _norm(name)
    mobile = bool(re.search(r"\d{4,5}(u|h|hs|hx|hk|y|p|g\d)\b|\d{3}(h|u|v|hx)\b|ryzen ai|\bm\d\b", n)) or is_laptop
    sock, mem = "Sconosciuto", ram_type or ""
    m = re.search(r"ryzen (?:\d|threadripper) (?:pro )?(\d)(\d{3})", n)
    if m and not mobile:
        s = int(m.group(1))
        sock = "AM4" if s <= 5 else "AM5"
        mem = mem or ("DDR4" if s <= 5 else "DDR5")
    m = re.search(r"i[3579]-(\d{4,5})", n)
    if m and not mobile:
        num = m.group(1)
        gen = int(num[:2]) if len(num) == 5 else int(num[0])
        sock = {12: "LGA1700", 13: "LGA1700", 14: "LGA1700", 10: "LGA1200", 11: "LGA1200",
                6: "LGA1151", 7: "LGA1151", 8: "LGA1151-v2", 9: "LGA1151-v2", 4: "LGA1150",
                3: "LGA1155", 2: "LGA1155"}.get(gen, sock)
        mem = mem or ("DDR3" if gen <= 5 else "DDR4")
    if re.search(r"ultra [579] 2\d{2}k?f?\b", n) and not mobile:
        sock, mem = "LGA1851", "DDR5"
    return {"socket": "Integrato (portatile)" if mobile else sock, "mem": mem, "mobile": mobile,
            "cpu_upgradable": (not mobile) and sock != "Sconosciuto"}


# --------------------------------------------------------------------------- GPU
def gpu_perf(name: str, vram_gb: float = 0, integrated: bool = False) -> dict:
    n = _norm(name)
    laptop = bool(re.search(r"laptop|mobile|max-q|\d{4}m\b", n))
    for e in _db().get("gpus", []):
        if e["_re"].search(n):
            idx = e["idx"] * (0.75 if laptop and e["vram"] else 1.0) * era_decay()
            return {"idx": round(idx, 1), "vram": vram_gb or e["vram"], "year": e.get("year"),
                    "tdp": e.get("tdp"), "matched": e["token"], "estimated": False,
                    "laptop": laptop, "integrated": integrated or e["vram"] == 0}
    # stima per VRAM
    if integrated or not vram_gb:
        idx = 1.5
    else:
        idx = interp(vram_gb, [(1, 2), (2, 3), (4, 6), (6, 10), (8, 16), (12, 26), (16, 38), (24, 55)])
    return {"idx": idx, "vram": vram_gb, "year": None, "tdp": None, "matched": None,
            "estimated": True, "laptop": laptop, "integrated": integrated}


# --------------------------------------------------------------------------- tabelle voti
GPU_GAMING = [(0, 0.5), (3, 1), (8, 1.5), (13, 2), (20, 2.5), (26, 3), (34, 3.5), (44, 4), (55, 4.5), (65, 5)]
CPU_GAMING = [(25, 1), (40, 2), (55, 3), (70, 4), (88, 5)]
CPU_OFFICE = [(20, 1), (35, 2.5), (50, 3.5), (62, 4.5), (72, 5)]
CPU_PROD = [(8, 1), (18, 2), (30, 3), (48, 4), (80, 5)]
GPU_PROD = [(1, 1.5), (10, 2.5), (25, 3.5), (45, 4.5), (65, 5)]
RAM_GAMING = [(4, 0.5), (8, 1.5), (16, 3.8), (32, 5)]
RAM_OFFICE = [(4, 1), (8, 3), (16, 4.5), (32, 5)]
RAM_PROD = [(8, 1), (16, 2.5), (32, 4), (64, 5)]

GAMING_LABELS = {
    1: "Solo giochi leggeri / indie a dettagli minimi",
    2: "eSport e 1080p a dettagli bassi",
    3: "1080p a dettagli medio-alti",
    4: "1440p a dettagli alti / 1080p alto refresh",
    5: "4K o 1440p ad alto refresh rate, ray tracing",
}
OFFICE_LABELS = {
    1: "Lento anche per navigazione e documenti",
    2: "Uso base con rallentamenti nel multitasking",
    3: "Ufficio e navigazione fluidi",
    4: "Multitasking pesante senza problemi",
    5: "Eccellente per qualsiasi attività da ufficio",
}
PROD_LABELS = {
    1: "Non adatto a editing o rendering",
    2: "Foto editing leggero",
    3: "Editing foto/video 1080p, programmazione",
    4: "Editing video 4K, rendering 3D, VM",
    5: "Workstation: rendering pesante, IA locale, compilazioni grandi",
}


GAMING_HALF_LABELS = {
    1.5: "Giochi leggeri ed eSport a dettagli bassi",
    2.5: "1080p a dettagli medi nei giochi recenti",
    3.5: "1080p dettagli alti / 1440p dettagli medi",
    4.5: "1440p alto refresh / 4K con upscaling",
}


def _label(table: dict, r: float) -> str:
    if table is GAMING_LABELS and r in GAMING_HALF_LABELS:
        return GAMING_HALF_LABELS[r]
    return table[max(1, min(5, int(r)))]


def _combine(parts: dict[str, tuple[float, float]]) -> float:
    """parts: nome -> (voto 0-5, peso). Media pesata con penalità collo di bottiglia."""
    tot = sum(w for _, w in parts.values())
    mean = sum(v * w for v, w in parts.values()) / tot
    key = [v for v, w in parts.values() if w >= 0.2]
    worst = min(key) if key else mean
    return 0.7 * mean + 0.3 * min(worst, mean)


# --------------------------------------------------------------------------- storage
def storage_rating(disks: list[dict]) -> dict:
    sysd = next((d for d in disks if d.get("is_system")), disks[0] if disks else None)
    if not sysd:
        return {"rating": 3.0, "system_type": "Sconosciuto", "ssd_total_gb": 0, "hdd_total_gb": 0}
    media = (sysd.get("media") or "").upper()
    bus = (sysd.get("bus") or "").upper()
    if media == "HDD":
        r, t = 1.5, "HDD"
    elif bus == "NVME":
        r, t = 4.8, "SSD NVMe"
    elif media == "SSD":
        r, t = 3.9, "SSD SATA"
    else:
        r, t = 3.0, "Sconosciuto"
    ssd_total = sum(d.get("size_gb", 0) for d in disks if (d.get("media") or "").upper() == "SSD"
                    and (d.get("bus") or "").upper() != "USB")
    hdd_total = sum(d.get("size_gb", 0) for d in disks if (d.get("media") or "").upper() == "HDD")
    if t != "HDD":
        if ssd_total < 250:
            r -= 0.7
        elif ssd_total < 500:
            r -= 0.3
        elif ssd_total >= 1900:
            r += 0.2
    return {"rating": max(0.5, min(5, r)), "system_type": t, "ssd_total_gb": ssd_total, "hdd_total_gb": hdd_total,
            "system_disk": sysd}


# --------------------------------------------------------------------------- analisi principale
def evaluate(report: dict) -> dict:
    cpu = report.get("cpu", {})
    ram = report.get("ram", {})
    gpus = report.get("gpus", [])
    is_laptop = bool(report.get("system", {}).get("is_laptop"))

    cp = cpu_perf(cpu.get("name", ""), cpu.get("cores", 0), cpu.get("threads", 0), cpu.get("base_clock_mhz", 0))
    plat = cpu_platform(cpu.get("name", ""), (ram.get("type") or "").split("/")[0], is_laptop)

    main_gpu = gpus[0] if gpus else {"name": "Nessuna", "vram_gb": 0, "is_integrated": True}
    gp = gpu_perf(main_gpu.get("name", ""), main_gpu.get("vram_gb", 0), main_gpu.get("is_integrated", False))

    ram_gb = float(ram.get("total_gb") or 0)
    ram_mhz = ram.get("configured_mhz") or ram.get("rated_mhz") or 0
    ram_type = (ram.get("type") or plat.get("mem") or "").upper()
    single = ram.get("modules_count") == 1
    speed_adj = 0.0
    if "DDR5" in ram_type and ram_mhz >= 6000:
        speed_adj = 0.2
    elif "DDR4" in ram_type and 0 < ram_mhz < 2666:
        speed_adj = -0.3
    elif "DDR3" in ram_type:
        speed_adj = -0.4
    chan_adj = -0.5 if single else 0.0

    st = storage_rating(report.get("disks", []))

    # --- voti per componente
    comp = {
        "gpu_gaming": interp(gp["idx"], GPU_GAMING),
        "cpu_gaming": interp(cp["gaming"], CPU_GAMING),
        "cpu_office": interp(cp["st"], CPU_OFFICE),
        "cpu_prod": interp(cp["mt"], CPU_PROD),
        "gpu_prod": interp(gp["idx"], GPU_PROD),
        "ram_gaming": max(0, interp(ram_gb, RAM_GAMING) + speed_adj + chan_adj),
        "ram_office": max(0, interp(ram_gb, RAM_OFFICE) + speed_adj / 2),
        "ram_prod": max(0, interp(ram_gb, RAM_PROD) + speed_adj + chan_adj / 2),
        "storage": st["rating"],
    }
    g_era = gpu_era(gp)
    c_era = cpu_era(cp, cpu.get("name", ""))
    comp["gpu_gaming"] -= g_era["penalty"]
    comp["gpu_prod"] -= g_era["penalty"] / 2
    comp["cpu_gaming"] -= c_era["penalty"]
    comp["cpu_prod"] -= c_era["penalty"] / 2
    if c_era["win11"] is False:
        comp["cpu_office"] -= 0.5

    gaming = _combine({"gpu": (comp["gpu_gaming"], 0.55), "cpu": (comp["cpu_gaming"], 0.25),
                       "ram": (comp["ram_gaming"], 0.12), "storage": (comp["storage"], 0.08)})
    office = _combine({"cpu": (comp["cpu_office"], 0.4), "ram": (comp["ram_office"], 0.3),
                       "storage": (comp["storage"], 0.3)})
    prod = _combine({"cpu": (comp["cpu_prod"], 0.45), "ram": (comp["ram_prod"], 0.2),
                     "gpu": (comp["gpu_prod"], 0.2), "storage": (comp["storage"], 0.15)})

    ratings = {
        "gaming": half_round(gaming),
        "office": half_round(office),
        "productivity": half_round(prod),
    }
    ratings["overall"] = half_round((ratings["gaming"] + ratings["office"] + ratings["productivity"]) / 3)

    return {
        "ratings": ratings,
        "raw": {"gaming": round(gaming, 2), "office": round(office, 2), "productivity": round(prod, 2)},
        "labels": {
            "gaming": _label(GAMING_LABELS, ratings["gaming"]),
            "office": _label(OFFICE_LABELS, ratings["office"]),
            "productivity": _label(PROD_LABELS, ratings["productivity"]),
        },
        "component_ratings": {k: round(max(0, min(5, v)), 2) for k, v in comp.items()},
        "cpu_perf": cp,
        "gpu_perf": gp,
        "platform": plat,
        "storage": st,
        "ram_info": {"gb": ram_gb, "mhz": ram_mhz, "type": ram_type, "single_channel": single},
        "is_laptop": is_laptop or plat["mobile"],
        "era": {"year": current_year(), "db_year": db_year(), "decay": round(era_decay(), 3),
                "gpu": g_era, "cpu": c_era},
    }
