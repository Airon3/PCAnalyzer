"""
Test velocità connessione.

Motore predefinito: server Cloudflare (speed.cloudflare.com), nessuna libreria extra.
Motore alternativo: Ookla Speedtest tramite il pacchetto `speedtest-cli`, se installato.
"""
from __future__ import annotations

import statistics
import threading
import time
from typing import Callable

import requests

CF = "https://speed.cloudflare.com"
Progress = Callable[[str, float, float | None], None]   # (fase, avanzamento 0-1, valore live Mbps)


class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()


def _noop(*_a, **_k):
    pass


# --------------------------------------------------------------------------- Cloudflare
def _meta() -> dict:
    try:
        return requests.get(f"{CF}/meta", timeout=8).json()
    except Exception:
        return {}


def _latency(n: int = 12, progress: Progress = _noop) -> tuple[float, float]:
    s = requests.Session()
    samples = []
    for i in range(n):
        t0 = time.perf_counter()
        try:
            r = s.get(f"{CF}/__down?bytes=0", timeout=5)
            dt = (time.perf_counter() - t0) * 1000
            # sottrae il tempo di elaborazione lato server, se indicato
            st = r.headers.get("Server-Timing", "")
            if "dur=" in st:
                try:
                    dt -= float(st.split("dur=")[1].split(",")[0].split(";")[0])
                except ValueError:
                    pass
            if i > 0:  # il primo include handshake TLS
                samples.append(max(dt, 0.1))
        except requests.RequestException:
            pass
        progress("Latenza", (i + 1) / n, None)
    if not samples:
        return 0.0, 0.0
    jitter = statistics.mean(abs(a - b) for a, b in zip(samples, samples[1:])) if len(samples) > 1 else 0.0
    return round(statistics.median(samples), 1), round(jitter, 1)


def _transfer(kind: str, seconds: float, threads: int, progress: Progress, cancel: CancelToken) -> float:
    total = [0]
    lock = threading.Lock()
    stop = threading.Event()
    t_start = time.perf_counter()
    payload = b"0" * (4 * 1024 * 1024)

    def worker():
        s = requests.Session()
        while not stop.is_set():
            try:
                if kind == "down":
                    with s.get(f"{CF}/__down?bytes=50000000", stream=True, timeout=10) as r:
                        for chunk in r.iter_content(64 * 1024):
                            with lock:
                                total[0] += len(chunk)
                            if stop.is_set():
                                break
                else:
                    s.post(f"{CF}/__up", data=payload, timeout=15,
                           headers={"Content-Type": "application/octet-stream"})
                    with lock:
                        total[0] += len(payload)
            except requests.RequestException:
                time.sleep(0.2)

    ths = [threading.Thread(target=worker, daemon=True) for _ in range(threads)]
    for t in ths:
        t.start()

    # scarta il primo secondo (slow start TCP) dal calcolo finale
    warm_bytes, warm_t = 0, None
    label = "Download" if kind == "down" else "Upload"
    while True:
        el = time.perf_counter() - t_start
        if el >= seconds or cancel.cancelled:
            break
        time.sleep(0.25)
        with lock:
            b = total[0]
        if warm_t is None and el >= 1.0:
            warm_bytes, warm_t = b, el
        live = (b - warm_bytes) * 8 / max(el - (warm_t or 0), 0.01) / 1e6 if warm_t else b * 8 / max(el, .01) / 1e6
        progress(label, min(el / seconds, 1.0), round(live, 1))
    stop.set()
    el = time.perf_counter() - t_start
    with lock:
        b = total[0]
    if warm_t:
        return round((b - warm_bytes) * 8 / max(el - warm_t, 0.01) / 1e6, 1)
    return round(b * 8 / max(el, 0.01) / 1e6, 1)


def run_cloudflare(progress: Progress = _noop, cancel: CancelToken | None = None,
                   seconds: float = 10.0) -> dict:
    cancel = cancel or CancelToken()
    progress("Connessione al server", 0.0, None)
    meta = _meta()
    ping, jitter = _latency(progress=progress)
    down = _transfer("down", seconds, 6, progress, cancel) if not cancel.cancelled else 0
    up = _transfer("up", seconds, 4, progress, cancel) if not cancel.cancelled else 0
    if not cancel.cancelled and not meta and ping == 0 and down == 0:
        raise RuntimeError("Impossibile raggiungere speed.cloudflare.com: verifica la connessione o il firewall.")
    progress("Completato", 1.0, None)
    return {
        "engine": "Cloudflare",
        "ping_ms": ping, "jitter_ms": jitter, "download_mbps": down, "upload_mbps": up,
        "isp": meta.get("asOrganization", ""), "ip": meta.get("clientIp", ""),
        "server": f'{meta.get("colo", "")} {meta.get("city", "")}'.strip(),
        "country": meta.get("country", ""), "cancelled": cancel.cancelled,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# --------------------------------------------------------------------------- Ookla
def ookla_available() -> bool:
    try:
        import speedtest  # noqa: F401
        return True
    except ImportError:
        return False


def run_ookla(progress: Progress = _noop, cancel: CancelToken | None = None) -> dict:
    import speedtest  # type: ignore

    progress("Ricerca server migliore", 0.05, None)
    st = speedtest.Speedtest(secure=True)
    st.get_best_server()
    progress("Download", 0.3, None)
    st.download()
    progress("Upload", 0.65, None)
    st.upload(pre_allocate=False)
    r = st.results.dict()
    progress("Completato", 1.0, None)
    srv = r.get("server", {})
    cl = r.get("client", {})
    return {
        "engine": "Ookla Speedtest",
        "ping_ms": round(r.get("ping", 0), 1), "jitter_ms": None,
        "download_mbps": round(r.get("download", 0) / 1e6, 1),
        "upload_mbps": round(r.get("upload", 0) / 1e6, 1),
        "isp": cl.get("isp", ""), "ip": cl.get("ip", ""),
        "server": f'{srv.get("sponsor", "")} - {srv.get("name", "")}', "country": srv.get("country", ""),
        "cancelled": False, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def run(engine: str = "cloudflare", progress: Progress = _noop, cancel: CancelToken | None = None) -> dict:
    if engine == "ookla" and ookla_available():
        return run_ookla(progress, cancel)
    return run_cloudflare(progress, cancel)


def rate_connection(res: dict) -> dict:
    """Voto 1-5 della connessione e cosa permette di fare."""
    d, u, p = res.get("download_mbps", 0), res.get("upload_mbps", 0), res.get("ping_ms", 999) or 999
    score = 0.0
    score += 2.5 * min(1, d / 300) + 1.0 * min(1, u / 100)
    score += 1.5 if p <= 15 else (1.1 if p <= 30 else (0.6 if p <= 60 else 0.2))
    score = max(1.0, min(5.0, round(score * 2) / 2))
    uses = []
    if d >= 5:
        uses.append("Navigazione e streaming HD")
    if d >= 25:
        uses.append("Streaming 4K")
    if u >= 5 and p <= 60:
        uses.append("Videochiamate HD")
    if p <= 40:
        uses.append("Gaming online")
    if u >= 10:
        uses.append("Live streaming 1080p (Twitch/YouTube)")
    if d >= 300:
        uses.append("Download giochi veloci (100 GB in < 1 ora)")
    return {"rating": score, "uses": uses}
