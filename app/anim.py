"""
Piccolo motore di animazioni per Tkinter/CustomTkinter.

Tutto gira con `after()` sul thread dell'interfaccia (~60 fps). Ogni animazione ha
una chiave: se ne parte un'altra con la stessa chiave, quella vecchia si ferma.
"""
from __future__ import annotations

import math
import time
from typing import Callable

FRAME_MS = 16


# ------------------------------------------------------------------ easing
def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_cubic(t: float) -> float:
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t: float) -> float:
    c1, c3 = 1.4, 2.4
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


# ------------------------------------------------------------------ colori
def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lerp_color(a: str, b: str, t: float) -> str:
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * t), round(ga + (gb - ga) * t), round(ba + (bb - ba) * t))


# ------------------------------------------------------------------ motore
class Animator:
    def __init__(self, root):
        self.root = root
        self._jobs: dict[str, str] = {}
        self.enabled = True

    def cancel(self, key: str) -> None:
        job = self._jobs.pop(key, None)
        if job:
            try:
                self.root.after_cancel(job)
            except Exception:
                pass

    def tween(self, key: str, start: float, end: float, ms: int, step: Callable[[float], None],
              ease: Callable[[float], float] = ease_out_cubic, done: Callable[[], None] | None = None,
              delay: int = 0) -> None:
        """Porta un valore da start a end in `ms` millisecondi chiamando step(valore)."""
        self.cancel(key)
        if not self.enabled or ms <= 0:
            step(end)
            if done:
                done()
            return
        t0 = [None]

        def tick():
            now = time.perf_counter()
            if t0[0] is None:
                t0[0] = now
            p = min(1.0, (now - t0[0]) * 1000 / ms)
            try:
                step(start + (end - start) * ease(p))
            except Exception:  # widget distrutto durante l'animazione
                self._jobs.pop(key, None)
                return
            if p < 1:
                self._jobs[key] = self.root.after(FRAME_MS, tick)
            else:
                self._jobs.pop(key, None)
                if done:
                    done()

        self._jobs[key] = self.root.after(max(1, delay), tick)

    # --------------------------------------------------------------- scorciatoie
    def count(self, key: str, label, end: float, ms: int = 700, fmt: str = "{:.1f}", start: float = 0,
              delay: int = 0, suffix: str = "") -> None:
        """Numero che sale da start a end dentro una CTkLabel."""
        self.tween(key, start, end, ms, lambda v: label.configure(text=fmt.format(v) + suffix), delay=delay)

    def bar(self, key: str, bar, end: float, ms: int = 650, start: float = 0, delay: int = 0) -> None:
        self.tween(key, start, max(0.0, min(1.0, end)), ms, bar.set, delay=delay)

    def color(self, key: str, a: str, b: str, ms: int, apply: Callable[[str], None]) -> None:
        self.tween(key, 0, 1, ms, lambda t: apply(lerp_color(a, b, t)), ease=ease_in_out_cubic)

    def slide_in(self, key: str, widget, dx: int = 36, ms: int = 260) -> None:
        """La pagina entra scorrendo da destra (widget gestito con place)."""
        self.tween(key, dx, 0, ms, lambda x: widget.place_configure(x=int(round(x))), ease=ease_out_cubic)


class Spinner:
    """Arco arancione rotante disegnato su un Canvas."""

    def __init__(self, canvas, color: str, track: str, size: int = 56, width: int = 5):
        self.c, self.color, self.track, self.size, self.w = canvas, color, track, size, width
        self.angle = 0.0
        self.job = None
        pad = width
        self.track_id = canvas.create_oval(pad, pad, size - pad, size - pad, outline=track, width=width)
        self.arc_id = canvas.create_arc(pad, pad, size - pad, size - pad, start=0, extent=90, style="arc",
                                        outline=color, width=width)

    def start(self):
        t0 = time.perf_counter()

        def tick():
            el = time.perf_counter() - t0
            self.angle = (el * 300) % 360
            ext = 60 + 80 * (0.5 + 0.5 * math.sin(el * 3))   # l'arco "respira"
            try:
                self.c.itemconfigure(self.arc_id, start=-self.angle, extent=ext)
                self.job = self.c.after(FRAME_MS, tick)
            except Exception:
                self.job = None
        tick()

    def stop(self):
        if self.job:
            try:
                self.c.after_cancel(self.job)
            except Exception:
                pass
            self.job = None
