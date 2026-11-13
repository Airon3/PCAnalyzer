"""
Rilevamento hardware.

Su Windows usa un unico script PowerShell (Get-CimInstance / Get-PhysicalDisk)
che restituisce tutto in JSON: niente dipendenze native (pywin32) e funziona
anche da thread secondari. Su Linux c'è un fallback basato su /proc, /sys,
lspci e lsblk (utile per sviluppo e test).
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
from typing import Any

import psutil

IS_WINDOWS = sys.platform.startswith("win")

# SMBIOSMemoryType -> nome
SMBIOS_MEM_TYPES = {
    20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3", 26: "DDR4",
    27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5",
}

PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$r = [ordered]@{}
$r.cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,CurrentClockSpeed,L2CacheSize,L3CacheSize,SocketDesignation)
$r.board = @(Get-CimInstance Win32_BaseBoard | Select-Object Manufacturer,Product,Version)
$r.bios = @(Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,@{n='ReleaseDate';e={ if ($_.ReleaseDate) { $_.ReleaseDate.ToString('yyyy-MM-dd') } else { '' } }})
$r.system = @(Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory,PCSystemType)
$r.os = @(Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture)
$r.mem = @(Get-CimInstance Win32_PhysicalMemory | Select-Object BankLabel,DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber,SMBIOSMemoryType,FormFactor)
$r.memarray = @(Get-CimInstance Win32_PhysicalMemoryArray | Select-Object MemoryDevices,MaxCapacityEx,Use)
$r.gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,PNPDeviceID,AdapterCompatibility)
$r.gpureg = @(Get-ItemProperty 'HKLM:\SYSTEM\ControlSet001\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*' | Select-Object DriverDesc,@{n='qw';e={$_.'HardwareInformation.qwMemorySize'}},@{n='ms';e={$_.'HardwareInformation.MemorySize'}})
$r.pdisk = @(Get-PhysicalDisk | Select-Object DeviceId,FriendlyName,@{n='MediaType';e={"$($_.MediaType)"}},@{n='BusType';e={"$($_.BusType)"}},Size,@{n='Health';e={"$($_.HealthStatus)"}},SpindleSpeed)
$r.part = @(Get-Partition | Where-Object { $_.DriveLetter } | Select-Object DiskNumber,@{n='DriveLetter';e={"$($_.DriveLetter)"}})
$r.vol = @(Get-Volume | Where-Object { $_.DriveLetter } | Select-Object @{n='DriveLetter';e={"$($_.DriveLetter)"}},Size,SizeRemaining,FileSystemLabel)
$r.sysdrive = $env:SystemDrive
$r | ConvertTo-Json -Depth 5 -Compress
"""


# --------------------------------------------------------------------------- utilità
def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _clean(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    s = re.sub(r"\((R|TM|tm|r)\)|®|™", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _int(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, list):  # REG_BINARY restituito come array di byte
            return int.from_bytes(bytes(int(b) & 0xFF for b in v), "little")
        return int(v)
    except (TypeError, ValueError):
        return default


def _gb(b: Any) -> float:
    return round(_int(b) / (1024 ** 3), 1)


def _run(cmd: list[str], timeout: int = 60) -> str:
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, timeout=timeout,
                                  encoding="utf-8", errors="replace")
    if IS_WINDOWS:
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kwargs).stdout or ""
    except Exception:
        return ""


def _empty_report() -> dict:
    return {
        "os": {}, "system": {}, "cpu": {}, "motherboard": {},
        "ram": {"total_gb": 0, "modules": []}, "gpus": [], "disks": [],
    }


# --------------------------------------------------------------------------- Windows
def _scan_windows() -> dict:
    raw_txt = _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-Command", PS_SCRIPT], timeout=90)
    try:
        raw = json.loads(raw_txt[raw_txt.find("{"):]) if "{" in raw_txt else {}
    except json.JSONDecodeError:
        raw = {}

    rep = _empty_report()

    # OS / sistema
    os_ = (_as_list(raw.get("os")) or [{}])[0]
    rep["os"] = {
        "name": _clean(os_.get("Caption")) or platform.platform(),
        "version": os_.get("Version", ""),
        "build": os_.get("BuildNumber", ""),
        "arch": os_.get("OSArchitecture", platform.machine()),
    }
    sys_ = (_as_list(raw.get("system")) or [{}])[0]
    rep["system"] = {
        "manufacturer": _clean(sys_.get("Manufacturer")),
        "model": _clean(sys_.get("Model")),
        "is_laptop": _int(sys_.get("PCSystemType")) == 2,
    }

    # CPU
    cpus = _as_list(raw.get("cpu"))
    c = cpus[0] if cpus else {}
    rep["cpu"] = {
        "name": _clean(c.get("Name")) or platform.processor(),
        "vendor": _clean(c.get("Manufacturer")),
        "cores": _int(c.get("NumberOfCores")) or psutil.cpu_count(logical=False) or 0,
        "threads": _int(c.get("NumberOfLogicalProcessors")) or psutil.cpu_count() or 0,
        "base_clock_mhz": _int(c.get("MaxClockSpeed")),
        "current_clock_mhz": _int(c.get("CurrentClockSpeed")),
        "l2_kb": _int(c.get("L2CacheSize")),
        "l3_kb": _int(c.get("L3CacheSize")),
        "socket_reported": _clean(c.get("SocketDesignation")),
        "sockets": len(cpus) or 1,
    }

    # Scheda madre + BIOS
    b = (_as_list(raw.get("board")) or [{}])[0]
    bios = (_as_list(raw.get("bios")) or [{}])[0]
    rep["motherboard"] = {
        "manufacturer": _clean(b.get("Manufacturer")),
        "model": _clean(b.get("Product")),
        "version": _clean(b.get("Version")),
        "bios_vendor": _clean(bios.get("Manufacturer")),
        "bios_version": _clean(bios.get("SMBIOSBIOSVersion")),
        "bios_date": bios.get("ReleaseDate", ""),
    }

    # RAM
    modules = []
    for m in _as_list(raw.get("mem")):
        t = SMBIOS_MEM_TYPES.get(_int(m.get("SMBIOSMemoryType")), "")
        modules.append({
            "slot": _clean(m.get("DeviceLocator")) or _clean(m.get("BankLabel")),
            "capacity_gb": _gb(m.get("Capacity")),
            "rated_mhz": _int(m.get("Speed")),
            "configured_mhz": _int(m.get("ConfiguredClockSpeed")),
            "manufacturer": _clean(m.get("Manufacturer")),
            "part_number": _clean(m.get("PartNumber")),
            "type": t,
        })
    slots = sum(_int(a.get("MemoryDevices")) for a in _as_list(raw.get("memarray"))
                if _int(a.get("Use"), 3) == 3) or None
    total = _gb(sys_.get("TotalPhysicalMemory")) or round(psutil.virtual_memory().total / 1024 ** 3, 1)
    rep["ram"] = _summarize_ram(modules, total, slots)

    # GPU (VRAM corretta dal registro: AdapterRAM è limitato a 4 GB)
    reg = _as_list(raw.get("gpureg"))
    gpus = []
    for g in _as_list(raw.get("gpu")):
        name = _clean(g.get("Name"))
        if not name or "basic display" in name.lower() or "remote" in name.lower():
            continue
        vram = _int(g.get("AdapterRAM"))
        for rg in reg:
            if _clean(rg.get("DriverDesc")) == name:
                vram = max(vram, _int(rg.get("qw")), _int(rg.get("ms")))
        res = ""
        if g.get("CurrentHorizontalResolution"):
            res = f'{g.get("CurrentHorizontalResolution")}x{g.get("CurrentVerticalResolution")} @ {g.get("CurrentRefreshRate")} Hz'
        gpus.append({
            "name": name,
            "vendor": _clean(g.get("AdapterCompatibility")),
            "vram_gb": round(vram / 1024 ** 3, 1) if vram else 0,
            "driver": g.get("DriverVersion", ""),
            "display": res,
        })
    rep["gpus"] = _mark_integrated(gpus)

    # Dischi
    letters_by_disk: dict[str, list[str]] = {}
    for p in _as_list(raw.get("part")):
        letters_by_disk.setdefault(str(p.get("DiskNumber")), []).append(str(p.get("DriveLetter")))
    vols = {str(v.get("DriveLetter")): v for v in _as_list(raw.get("vol"))}
    sysdrive = str(raw.get("sysdrive") or "C:").rstrip(":\\")
    disks = []
    for d in _as_list(raw.get("pdisk")):
        did = str(d.get("DeviceId"))
        letters = letters_by_disk.get(did, [])
        free = sum(_int(vols[l].get("SizeRemaining")) for l in letters if l in vols)
        used_total = sum(_int(vols[l].get("Size")) for l in letters if l in vols)
        bus = str(d.get("BusType") or "")
        media = str(d.get("MediaType") or "")
        if media in ("Unspecified", "0", ""):
            media = "SSD" if bus.upper() == "NVME" else ("HDD" if _int(d.get("SpindleSpeed")) > 0 else "Sconosciuto")
        disks.append({
            "model": _clean(d.get("FriendlyName")),
            "media": media,                     # SSD / HDD
            "bus": bus,                         # NVMe / SATA / USB / RAID
            "size_gb": _gb(d.get("Size")),
            "letters": letters,
            "free_gb": round(free / 1024 ** 3, 1) if used_total else None,
            "volumes_gb": round(used_total / 1024 ** 3, 1) if used_total else None,
            "health": d.get("Health", ""),
            "is_system": sysdrive in letters,
        })
    rep["disks"] = disks
    return rep


# --------------------------------------------------------------------------- Linux (sviluppo)
def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def _scan_linux() -> dict:
    rep = _empty_report()
    rep["os"] = {"name": platform.platform(), "version": platform.release(), "build": "", "arch": platform.machine()}
    chassis = _read("/sys/class/dmi/id/chassis_type")
    rep["system"] = {
        "manufacturer": _read("/sys/class/dmi/id/sys_vendor"),
        "model": _read("/sys/class/dmi/id/product_name"),
        "is_laptop": chassis in {"8", "9", "10", "14", "31", "32"},
    }
    cpuinfo = _read("/proc/cpuinfo")
    name = (re.search(r"model name\s*:\s*(.+)", cpuinfo) or [None, platform.processor()])[1]
    vendor = (re.search(r"vendor_id\s*:\s*(.+)", cpuinfo) or [None, ""])[1]
    freq = psutil.cpu_freq()
    rep["cpu"] = {
        "name": _clean(name), "vendor": vendor,
        "cores": psutil.cpu_count(logical=False) or 0, "threads": psutil.cpu_count() or 0,
        "base_clock_mhz": int(freq.max) if freq and freq.max else 0,
        "current_clock_mhz": int(freq.current) if freq else 0,
        "l2_kb": 0, "l3_kb": 0, "socket_reported": "", "sockets": 1,
    }
    rep["motherboard"] = {
        "manufacturer": _read("/sys/class/dmi/id/board_vendor"),
        "model": _read("/sys/class/dmi/id/board_name"),
        "version": _read("/sys/class/dmi/id/board_version"),
        "bios_vendor": _read("/sys/class/dmi/id/bios_vendor"),
        "bios_version": _read("/sys/class/dmi/id/bios_version"),
        "bios_date": _read("/sys/class/dmi/id/bios_date"),
    }
    total = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    rep["ram"] = _summarize_ram([], total, None)

    gpus = []
    if shutil.which("lspci"):
        for line in _run(["lspci"]).splitlines():
            if re.search(r"VGA|3D controller|Display controller", line):
                gpus.append({"name": _clean(line.split(":", 2)[-1]), "vendor": "", "vram_gb": 0,
                             "driver": "", "display": ""})
    rep["gpus"] = _mark_integrated(gpus)

    disks = []
    if shutil.which("lsblk"):
        try:
            data = json.loads(_run(["lsblk", "-J", "-b", "-o", "NAME,MODEL,ROTA,TRAN,SIZE,TYPE,MOUNTPOINT"]))
            for d in data.get("blockdevices", []):
                if d.get("type") != "disk":
                    continue
                tran = (d.get("tran") or "").upper()
                mounts = [c.get("mountpoint") for c in d.get("children", []) or [] if c.get("mountpoint")]
                disks.append({
                    "model": d.get("model") or d.get("name"),
                    "media": "HDD" if str(d.get("rota")) in ("1", "True", "true") else "SSD",
                    "bus": "NVMe" if d.get("name", "").startswith("nvme") else tran,
                    "size_gb": _gb(d.get("size")), "letters": mounts,
                    "free_gb": None, "volumes_gb": None, "health": "",
                    "is_system": "/" in mounts,
                })
        except Exception:
            pass
    rep["disks"] = disks
    return rep


# --------------------------------------------------------------------------- comuni
def _summarize_ram(modules: list[dict], total_gb: float, slots: int | None) -> dict:
    types = {m["type"] for m in modules if m.get("type")}
    rated = [m["rated_mhz"] for m in modules if m.get("rated_mhz")]
    conf = [m["configured_mhz"] for m in modules if m.get("configured_mhz")]
    n = len(modules)
    if n >= 2 and n % 2 == 0:
        channel = "Dual channel" if n in (2, 4) else f"{n} moduli"
    elif n == 1:
        channel = "Single channel"
    else:
        channel = "Sconosciuto" if n == 0 else f"{n} moduli (configurazione asimmetrica)"
    installed = round(sum(m["capacity_gb"] for m in modules), 1)
    return {
        "total_gb": installed or total_gb,
        "usable_gb": total_gb,
        "type": "/".join(sorted(types)) if types else "",
        "rated_mhz": min(rated) if rated else 0,          # MT/s dichiarati dai moduli
        "configured_mhz": min(conf) if conf else 0,        # MT/s effettivi
        "modules": modules,
        "modules_count": n,
        "slots_total": slots,
        "channel": channel,
        "mixed_kits": len({(m["capacity_gb"], m["part_number"]) for m in modules}) > 1,
    }


_IGPU_PAT = re.compile(r"uhd|iris|hd graphics|intel.*graphics$|radeon\(?tm\)? graphics|radeon graphics|"
                       r"vega \d+|radeon \d{3}m|arc graphics|microsoft", re.I)


def _mark_integrated(gpus: list[dict]) -> list[dict]:
    for g in gpus:
        g["is_integrated"] = bool(_IGPU_PAT.search(g["name"])) and not re.search(r"\barc [ab]\d{3}", g["name"], re.I)
    # GPU dedicata per prima
    gpus.sort(key=lambda g: (g["is_integrated"], -g.get("vram_gb", 0)))
    return gpus


def scan() -> dict:
    """Esegue la scansione completa e restituisce un dizionario serializzabile."""
    rep = _scan_windows() if IS_WINDOWS else _scan_linux()
    rep["cpu"].setdefault("name", "Sconosciuto")
    return rep


def live_stats() -> dict:
    """Statistiche in tempo reale (uso CPU, frequenza, RAM)."""
    f = psutil.cpu_freq()
    vm = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_mhz": int(f.current) if f else 0,
        "ram_used_gb": round(vm.used / 1024 ** 3, 1),
        "ram_percent": vm.percent,
    }


if __name__ == "__main__":
    print(json.dumps(scan(), indent=2, ensure_ascii=False))
