"""Esportazione del report in testo o JSON."""
from __future__ import annotations

import json
import time


def stars_text(r: float) -> str:
    full = int(r)
    half = (r - full) >= 0.5
    return "★" * full + ("½" if half else "") + "☆" * (5 - full - (1 if half else 0))


def to_text(report: dict, ev: dict, an: dict, speed: dict | None = None) -> str:
    L = []
    w = L.append
    w("PC ANALYZER - REPORT")
    w(f"Generato il {time.strftime('%d/%m/%Y %H:%M')}")
    w("=" * 60)
    s = report.get("system", {})
    w(f"Sistema: {s.get('manufacturer', '')} {s.get('model', '')} ({'Portatile' if ev['is_laptop'] else 'Desktop'})")
    w(f"OS: {report.get('os', {}).get('name', '')} build {report.get('os', {}).get('build', '')}")
    w("")
    w("VOTI")
    names = {"gaming": "Gaming", "office": "Ufficio", "productivity": "Produttività", "overall": "Complessivo"}
    for k, n in names.items():
        r = ev["ratings"][k]
        lab = ev["labels"].get(k, "")
        w(f"  {n:<14} {r:.1f}/5  {stars_text(r)}  {lab}")
    w("")
    c = report.get("cpu", {})
    w("CPU")
    w(f"  {c.get('name')}  |  {c.get('cores')} core / {c.get('threads')} thread  |  base {c.get('base_clock_mhz')} MHz")
    w(f"  Socket: {ev['platform']['socket']}  |  Cache L2 {c.get('l2_kb')} KB, L3 {c.get('l3_kb')} KB")
    mb = report.get("motherboard", {})
    w("SCHEDA MADRE")
    w(f"  {mb.get('manufacturer')} {mb.get('model')}  |  BIOS {mb.get('bios_version')} ({mb.get('bios_date')})")
    ram = report.get("ram", {})
    w("MEMORIA")
    w(f"  {ram.get('total_gb')} GB {ram.get('type')} @ {ram.get('configured_mhz')} MT/s  |  {ram.get('channel')}  |  "
      f"slot {ram.get('modules_count')}/{ram.get('slots_total') or '?'}")
    for m in ram.get("modules", []):
        w(f"   - {m.get('slot')}: {m.get('capacity_gb')} GB {m.get('manufacturer')} {m.get('part_number')} "
          f"({m.get('configured_mhz')} MT/s)")
    w("SCHEDA VIDEO")
    for g in report.get("gpus", []):
        w(f"  {g.get('name')}  |  {g.get('vram_gb')} GB  |  driver {g.get('driver')}"
          f"{'  [integrata]' if g.get('is_integrated') else ''}")
    w("ARCHIVIAZIONE")
    for d in report.get("disks", []):
        w(f"  {d.get('model')}  |  {d.get('media')} {d.get('bus')}  |  {d.get('size_gb')} GB"
          f"{'  [sistema]' if d.get('is_system') else ''}")
    w("")
    w(f"BILANCIAMENTO: {an['balance_score']}/100 - {an['verdict']}")
    for i in an["issues"]:
        w(f"  [{i['severity'].upper()}] {i['title']}: {i['detail']}")
    for f in an["free_fixes"]:
        w(f"  [GRATIS] {f['title']}: {f['detail']}")
    w("")
    w(f"UPGRADE CONSIGLIATI (prezzi aggiornati al {an.get('prices_updated')}, fonte: {an.get('prices_source')})")
    for u in an["upgrades"]:
        p = f"{u['price_eur']} €" if u.get("price_eur") else "prezzo variabile"
        g = u["gain"]
        w(f"  P{u['priority']} {u['component']}: {u['name']} - {p}")
        w(f"     {u['reason']}")
        w(f"     Gaming {g['gaming']['before']}→{g['gaming']['after']}, Ufficio {g['office']['before']}→"
          f"{g['office']['after']}, Produttività {g['productivity']['before']}→{g['productivity']['after']}")
        if u.get("note"):
            w(f"     Nota: {u['note']}")
    if speed:
        w("")
        w(f"CONNESSIONE ({speed.get('engine')}, {speed.get('timestamp')})")
        w(f"  Download {speed.get('download_mbps')} Mbps | Upload {speed.get('upload_mbps')} Mbps | "
          f"Ping {speed.get('ping_ms')} ms | ISP {speed.get('isp')}")
    return "\n".join(L)


def to_json(report: dict, ev: dict, an: dict, speed: dict | None = None) -> str:
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items() if not k.startswith("_")}
        if isinstance(o, list):
            return [clean(v) for v in o]
        return o
    return json.dumps(clean({"hardware": report, "evaluation": ev, "balance": an, "speedtest": speed}),
                      indent=2, ensure_ascii=False)
