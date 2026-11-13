"""Interfaccia grafica (CustomTkinter) – tema Graphite Ember con animazioni."""
from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import (__version__, ai_advisor, balance, drivers, hardware, prices, report as report_mod, scoring,
               speedtest_engine, theme as T, updater)
from .anim import Animator, Spinner, lerp_color
from .paths import asset_path, load_json, load_settings, save_json, save_settings, user_dir, user_file

APP_TITLE = "PC Analyzer"


# =========================================================================== widget
class StarRating(tk.Canvas):
    """5 stelle con mezzi voti; set() ridisegna, così il valore si può animare."""

    def __init__(self, master, value: float = 0, size: int = 24, bg_color=T.SURF, **kw):
        self.size, self.value, self.bg_color = size, value, bg_color
        super().__init__(master, width=size * 5 + 8, height=size + 4, highlightthickness=0,
                         bg=T.pick(bg_color), **kw)
        self.draw()

    @staticmethod
    def _star(cx, cy, r_out, r_in):
        pts = []
        for i in range(10):
            ang = math.pi / 2 + i * math.pi / 5
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(ang), cy - r * math.sin(ang)))
        return pts

    @staticmethod
    def _clip_left(poly, xc):
        out = []
        for i, cur in enumerate(poly):
            prev = poly[i - 1]
            cin, pin = cur[0] <= xc, prev[0] <= xc
            if cin != pin:
                t = (xc - prev[0]) / (cur[0] - prev[0])
                out.append((xc, prev[1] + t * (cur[1] - prev[1])))
            if cin:
                out.append(cur)
        return out

    def draw(self):
        self.delete("all")
        self.configure(bg=T.pick(self.bg_color))
        s = self.size
        empty = T.pick(T.SURF3)
        for i in range(5):
            cx, cy = 4 + s * i + s / 2, s / 2 + 2
            poly = self._star(cx, cy, s * 0.46, s * 0.19)
            flat = [c for p in poly for c in p]
            self.create_polygon(flat, fill=empty, outline="")
            fill = max(0.0, min(1.0, self.value - i))
            if fill >= 0.995:
                self.create_polygon(flat, fill=T.ACCENT, outline="")
            elif fill > 0.01:
                # riempimento parziale durante l'animazione, mezza stella a fine corsa
                xc = cx - s * 0.46 + s * 0.92 * fill
                part = self._clip_left(poly, xc)
                if len(part) >= 3:
                    self.create_polygon([c for p in part for c in p], fill=T.ACCENT, outline="")

    def set(self, v: float):
        self.value = v
        self.draw()


# =========================================================================== app
class App(ctk.CTk):
    PAGES = [
        ("summary", "Riepilogo"), ("cpu", "Processore"), ("board", "Scheda madre"), ("ram", "Memoria"),
        ("gpu", "Scheda video"), ("storage", "Archiviazione"), ("drivers", "Driver"),
        ("balance", "Bilanciamento"), ("speed", "Speed test"), ("ai", "Assistente IA"), ("settings", "Impostazioni"),
    ]

    def __init__(self):
        self.settings = load_settings()
        ctk.set_appearance_mode(self.settings.get("appearance", "dark"))
        T.apply_ctk_theme()
        super().__init__()
        T.init_fonts(self)
        self.title(APP_TITLE)
        self.geometry("1240x810")
        self.minsize(1020, 660)
        self._set_icon()

        self.anim = Animator(self)
        self.anim.enabled = bool(self.settings.get("animations", True))
        self.report: dict | None = None
        self.ev: dict | None = None
        self.an: dict | None = None
        self.speed_result: dict | None = load_json(user_dir() / "last_speedtest.json")
        self.ai_history: list[dict] = []
        self.star_widgets: list[StarRating] = []
        self.live_label = None
        self.live_bar = None
        self.speed_cancel: speedtest_engine.CancelToken | None = None
        self.update_info: dict | None = None
        self._toast = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew", padx=(18, 18), pady=18)
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._page_anims: dict[str, list] = {}
        self._played: set[str] = set()
        self.current = "summary"
        self._loader = None
        self.after(120, self.start_scan)
        self.after(1000, self._live_loop)

    def _set_icon(self):
        try:
            if sys.platform.startswith("win"):
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCAnalyzer.App")
                self.iconbitmap(str(asset_path("icon.ico")))
                self.after(300, lambda: self.iconbitmap(str(asset_path("icon.ico"))))
            else:
                self._icon_img = tk.PhotoImage(file=str(asset_path("icon.png")))
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    # ================================================================== mattoncini UI
    def btn(self, master, text, command, kind="primary", **kw):
        if kind == "ghost":
            style = dict(fg_color=T.SURF2, hover_color=T.SURF3, text_color=T.TEXT, border_width=1,
                         border_color=T.BORDER)
        elif kind == "danger":
            style = dict(fg_color=T.BAD, hover_color=("#B8292E", "#D9454A"), text_color=("#FFFFFF", "#FFFFFF"))
        else:
            style = {}
        style.update(kw)
        style.setdefault("height", 36)
        style.setdefault("font", T.font(13, "bold"))
        return ctk.CTkButton(master, text=text, command=command, **style)

    def card(self, master, title: str | None = None, hover: bool = False, **kw) -> ctk.CTkFrame:
        f = ctk.CTkFrame(master, fg_color=T.SURF, corner_radius=12, border_width=1, border_color=T.BORDER, **kw)
        if title:
            ctk.CTkLabel(f, text=title.upper(), font=T.font(12, "bold"), text_color=T.MUTED, anchor="w").pack(
                fill="x", padx=18, pady=(14, 6))
        if hover:
            self._hoverable(f)
        return f

    def _hoverable(self, frame):
        """Bordo che si accende di arancione al passaggio del mouse (con dissolvenza)."""
        key = f"hover{id(frame)}"
        state = {"on": False}

        def inside():
            try:
                x, y = self.winfo_pointerxy()
                w = self.winfo_containing(x, y)
            except Exception:
                return False
            while w is not None:
                if w is frame:
                    return True
                w = getattr(w, "master", None)
            return False

        def fade(to_glow: bool):
            a, b = T.pick(T.BORDER), T.pick(T.ACCENT_GLOW)
            if not to_glow:
                a, b = b, a
            self.anim.color(key, a, b, 180, lambda c: frame.configure(border_color=c))

        def poll():
            # i figli della card "rubano" gli eventi Leave: controlliamo la posizione del mouse
            if not frame.winfo_exists():
                return
            if inside():
                frame.after(120, poll)
            else:
                state["on"] = False
                fade(False)
                frame.after(220, lambda: frame.winfo_exists() and not state["on"]
                            and frame.configure(border_color=T.BORDER))

        def enter(_e=None):
            if state["on"]:
                return
            state["on"] = True
            fade(True)
            frame.after(120, poll)

        frame.bind("<Enter>", enter, add="+")

    def kv_table(self, master, rows, key_width: int = 200):
        t = ctk.CTkFrame(master, fg_color="transparent")
        for i, (k, v) in enumerate(rows):
            ctk.CTkLabel(t, text=k, text_color=T.MUTED, anchor="w", width=key_width, font=T.font(13)).grid(
                row=i, column=0, sticky="w", padx=(0, 10), pady=3)
            ctk.CTkLabel(t, text=str(v) if v not in (None, "") else "—", anchor="w", justify="left",
                         wraplength=560, font=T.font(13)).grid(row=i, column=1, sticky="w", pady=3)
        t.pack(fill="x", padx=18, pady=(2, 16))
        return t

    def meter(self, page: str, master, label: str, value: float, maxv: float = 5, text: str | None = None,
              color=None, fmt: str = "{:.1f}"):
        row = ctk.CTkFrame(master, fg_color="transparent")
        ctk.CTkLabel(row, text=label, anchor="w", width=200, text_color=T.MUTED, font=T.font(13)).pack(side="left")
        bar = ctk.CTkProgressBar(row, height=8, corner_radius=4, progress_color=color or (T.ACCENT, T.ACCENT))
        bar.set(0)
        bar.pack(side="left", fill="x", expand=True, padx=10)
        val = ctk.CTkLabel(row, text=text or fmt.format(0), width=60, anchor="e", font=T.font(16, kind="num"))
        val.pack(side="left")
        row.pack(fill="x", padx=18, pady=4)
        frac = max(0.0, min(1.0, value / maxv))
        self._reg(page, lambda d: self.anim.bar(f"m{id(bar)}", bar, frac, 700, delay=d))
        if text is None:
            self._reg(page, lambda d: self.anim.count(f"mv{id(val)}", val, value, 700, fmt, delay=d), step=0)
        else:
            val.configure(text=text)
        return row

    def page_title(self, master, eyebrow: str, title: str, subtitle: str = ""):
        ctk.CTkLabel(master, text=eyebrow.upper(), font=T.font(12, "bold"), text_color=T.ACCENT_TEXT,
                     anchor="w").pack(fill="x", padx=6, pady=(4, 0))
        ctk.CTkLabel(master, text=title, font=T.font(28, "bold"), anchor="w").pack(fill="x", padx=6)
        if subtitle:
            ctk.CTkLabel(master, text=subtitle, text_color=T.MUTED, anchor="w", justify="left", wraplength=900,
                         font=T.font(13)).pack(fill="x", padx=6, pady=(2, 12))
        else:
            ctk.CTkFrame(master, height=10, fg_color="transparent").pack()

    def chip(self, master, text, color=T.SURF3, text_color=T.TEXT):
        return ctk.CTkLabel(master, text=f"  {text}  ", fg_color=color, corner_radius=6, text_color=text_color,
                            font=T.font(11, "bold"), height=22)

    def _stars(self, master, value, size=24, bg=T.SURF, page: str | None = None, delay: int = 0):
        s = StarRating(master, 0 if (page and self.anim.enabled) else value, size=size, bg_color=bg)
        self.star_widgets.append(s)
        if page:
            self._reg(page, lambda d: self.anim.tween(f"st{id(s)}", 0, value, 900, s.set, delay=d + delay), step=0)
        return s

    def _reg(self, page: str, fn, step: int = 1):
        """Registra un'animazione da eseguire quando la pagina viene mostrata (con piccolo sfalsamento)."""
        lst = self._page_anims.setdefault(page, [])
        lst.append((fn, step))

    # ================================================================== sidebar
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=228, corner_radius=0, fg_color=T.SIDE, border_width=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        self.sidebar = sb
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(22, 18))
        try:
            from PIL import Image
            img = ctk.CTkImage(Image.open(asset_path("icon.png")), size=(34, 34))
            ctk.CTkLabel(head, image=img, text="").pack(side="left")
        except Exception:
            pass
        txt = ctk.CTkFrame(head, fg_color="transparent")
        txt.pack(side="left", padx=10)
        ctk.CTkLabel(txt, text="PC Analyzer", font=T.font(17, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(txt, text="hardware · rating · upgrade", font=T.font(11), text_color=T.MUTED,
                     anchor="w").pack(fill="x")

        self.nav_frame = ctk.CTkFrame(sb, fg_color="transparent")
        self.nav_frame.pack(fill="x", padx=12)
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in self.PAGES:
            b = ctk.CTkButton(self.nav_frame, text=label, anchor="w", height=38, corner_radius=8,
                              fg_color=T.SIDE, hover=False, text_color=T.MUTED, font=T.font(13),
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", pady=1)
            b.bind("<Enter>", lambda e, k=key: self._nav_hover(k, True), add="+")
            b.bind("<Leave>", lambda e, k=key: self._nav_hover(k, False), add="+")
            self.nav_buttons[key] = b
        self.nav_ind = ctk.CTkFrame(self.nav_frame, width=3, height=18, corner_radius=2, fg_color=T.ACCENT)
        self._ind_y = None

        ctk.CTkFrame(sb, fg_color="transparent").pack(fill="both", expand=True)
        self.btn(sb, "Nuova scansione", self.start_scan).pack(fill="x", padx=16, pady=(0, 8))
        self.btn(sb, "Esporta report", self.export_report, kind="ghost").pack(fill="x", padx=16, pady=(0, 10))
        self.version_lbl = ctk.CTkLabel(sb, text=f"v{__version__}", font=T.font(11), text_color=T.MUTED)
        self.version_lbl.pack(pady=(0, 14))

    def _nav_hover(self, key: str, enter: bool):
        if key == self.current:
            return
        b = self.nav_buttons[key]
        a, c = T.pick(T.SIDE), T.pick(T.SURF2)
        if not enter:
            a, c = c, a
        self.anim.color(f"nav{key}", a, c, 140, lambda col: b.configure(fg_color=col))
        b.configure(text_color=T.TEXT if enter else T.MUTED)

    def _move_indicator(self, key: str):
        b = self.nav_buttons[key]
        self.update_idletasks()
        y = b.winfo_y() + (b.winfo_height() - 18) // 2
        if self._ind_y is None:
            self.nav_ind.place(x=2, y=y)
            self._ind_y = y
            return
        y0 = self._ind_y
        self._ind_y = y
        self.anim.tween("ind", y0, y, 260, lambda v: self.nav_ind.place_configure(y=int(v)))
        self.nav_ind.lift()

    def _style_nav(self, key: str):
        for k, b in self.nav_buttons.items():
            self.anim.cancel(f"nav{k}")
            if k == key:
                b.configure(fg_color=T.SURF2, text_color=T.TEXT, font=T.font(13, "bold"))
            else:
                b.configure(fg_color=T.SIDE, text_color=T.MUTED, font=T.font(13))
        self.nav_ind.lift()

    # ================================================================== navigazione
    def show(self, key: str, animate: bool = True):
        if not self.report:
            return
        if key not in self.pages:
            self._build_page(key)
        new = self.pages[key]
        old = self.pages.get(self.current) if self.current != key else None
        self.current = key
        self._style_nav(key)
        self._move_indicator(key)
        if old is None or not animate or not self.anim.enabled:
            for k, p in self.pages.items():
                if p is not new:
                    p.place_forget()
            new.place(x=0, y=0, relwidth=1, relheight=1)
            new.lift()
        else:
            new.place(x=40, y=0, relwidth=1, relheight=1)
            new.lift()

            def finish():
                new.place(x=0, y=0, relwidth=1, relheight=1)
                if old.winfo_exists() and old is not self.pages.get(self.current):
                    old.place_forget()
            self.anim.tween("page", 40, 0, 240, lambda x: new.place_configure(x=int(x)), done=finish)
        if key not in self._played:
            self._played.add(key)
            d = 60
            for fn, step in self._page_anims.get(key, []):
                fn(d)
                d += 45 * step

    def _build_page(self, key: str):
        holder = ctk.CTkFrame(self.content, fg_color="transparent")
        p = ctk.CTkScrollableFrame(holder, fg_color="transparent", scrollbar_button_color=T.SURF3)
        p.pack(fill="both", expand=True)
        builders = {
            "summary": self._page_summary, "cpu": self._page_cpu, "board": self._page_board,
            "ram": self._page_ram, "gpu": self._page_gpu, "storage": self._page_storage,
            "drivers": self._page_drivers, "balance": self._page_balance, "speed": self._page_speed,
            "ai": self._page_ai, "settings": self._page_settings,
        }
        self._page_anims[key] = []
        try:
            builders[key](p)
        except Exception as e:  # una pagina con un errore non deve bloccare le altre
            ctk.CTkLabel(p, text=f"Errore nella pagina: {e}", text_color=T.BAD).pack(pady=20)
        self.pages[key] = holder

    def invalidate_pages(self, keep_current: bool = True):
        cur = self.current
        for p in self.pages.values():
            p.destroy()
        self.pages, self._page_anims, self.star_widgets = {}, {}, []
        self._played = set()
        self.live_label = self.live_bar = None
        if keep_current and self.report:
            self.show(cur, animate=False)

    # ================================================================== scansione
    def _show_loader(self):
        for p in self.pages.values():
            p.destroy()
        self.pages, self._page_anims, self._played, self.star_widgets = {}, {}, set(), []
        if self._loader:
            self._loader.destroy()
        f = ctk.CTkFrame(self.content, fg_color="transparent")
        f.place(relx=0.5, rely=0.45, anchor="center")
        self._loader = f
        cv = tk.Canvas(f, width=64, height=64, highlightthickness=0, bg=T.pick(T.BG))
        cv.pack(pady=(0, 18))
        self._spinner = Spinner(cv, T.ACCENT, T.pick(T.SURF3), size=64, width=5)
        self._spinner.start()
        ctk.CTkLabel(f, text="Analisi dell'hardware", font=T.font(22, "bold")).pack()
        self._phase_lbl = ctk.CTkLabel(f, text="Avvio…", text_color=T.MUTED, font=T.font(13))
        self._phase_lbl.pack(pady=(4, 14))
        self._phase_bar = ctk.CTkProgressBar(f, width=360, height=6, corner_radius=3)
        self._phase_bar.set(0)
        self._phase_bar.pack()
        self._phase_val = 0.0

    def _phase(self, text: str, frac: float):
        def ui():
            if not self._loader:
                return
            self._phase_lbl.configure(text=text)
            self.anim.bar("phase", self._phase_bar, frac, 500, start=self._phase_val)
            self._phase_val = frac
        self.after(0, ui)

    def start_scan(self):
        self.report = None
        self._show_loader()

        def work():
            try:
                self._phase("Lettura di CPU, scheda madre, memoria, GPU e dischi…", 0.55)
                rep = hardware.scan()
                self._phase("Calcolo dei voti…", 0.75)
                ev = scoring.evaluate(rep)
                self._phase("Analisi del bilanciamento e degli upgrade…", 0.92)
                an = balance.analyze(rep, ev)
                self._phase("Fatto", 1.0)
                self.after(450, lambda: self._scan_done(rep, ev, an))
            except Exception as e:  # pragma: no cover
                err = str(e)
                self.after(0, lambda: self._scan_error(err))

        threading.Thread(target=work, daemon=True).start()

    def _scan_error(self, err: str):
        if self._loader:
            self._phase_lbl.configure(text=f"Errore durante la scansione: {err}", text_color=T.BAD)
            self.btn(self._loader, "Riprova", self.start_scan).pack(pady=14)

    def _scan_done(self, rep, ev, an):
        self.report, self.ev, self.an = rep, ev, an
        if self._loader:
            self._spinner.stop()
            self._loader.destroy()
            self._loader = None
        self.show(self.current if self.current else "summary", animate=False)
        if not getattr(self, "_update_checked", False):
            self._update_checked = True
            self.after(2500, self._auto_check_update)

    def refresh_analysis(self):
        if not self.report:
            return
        self.an = balance.analyze(self.report, self.ev)
        self.invalidate_pages()

    # ================================================================== toast
    def toast(self, text: str, kind: str = "ok", action: tuple[str, callable] | None = None, ms: int = 3200):
        if self._toast is not None:
            try:
                self._toast.destroy()
            except Exception:
                pass
        col = {"ok": T.OK, "err": T.BAD, "info": (T.ACCENT, T.ACCENT)}.get(kind, T.OK)
        t = ctk.CTkFrame(self, fg_color=T.SURF2, corner_radius=10, border_width=1, border_color=T.BORDER)
        ctk.CTkFrame(t, width=4, height=30, corner_radius=2, fg_color=col).pack(side="left", padx=(12, 10), pady=12)
        ctk.CTkLabel(t, text=text, font=T.font(13), wraplength=340, justify="left").pack(side="left", pady=10)
        if action:
            label, fn = action
            self.btn(t, label, lambda: (fn(), hide()), height=30, width=90).pack(side="left", padx=(12, 4))
        ctk.CTkButton(t, text="✕", width=28, height=28, fg_color="transparent", hover_color=T.SURF3,
                      text_color=T.MUTED, command=lambda: hide()).pack(side="left", padx=(4, 8))
        self._toast = t
        t.place(relx=1.0, rely=1.0, anchor="se", x=420, y=-22)
        self.anim.tween("toast", 420, -22, 320, lambda x: t.place_configure(x=int(x)))

        def hide():
            if not t.winfo_exists():
                return
            self.anim.tween("toast", -22, 440, 260, lambda x: t.place_configure(x=int(x)),
                            done=lambda: t.winfo_exists() and t.destroy())
        if ms:
            self.after(ms, hide)

    # ================================================================== pagine
    def _page_summary(self, p):
        rep, ev, an = self.report, self.ev, self.an
        sysi = rep.get("system", {})
        self.page_title(p, "Panoramica", "Riepilogo build",
                        f"{sysi.get('manufacturer', '')} {sysi.get('model', '')} · "
                        f"{'Portatile' if ev['is_laptop'] else 'Desktop'} · {rep.get('os', {}).get('name', '')}")
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="x", pady=2)
        items = [("overall", "Complessivo"), ("gaming", "Gaming"), ("office", "Ufficio"),
                 ("productivity", "Produttività")]
        for i, (k, name) in enumerate(items):
            grid.grid_columnconfigure(i, weight=1, uniform="r")
            c = self.card(grid, hover=True)
            c.grid(row=0, column=i, sticky="nsew", padx=6, pady=6)
            r = ev["ratings"][k]
            ctk.CTkLabel(c, text=name.upper(), font=T.font(12, "bold"), text_color=T.MUTED,
                         anchor="w").pack(fill="x", padx=18, pady=(16, 0))
            num_row = ctk.CTkFrame(c, fg_color="transparent")
            num_row.pack(fill="x", padx=18)
            num = ctk.CTkLabel(num_row, text="0.0" if self.anim.enabled else f"{r:.1f}",
                               font=T.font(46, kind="num"), anchor="w")
            num.pack(side="left")
            ctk.CTkLabel(num_row, text=" /5", font=T.font(18, kind="num"), text_color=T.MUTED).pack(
                side="left", anchor="s", pady=(0, 10))
            self._reg("summary", lambda d, n=num, v=r: self.anim.count(f"r{id(n)}", n, v, 900, delay=d), step=0)
            st = self._stars(c, r, page="summary")
            st.pack(anchor="w", padx=16, pady=(0, 8))
            self._reg("summary", lambda d: None)   # sfalsamento tra le card
            lab = ev["labels"].get(k, "Media dei tre utilizzi" if k == "overall" else "")
            ctk.CTkLabel(c, text=lab, text_color=T.MUTED, wraplength=210, justify="left", anchor="w",
                         font=T.font(12)).pack(fill="x", padx=18, pady=(0, 16))

        # bilanciamento
        b = self.card(p, hover=True)
        b.pack(fill="x", padx=6, pady=8)
        row = ctk.CTkFrame(b, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(16, 8))
        sc = an["balance_score"]
        col = T.OK if sc >= 80 else (T.WARN if sc >= 60 else T.BAD)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left")
        ctk.CTkLabel(left, text="BILANCIAMENTO", font=T.font(12, "bold"), text_color=T.MUTED, anchor="w").pack(fill="x")
        nr = ctk.CTkFrame(left, fg_color="transparent")
        nr.pack(fill="x")
        scl = ctk.CTkLabel(nr, text="0", font=T.font(36, kind="num"), text_color=col)
        scl.pack(side="left")
        ctk.CTkLabel(nr, text=f" /100   {an['verdict']}", font=T.font(15, "bold")).pack(side="left", anchor="s",
                                                                                      pady=(0, 6))
        self._reg("summary", lambda d: self.anim.count("bal", scl, sc, 900, "{:.0f}", delay=d), step=0)
        self.btn(row, "Dettagli e upgrade  →", lambda: self.show("balance"), kind="ghost", width=200).pack(side="right")
        pb = ctk.CTkProgressBar(b, height=8, corner_radius=4, progress_color=col)
        pb.set(0)
        pb.pack(fill="x", padx=18, pady=(4, 10))
        self._reg("summary", lambda d: self.anim.bar("balbar", pb, sc / 100, 900, delay=d))
        top = [i for i in an["issues"] if i["severity"] in ("alta", "media")][:3]
        for i in top:
            ctk.CTkLabel(b, text=f"●  {i['title']}", text_color=T.SEVERITY[i["severity"]], anchor="w",
                         font=T.font(13)).pack(fill="x", padx=18)
        ctk.CTkFrame(b, height=12, fg_color="transparent").pack()

        # componenti
        c = self.card(p, "Componenti")
        c.pack(fill="x", padx=6, pady=8)
        cpu, ram = rep.get("cpu", {}), rep.get("ram", {})
        gpu = (rep.get("gpus") or [{}])[0]
        sysd = ev["storage"].get("system_disk") or {}
        mb = rep.get("motherboard", {})
        self.kv_table(c, [
            ("Processore", f"{cpu.get('name')}  ({cpu.get('cores')}C / {cpu.get('threads')}T)"),
            ("Scheda madre", f"{mb.get('manufacturer', '')} {mb.get('model', '')}"),
            ("Memoria", f"{ram.get('total_gb')} GB {ram.get('type', '')} @ {ram.get('configured_mhz') or '?'} MT/s "
                        f"· {ram.get('channel', '')}"),
            ("Scheda video", f"{gpu.get('name', 'Nessuna')}  ({gpu.get('vram_gb', 0)} GB)"),
            ("Disco di sistema", f"{sysd.get('model', '—')}  · {ev['storage']['system_type']} · "
                                 f"{sysd.get('size_gb', '?')} GB"),
        ])
        cr = ev["component_ratings"]
        c2 = self.card(p, "Punteggio per componente (0-5)")
        c2.pack(fill="x", padx=6, pady=8)
        for lab, v in (("CPU · gaming", cr["cpu_gaming"]), ("CPU · multi-thread", cr["cpu_prod"]),
                       ("GPU · gaming", cr["gpu_gaming"]), ("RAM", cr["ram_gaming"]), ("Archiviazione", cr["storage"])):
            self.meter("summary", c2, lab, v)
        ctk.CTkFrame(c2, height=12, fg_color="transparent").pack()

    def _page_cpu(self, p):
        cpu, ev = self.report.get("cpu", {}), self.ev
        cp, plat = ev["cpu_perf"], ev["platform"]
        self.page_title(p, "Componenti", "Processore", cpu.get("name", ""))
        c = self.card(p, "Specifiche")
        c.pack(fill="x", padx=6, pady=6)
        self.kv_table(c, [
            ("Nome", cpu.get("name")), ("Produttore", cpu.get("vendor")),
            ("Core / Thread", f"{cpu.get('cores')} / {cpu.get('threads')}"),
            ("Frequenza base", f"{cpu.get('base_clock_mhz')} MHz" if cpu.get("base_clock_mhz") else ""),
            ("Cache L2 / L3", f"{cpu.get('l2_kb') or '—'} KB / {cpu.get('l3_kb') or '—'} KB"),
            ("Socket (rilevato)", cpu.get("socket_reported")),
            ("Piattaforma", f"{plat['socket']} · memoria {plat['mem'] or '—'}"),
            ("Anno di uscita", cp.get("year") or "—"), ("TDP", f"{cp['tdp']} W" if cp.get("tdp") else "—"),
        ])
        live = self.card(p, "Monitor in tempo reale")
        live.pack(fill="x", padx=6, pady=6)
        self.live_label = ctk.CTkLabel(live, text="…", anchor="w", font=T.font(14, kind="num"))
        self.live_label.pack(fill="x", padx=18, pady=(0, 6))
        self.live_bar = ctk.CTkProgressBar(live, height=8, corner_radius=4)
        self.live_bar.set(0)
        self.live_bar.pack(fill="x", padx=18, pady=(0, 16))
        self._live_val = 0.0

        perf = self.card(p, "Indici prestazionali (100 = CPU desktop top di gamma)")
        perf.pack(fill="x", padx=6, pady=6)
        self.meter("cpu", perf, "Single-thread", cp["st"], 100, fmt="{:.0f}")
        self.meter("cpu", perf, "Multi-thread", cp["mt"], 100, fmt="{:.0f}")
        self.meter("cpu", perf, "Gaming", cp["gaming"], 100, fmt="{:.0f}")
        note = ("✓ Modello riconosciuto nel database." if not cp["estimated"]
                else "⚠ Modello non presente nel database: valori stimati da generazione, core e thread.")
        ctk.CTkLabel(perf, text=note, text_color=T.MUTED, anchor="w", font=T.font(12)).pack(fill="x", padx=18,
                                                                                           pady=(6, 6))
        self._era_box(perf, ev["era"]["cpu"])

    def _era_box(self, master, era: dict):
        yr = self.ev["era"]["year"]
        if not era.get("notes"):
            ctk.CTkLabel(master, text=f"✓ Al passo con gli standard del {yr}.", text_color=T.OK,
                         anchor="w", font=T.font(13)).pack(fill="x", padx=18, pady=(0, 16))
            return
        ctk.CTkLabel(master, text=f"Rispetto agli standard del {yr}  ·  penalità voto -{era.get('penalty', 0):.2f}",
                     anchor="w", font=T.font(13, "bold"), text_color=T.WARN).pack(fill="x", padx=18)
        for n in era["notes"]:
            ctk.CTkLabel(master, text=f"  •  {n}", anchor="w", justify="left", wraplength=820,
                         text_color=T.MUTED, font=T.font(13)).pack(fill="x", padx=18)
        ctk.CTkFrame(master, height=14, fg_color="transparent").pack()

    def _page_board(self, p):
        mb, s = self.report.get("motherboard", {}), self.report.get("system", {})
        self.page_title(p, "Componenti", "Scheda madre e BIOS", f"{mb.get('manufacturer', '')} {mb.get('model', '')}")
        c = self.card(p, "Scheda madre")
        c.pack(fill="x", padx=6, pady=6)
        self.kv_table(c, [("Produttore", mb.get("manufacturer")), ("Modello", mb.get("model")),
                          ("Revisione", mb.get("version")), ("Socket CPU", self.ev["platform"]["socket"])])
        c = self.card(p, "BIOS / UEFI")
        c.pack(fill="x", padx=6, pady=6)
        self.kv_table(c, [("Produttore", mb.get("bios_vendor")), ("Versione", mb.get("bios_version")),
                          ("Data", mb.get("bios_date"))])
        c = self.card(p, "Sistema")
        c.pack(fill="x", padx=6, pady=6)
        o = self.report.get("os", {})
        self.kv_table(c, [("Produttore sistema", s.get("manufacturer")), ("Modello sistema", s.get("model")),
                          ("Tipo", "Portatile" if self.ev["is_laptop"] else "Desktop"),
                          ("Sistema operativo", o.get("name")),
                          ("Versione / Build", f"{o.get('version')} / {o.get('build')}"), ("Architettura", o.get("arch"))])
        self.btn(p, "Driver e BIOS per questa scheda  →", lambda: self.show("drivers"), kind="ghost").pack(
            anchor="e", padx=8, pady=6)

    def _page_ram(self, p):
        ram = self.report.get("ram", {})
        self.page_title(p, "Componenti", "Memoria", f"{ram.get('total_gb')} GB {ram.get('type', '')}")
        c = self.card(p, "Riepilogo")
        c.pack(fill="x", padx=6, pady=6)
        self.kv_table(c, [
            ("Capacità totale", f"{ram.get('total_gb')} GB"), ("Utilizzabile", f"{ram.get('usable_gb')} GB"),
            ("Tipo", ram.get("type")), ("Frequenza effettiva", f"{ram.get('configured_mhz') or '—'} MT/s"),
            ("Frequenza dichiarata (SPD)", f"{ram.get('rated_mhz') or '—'} MT/s"),
            ("Configurazione", ram.get("channel")),
            ("Slot occupati", f"{ram.get('modules_count')} / {ram.get('slots_total') or '?'}"),
        ])
        for m in ram.get("modules", []):
            c = self.card(p, f"Slot {m.get('slot')}", hover=True)
            c.pack(fill="x", padx=6, pady=6)
            self.kv_table(c, [("Capacità", f"{m.get('capacity_gb')} GB"), ("Produttore", m.get("manufacturer")),
                              ("Part number", m.get("part_number")), ("Tipo", m.get("type")),
                              ("Velocità", f"{m.get('configured_mhz')} / {m.get('rated_mhz')} MT/s (effettiva / SPD)")])
        if not ram.get("modules"):
            ctk.CTkLabel(p, text="Dettaglio moduli non disponibile su questo sistema.", text_color=T.MUTED).pack(pady=8)

    def _page_gpu(self, p):
        gpus = self.report.get("gpus", [])
        self.page_title(p, "Componenti", "Scheda video", f"{len(gpus)} adattatori rilevati")
        gp = self.ev["gpu_perf"]
        for i, g in enumerate(gpus):
            c = self.card(p, g.get("name", "") + ("  ·  integrata" if g.get("is_integrated") else ""), hover=True)
            c.pack(fill="x", padx=6, pady=6)
            self.kv_table(c, [("Produttore", g.get("vendor")), ("Memoria video", f"{g.get('vram_gb')} GB"),
                              ("Tipo", "Integrata" if g.get("is_integrated") else "Dedicata"),
                              ("Driver installato", g.get("driver")), ("Display", g.get("display"))])
            if i == 0:
                self.meter("gpu", c, "Indice gaming (5090 = 100)", gp["idx"], 100, fmt="{:.0f}")
                note = "✓ Modello riconosciuto." if not gp["estimated"] else "⚠ Modello non nel database: stima da VRAM."
                if gp.get("laptop"):
                    note += " Versione mobile: prestazioni ridotte rispetto alla desktop."
                ctk.CTkLabel(c, text=note, text_color=T.MUTED, anchor="w", font=T.font(12)).pack(fill="x", padx=18,
                                                                                                pady=(6, 6))
                self._era_box(c, self.ev["era"]["gpu"])
        self.btn(p, "Driver per la scheda video  →", lambda: self.show("drivers"), kind="ghost").pack(
            anchor="e", padx=8, pady=6)

    def _page_storage(self, p):
        disks = self.report.get("disks", [])
        st = self.ev["storage"]
        self.page_title(p, "Componenti", "Archiviazione",
                        f"{len(disks)} dischi · SSD totale {st['ssd_total_gb']:.0f} GB · HDD totale {st['hdd_total_gb']:.0f} GB")
        for d in disks:
            c = self.card(p, f"{d.get('model')}" + ("   ·   disco di sistema" if d.get("is_system") else ""), hover=True)
            c.pack(fill="x", padx=6, pady=6)
            tags = ctk.CTkFrame(c, fg_color="transparent")
            tags.pack(fill="x", padx=18, pady=(0, 6))
            for t in filter(None, [d.get("media"), d.get("bus")]):
                self.chip(tags, t, color=(T.ACCENT_DEEP, T.ACCENT_DEEP) if t.upper() == "NVME" else T.SURF3,
                          text_color=("#FFFFFF", "#FFFFFF") if t.upper() == "NVME" else T.TEXT).pack(side="left",
                                                                                                     padx=(0, 6))
            self.kv_table(c, [("Capacità", f"{d.get('size_gb')} GB"),
                              ("Unità", ", ".join(d.get("letters") or []) or "—"), ("Stato", d.get("health"))])
            if d.get("volumes_gb"):
                used = d["volumes_gb"] - (d.get("free_gb") or 0)
                frac = used / d["volumes_gb"]
                row = ctk.CTkFrame(c, fg_color="transparent")
                row.pack(fill="x", padx=18, pady=(0, 16))
                colr = T.BAD if frac > 0.9 else (T.WARN if frac > 0.75 else (T.ACCENT, T.ACCENT))
                bar = ctk.CTkProgressBar(row, height=8, corner_radius=4, progress_color=colr)
                bar.set(0)
                bar.pack(side="left", fill="x", expand=True)
                self._reg("storage", lambda dl, b=bar, f=frac: self.anim.bar(f"d{id(b)}", b, f, 800, delay=dl))
                ctk.CTkLabel(row, text=f"  {used:.0f} / {d['volumes_gb']:.0f} GB usati", width=190,
                             font=T.font(13, kind="num")).pack(side="left")

    # ------------------------------------------------------------------ driver
    def _page_drivers(self, p):
        self.page_title(p, "Supporto", "Driver e BIOS",
                        "Link ai siti ufficiali dei produttori, scelti in base ai componenti rilevati. "
                        "Prima di aggiornare il BIOS crea un punto di ripristino e non spegnere il PC durante l'operazione.")
        sections = drivers.driver_sections(self.report, self.ev["is_laptop"])
        for s in sections:
            c = self.card(p, hover=True)
            c.pack(fill="x", padx=6, pady=7)
            head = ctk.CTkFrame(c, fg_color="transparent")
            head.pack(fill="x", padx=18, pady=(16, 4))
            ctk.CTkLabel(head, text=s["component"].upper(), font=T.font(12, "bold"), text_color=T.MUTED).pack(side="left")
            if s.get("vendor"):
                self.chip(head, s["vendor"], color=(T.ACCENT_DEEP, T.ACCENT_DEEP),
                          text_color=("#FFFFFF", "#FFFFFF")).pack(side="left", padx=10)
            ctk.CTkLabel(c, text=s.get("device") or "—", font=T.font(17, "bold"), anchor="w").pack(fill="x", padx=18)
            info = []
            if s.get("installed"):
                info.append(f"Driver installato: {s['installed']}")
            bios = s.get("bios")
            if bios and bios.get("version"):
                info.append(f"BIOS installato: {bios['version']} ({bios.get('date') or 'data sconosciuta'})")
            if info:
                ctk.CTkLabel(c, text="   ·   ".join(info), text_color=T.MUTED, anchor="w", font=T.font(12)).pack(
                    fill="x", padx=18, pady=(2, 0))
            if bios and bios.get("advice"):
                ctk.CTkLabel(c, text="⚠ " + bios["advice"], text_color=T.WARN, anchor="w", justify="left",
                             wraplength=840, font=T.font(12)).pack(fill="x", padx=18, pady=(6, 0))
            ctk.CTkFrame(c, height=8, fg_color="transparent").pack()
            for it in s.get("items", []):
                r = ctk.CTkFrame(c, fg_color=T.SURF2, corner_radius=10)
                r.pack(fill="x", padx=14, pady=3)
                txt = ctk.CTkFrame(r, fg_color="transparent")
                txt.pack(side="left", fill="x", expand=True, padx=14, pady=10)
                ctk.CTkLabel(txt, text=it["title"], font=T.font(14, "bold"), anchor="w").pack(fill="x")
                ctk.CTkLabel(txt, text=it.get("desc", ""), text_color=T.MUTED, anchor="w", justify="left",
                             wraplength=640, font=T.font(12)).pack(fill="x")
                kind = "primary" if it.get("kind") in ("driver", "bios") else "ghost"
                self.btn(r, "Apri  ↗", lambda u=it["url"]: webbrowser.open(u), kind=kind, width=96).pack(
                    side="right", padx=12)
            if not s.get("items"):
                ctk.CTkLabel(c, text="Nessun link disponibile per questo componente.", text_color=T.MUTED,
                             anchor="w").pack(fill="x", padx=18)
            if s.get("note"):
                ctk.CTkLabel(c, text="ℹ  " + s["note"], text_color=T.MUTED, anchor="w", justify="left",
                             wraplength=840, font=T.font(12)).pack(fill="x", padx=18, pady=(8, 0))
            ctk.CTkFrame(c, height=14, fg_color="transparent").pack()
        w = self.card(p, "Altri aggiornamenti")
        w.pack(fill="x", padx=6, pady=7)
        ctk.CTkLabel(w, text="Windows Update installa automaticamente molti driver di base (audio, rete, USB). "
                             "Controlla anche Impostazioni › Windows Update › Opzioni avanzate › Aggiornamenti "
                             "facoltativi.", text_color=T.MUTED, anchor="w", justify="left", wraplength=860,
                     font=T.font(13)).pack(fill="x", padx=18)
        self.btn(w, "Apri Windows Update", lambda: self._open_uri("ms-settings:windowsupdate"), kind="ghost",
                 width=200).pack(anchor="w", padx=18, pady=(10, 16))

    # ------------------------------------------------------------------ bilanciamento
    def _page_balance(self, p):
        an = self.an
        self.page_title(p, "Analisi", "Bilanciamento e upgrade",
                        f"Prezzi aggiornati al {an.get('prices_updated')} · fonte: {an.get('prices_source')}"
                        + ("   ·   ⚠ listino vecchio di oltre 30 giorni: aggiornalo"
                           if an.get("prices_age_days", 0) > 30 else ""))
        top = self.card(p)
        top.pack(fill="x", padx=6, pady=6)
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=16)
        sc = an["balance_score"]
        col = T.OK if sc >= 80 else (T.WARN if sc >= 60 else T.BAD)
        scl = ctk.CTkLabel(row, text="0", font=T.font(52, kind="num"), text_color=col)
        scl.pack(side="left")
        self._reg("balance", lambda d: self.anim.count("bal2", scl, sc, 900, "{:.0f}", delay=d))
        ctk.CTkLabel(row, text=f"/100\n{an['verdict']}", justify="left", font=T.font(15, "bold")).pack(
            side="left", padx=12)
        btns = ctk.CTkFrame(row, fg_color="transparent")
        btns.pack(side="right")
        self.btn(btns, "Aggiorna prezzi", self.update_prices_dialog, width=170).pack(pady=3)
        self.btn(btns, "Analisi con IA", lambda: self.show("ai"), kind="ghost", width=170).pack(pady=3)

        if an["issues"]:
            c = self.card(p, "Problemi rilevati")
            c.pack(fill="x", padx=6, pady=6)
            for i in an["issues"]:
                f = ctk.CTkFrame(c, fg_color=T.SURF2, corner_radius=10)
                f.pack(fill="x", padx=14, pady=4)
                h = ctk.CTkFrame(f, fg_color="transparent")
                h.pack(fill="x", padx=14, pady=(10, 0))
                self.chip(h, i["severity"].upper(), color=T.SEVERITY[i["severity"]],
                          text_color=("#FFFFFF", "#0E0F11")).pack(side="left")
                ctk.CTkLabel(h, text=f"  {i['component']}  ·  {i['title']}", font=T.font(14, "bold"),
                             anchor="w").pack(side="left")
                ctk.CTkLabel(f, text=i["detail"], anchor="w", justify="left", wraplength=820, text_color=T.MUTED,
                             font=T.font(13)).pack(fill="x", padx=14, pady=(4, 10))
            ctk.CTkFrame(c, height=10, fg_color="transparent").pack()
        if an["free_fixes"]:
            c = self.card(p, "Ottimizzazioni gratuite")
            c.pack(fill="x", padx=6, pady=6)
            for fx in an["free_fixes"]:
                ctk.CTkLabel(c, text=f"✓  {fx['title']}", anchor="w", text_color=T.OK,
                             font=T.font(14, "bold")).pack(fill="x", padx=18)
                ctk.CTkLabel(c, text=fx["detail"], anchor="w", justify="left", wraplength=840, text_color=T.MUTED,
                             font=T.font(13)).pack(fill="x", padx=18, pady=(0, 10))

        c = self.card(p, "Upgrade consigliati")
        c.pack(fill="x", padx=6, pady=6)
        if not an["upgrades"]:
            ctk.CTkLabel(c, text="Nessun upgrade necessario: la build è già equilibrata per il suo livello.",
                         anchor="w").pack(fill="x", padx=18, pady=(0, 16))
        prio_lbl = {1: "PRIORITÀ ALTA", 2: "CONSIGLIATO", 3: "OPZIONALE", 4: "ALTERNATIVA"}
        for u in an["upgrades"]:
            f = ctk.CTkFrame(c, fg_color=T.SURF2, corner_radius=10, border_width=1, border_color=T.SURF2)
            f.pack(fill="x", padx=14, pady=5)
            self._hoverable(f)
            head = ctk.CTkFrame(f, fg_color="transparent")
            head.pack(fill="x", padx=14, pady=(12, 2))
            self.chip(head, prio_lbl.get(u["priority"], ""), color=T.PRIORITY.get(u["priority"], T.SURF3),
                      text_color=("#FFFFFF", "#0E0F11")).pack(side="left")
            ctk.CTkLabel(head, text=f"  {u['component']}  ·  {u['name']}", font=T.font(14, "bold"),
                         anchor="w").pack(side="left")
            price = f"~ {u['price_eur']} €" if u.get("price_eur") else "prezzo variabile"
            if u.get("prev_price_eur") and u.get("price_eur"):
                diff = u["price_eur"] - u["prev_price_eur"]
                price += f"  ({'+' if diff > 0 else ''}{diff} €)"
            ctk.CTkLabel(head, text=price, font=T.font(18, kind="num"), text_color=T.ACCENT_TEXT).pack(side="right")
            ctk.CTkLabel(f, text=u["reason"], anchor="w", justify="left", wraplength=840, font=T.font(13)).pack(
                fill="x", padx=14)
            g = u.get("gain") or {}
            if g:
                gl = "     ".join(f"{n}  {g[k]['before']:.1f} → {g[k]['after']:.1f}"
                                  for k, n in (("gaming", "Gaming"), ("office", "Ufficio"),
                                               ("productivity", "Produttività")))
                ctk.CTkLabel(f, text=gl, anchor="w", text_color=T.OK, font=T.font(14, kind="num")).pack(
                    fill="x", padx=14, pady=(6, 0))
            for part in u.get("parts", []) or []:
                ctk.CTkLabel(f, text=f"   •  {part['name']}   ~{part['price_eur']} €", anchor="w",
                             font=T.font(13)).pack(fill="x", padx=14)
            if u.get("note"):
                ctk.CTkLabel(f, text="ℹ  " + u["note"], anchor="w", justify="left", wraplength=840,
                             text_color=T.MUTED, font=T.font(12)).pack(fill="x", padx=14, pady=(4, 0))
            links = ctk.CTkFrame(f, fg_color="transparent")
            links.pack(fill="x", padx=14, pady=(8, 12))
            for name, url in (u.get("links") or {}).items():
                self.btn(links, f"{name}  ↗", lambda x=url: webbrowser.open(x), kind="ghost", width=120,
                         height=30, font=T.font(12)).pack(side="left", padx=(0, 6))
        if an["recommended_total_eur"]:
            ctk.CTkLabel(c, text=f"Totale upgrade prioritari / consigliati:  ~ {an['recommended_total_eur']} €",
                         font=T.font(18, kind="num"), anchor="e").pack(fill="x", padx=18, pady=(8, 16))
        ctk.CTkLabel(p, text="I prezzi sono indicativi: verifica sempre disponibilità e prezzo finale presso il venditore.",
                     text_color=T.MUTED, font=T.font(12)).pack(pady=8)

    # ------------------------------------------------------------------ speed test
    def _page_speed(self, p):
        self.page_title(p, "Rete", "Test velocità connessione",
                        "Misura ping, jitter, download e upload della connessione attuale.")
        c = self.card(p)
        c.pack(fill="x", padx=6, pady=6)
        top = ctk.CTkFrame(c, fg_color="transparent")
        top.pack(fill="x", padx=18, pady=16)
        engines = ["Cloudflare"] + (["Ookla"] if speedtest_engine.ookla_available() else [])
        self.speed_engine = ctk.CTkSegmentedButton(top, values=engines, font=T.font(13, "bold"))
        self.speed_engine.set("Ookla" if self.settings.get("speedtest_engine") == "ookla" and "Ookla" in engines
                              else "Cloudflare")
        self.speed_engine.pack(side="left")
        self.speed_btn = self.btn(top, "Avvia test", self.toggle_speedtest, width=170, height=40,
                                  font=T.font(15, "bold"))
        self.speed_btn.pack(side="right")

        nums = ctk.CTkFrame(c, fg_color="transparent")
        nums.pack(fill="x", padx=12, pady=4)
        self.speed_vals, self._speed_shown = {}, {}
        for i, (k, lab, unit) in enumerate([("download_mbps", "Download", "Mbps"), ("upload_mbps", "Upload", "Mbps"),
                                            ("ping_ms", "Ping", "ms"), ("jitter_ms", "Jitter", "ms")]):
            nums.grid_columnconfigure(i, weight=1, uniform="s")
            f = ctk.CTkFrame(nums, fg_color=T.SURF2, corner_radius=10)
            f.grid(row=0, column=i, sticky="nsew", padx=6)
            ctk.CTkLabel(f, text=lab.upper(), text_color=T.MUTED, font=T.font(12, "bold")).pack(pady=(14, 0))
            v = ctk.CTkLabel(f, text="—", font=T.font(40, kind="num"))
            v.pack()
            ctk.CTkLabel(f, text=unit, text_color=T.MUTED, font=T.font(12)).pack(pady=(0, 14))
            self.speed_vals[k] = v
            self._speed_shown[k] = 0.0
        self.speed_phase = ctk.CTkLabel(c, text="Pronto", anchor="w", text_color=T.MUTED, font=T.font(13))
        self.speed_phase.pack(fill="x", padx=18, pady=(14, 4))
        self.speed_bar = ctk.CTkProgressBar(c, height=6, corner_radius=3)
        self.speed_bar.set(0)
        self.speed_bar.pack(fill="x", padx=18, pady=(0, 18))
        self._speed_frac = 0.0

        self.speed_res_card = self.card(p, "Valutazione connessione")
        self.speed_res_card.pack(fill="x", padx=6, pady=6)
        self._render_speed_result(animate=False)

    def _speed_set(self, k: str, val: float, ms: int = 280, fmt: str = "{:.0f}"):
        lbl = self.speed_vals.get(k)
        if lbl is None or not lbl.winfo_exists():
            return
        start = self._speed_shown.get(k, 0.0)
        self._speed_shown[k] = val

        def step(v):
            lbl.configure(text=fmt.format(v))
        self.anim.tween(f"sp{k}", start, val, ms, step)

    def _render_speed_result(self, animate: bool = True):
        f = self.speed_res_card
        for w in list(f.winfo_children())[1:]:
            w.destroy()
        r = self.speed_result
        if not r:
            ctk.CTkLabel(f, text="Nessun test eseguito.", text_color=T.MUTED, anchor="w").pack(fill="x", padx=18,
                                                                                              pady=(0, 16))
            return
        for k in self.speed_vals:
            val = r.get(k)
            if val in (None, 0) and k == "jitter_ms":
                self.speed_vals[k].configure(text="—")
                continue
            fmt = "{:.1f}" if k in ("ping_ms", "jitter_ms") else "{:.0f}"
            if animate:
                self._speed_set(k, float(val or 0), 700, fmt)
            else:
                self.speed_vals[k].configure(text=fmt.format(float(val or 0)))
                self._speed_shown[k] = float(val or 0)
        rate = speedtest_engine.rate_connection(r)
        row = ctk.CTkFrame(f, fg_color="transparent")
        row.pack(fill="x", padx=18)
        ctk.CTkLabel(row, text=f"{rate['rating']:.1f}", font=T.font(36, kind="num")).pack(side="left")
        st = self._stars(row, 0 if animate else rate["rating"])
        st.pack(side="left", padx=12)
        if animate:
            self.anim.tween("spstars", 0, rate["rating"], 900, st.set)
        self.kv_table(f, [("Motore", r.get("engine")), ("Data", r.get("timestamp")), ("Provider (ISP)", r.get("isp")),
                          ("IP pubblico", r.get("ip")), ("Server", r.get("server")),
                          ("Adatta per", ", ".join(rate["uses"]) or "uso molto limitato")])

    def toggle_speedtest(self):
        if self.speed_cancel:
            self.speed_cancel.cancel()
            self.speed_btn.configure(text="Annullamento…", state="disabled")
            return
        engine = "ookla" if self.speed_engine.get() == "Ookla" else "cloudflare"
        self.settings["speedtest_engine"] = engine
        save_settings(self.settings)
        self.speed_cancel = speedtest_engine.CancelToken()
        self.speed_btn.configure(text="Interrompi", fg_color=T.BAD, hover_color=("#B8292E", "#D9454A"),
                                 text_color=("#FFFFFF", "#FFFFFF"))
        for k, v in self.speed_vals.items():
            v.configure(text="—")
            self._speed_shown[k] = 0.0
        phase_key = {"Download": "download_mbps", "Upload": "upload_mbps"}

        def progress(phase, frac, live):
            def ui():
                if not self.speed_bar.winfo_exists():
                    return
                self.speed_phase.configure(text=f"{phase}…" if frac < 1 else phase)
                self.anim.bar("spbar", self.speed_bar, frac, 240, start=self._speed_frac)
                self._speed_frac = frac
                if live is not None and phase in phase_key:
                    self._speed_set(phase_key[phase], live)
            self.after(0, ui)

        def work():
            try:
                res = speedtest_engine.run(engine, progress, self.speed_cancel)
                self.after(0, lambda: self._speed_done(res, None))
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._speed_done(None, err))

        threading.Thread(target=work, daemon=True).start()

    def _speed_done(self, res, err):
        self.speed_cancel = None
        if not self.speed_btn.winfo_exists():
            return
        self.speed_btn.configure(text="Avvia test", state="normal", fg_color=(T.ACCENT, T.ACCENT),
                                 hover_color=(T.ACCENT_HOVER, T.ACCENT_HOVER), text_color=(T.ON_ACCENT, T.ON_ACCENT))
        self._speed_frac = 0.0
        if err:
            self.speed_phase.configure(text=f"Errore: {err}")
            return
        if res and not res.get("cancelled"):
            self.speed_result = res
            save_json(user_dir() / "last_speedtest.json", res)
            self._render_speed_result(animate=True)
            self.speed_phase.configure(text="Test completato")
        else:
            self.speed_phase.configure(text="Test interrotto")

    # ------------------------------------------------------------------ IA
    def _page_ai(self, p):
        has_key = bool(self.settings.get("anthropic_api_key"))
        self.page_title(p, "Intelligenza artificiale", "Assistente IA",
                        "Analisi approfondita con Claude (Anthropic): verifica la build, cerca i prezzi attuali sul web e "
                        "risponde alle tue domande. L'algoritmo locale funziona anche senza IA.")
        if not has_key:
            w = self.card(p)
            w.pack(fill="x", padx=6, pady=6)
            ctk.CTkLabel(w, text="Per usare l'IA inserisci una API key Anthropic nelle Impostazioni.",
                         anchor="w").pack(side="left", padx=18, pady=16)
            self.btn(w, "Vai alle impostazioni", lambda: self.show("settings"), kind="ghost").pack(side="right", padx=16)
        c = self.card(p, "Analisi della build")
        c.pack(fill="x", padx=6, pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 12))
        ctk.CTkLabel(row, text="Utilizzo", text_color=T.MUTED).pack(side="left")
        self.ai_use = ctk.CTkOptionMenu(row, values=["Misto", "Gaming", "Ufficio", "Produttività / editing",
                                                     "Streaming", "IA locale / sviluppo"])
        self.ai_use.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(row, text="Budget", text_color=T.MUTED).pack(side="left")
        self.ai_budget = ctk.CTkEntry(row, placeholder_text="es. 500 €", width=120)
        self.ai_budget.pack(side="left", padx=8)
        self.ai_btn = self.btn(row, "Analizza con IA", self.run_ai_analysis, width=170,
                               state="normal" if has_key else "disabled")
        self.ai_btn.pack(side="right")
        self.ai_out = ctk.CTkTextbox(c, height=400, wrap="word", font=T.font(13), corner_radius=10)
        self.ai_out.pack(fill="both", expand=True, padx=18, pady=(0, 12))
        self.ai_out.insert("end", "Premi «Analizza con IA» per ricevere un'analisi dettagliata con prezzi aggiornati.")
        self.ai_out.configure(state="disabled")
        q = ctk.CTkFrame(c, fg_color="transparent")
        q.pack(fill="x", padx=18, pady=(0, 18))
        self.ai_q = ctk.CTkEntry(q, placeholder_text="Fai una domanda (es. «Con 300 € cosa conviene cambiare?»)",
                                 height=36)
        self.ai_q.pack(side="left", fill="x", expand=True)
        self.ai_q.bind("<Return>", lambda e: self.ask_ai())
        self.ai_ask_btn = self.btn(q, "Chiedi", self.ask_ai, width=100, state="normal" if has_key else "disabled")
        self.ai_ask_btn.pack(side="left", padx=(8, 0))

    def _ai_write(self, text: str, append: bool = False):
        self.ai_out.configure(state="normal")
        if not append:
            self.ai_out.delete("1.0", "end")
        self.ai_out.insert("end", text)
        self.ai_out.see("end")
        self.ai_out.configure(state="disabled")

    def _ai_typewrite(self, text: str, append: bool = False):
        """Mostra la risposta a blocchi, come se venisse scritta (fluido anche su testi lunghi)."""
        if not self.anim.enabled:
            return self._ai_write(text, append)
        if not append:
            self._ai_write("")
        chunks = [text[i:i + 24] for i in range(0, len(text), 24)]

        def step(i=0):
            if i < len(chunks) and self.ai_out.winfo_exists():
                self._ai_write(chunks[i], append=True)
                self.after(8, lambda: step(i + 1))
        step()

    def _ai_busy(self, busy: bool):
        st = "disabled" if busy else "normal"
        self.ai_btn.configure(state=st)
        self.ai_ask_btn.configure(state=st)

    def run_ai_analysis(self):
        self._ai_busy(True)
        self._ai_write("Analisi in corso… (la ricerca dei prezzi sul web può richiedere fino a un minuto)")
        use, budget = self.ai_use.get(), self.ai_budget.get()

        def work():
            try:
                txt = ai_advisor.analyze_build(self.settings, self.report, self.ev, self.an, budget, use)
                self.ai_history = [{"role": "user", "content": f"Analizza la build (uso {use}, budget {budget})"},
                                   {"role": "assistant", "content": txt}]
            except Exception as e:
                txt = f"Errore: {e}"
            self.after(0, lambda: (self._ai_typewrite(txt), self._ai_busy(False)))

        threading.Thread(target=work, daemon=True).start()

    def ask_ai(self):
        q = self.ai_q.get().strip()
        if not q or not self.settings.get("anthropic_api_key"):
            return
        self.ai_q.delete(0, "end")
        self._ai_busy(True)
        self._ai_write(f"\n\nTu: {q}\n…", append=True)

        def work():
            try:
                ans = ai_advisor.ask(self.settings, self.report, self.ev, self.an, self.ai_history, q)
                self.ai_history += [{"role": "user", "content": q}, {"role": "assistant", "content": ans}]
            except Exception as e:
                ans = f"Errore: {e}"

            def ui():
                self.ai_out.configure(state="normal")
                self.ai_out.delete("end-2c linestart", "end")
                self.ai_out.configure(state="disabled")
                self._ai_typewrite(f"\nIA: {ans}", append=True)
                self._ai_busy(False)
            self.after(0, ui)

        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------------------------ impostazioni
    def _page_settings(self, p):
        self.page_title(p, "Configurazione", "Impostazioni")

        # --- aggiornamenti
        c = self.card(p, "Aggiornamenti dell'app")
        c.pack(fill="x", padx=6, pady=6)
        repo, branch = updater.repo_config(self.settings)
        mode = ("eseguibile (.exe)" if updater.is_frozen() else
                ("copia di sviluppo (git)" if updater.is_dev_copy() else "sorgenti"))
        ctk.CTkLabel(c, text=f"Versione installata: {__version__}   ·   modalità: {mode}", anchor="w",
                     font=T.font(13)).pack(fill="x", padx=18)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=10)
        ctk.CTkLabel(row, text="Repository GitHub", width=150, anchor="w").pack(side="left")
        self.set_repo = ctk.CTkEntry(row, width=300, placeholder_text="utente/PCAnalyzer")
        if repo:
            self.set_repo.insert(0, repo)
        self.set_repo.pack(side="left")
        ctk.CTkLabel(row, text="ramo", text_color=T.MUTED).pack(side="left", padx=(12, 6))
        self.set_branch = ctk.CTkEntry(row, width=90)
        self.set_branch.insert(0, branch)
        self.set_branch.pack(side="left")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 6))
        self.set_autoupd = ctk.CTkSwitch(row, text="Controlla gli aggiornamenti all'avvio")
        if self.settings.get("check_updates", True):
            self.set_autoupd.select()
        self.set_autoupd.pack(side="left")
        self.btn(row, "Verifica ora", self.check_updates_now, width=140).pack(side="right")
        self.upd_status = ctk.CTkLabel(c, text="", anchor="w", text_color=T.MUTED, font=T.font(12), wraplength=860,
                                       justify="left")
        self.upd_status.pack(fill="x", padx=18, pady=(0, 14))

        # --- IA
        c = self.card(p, "Intelligenza artificiale (Anthropic Claude)")
        c.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(c, text="La chiave si ottiene su console.anthropic.com e viene salvata solo su questo PC "
                             f"({user_dir()}).", text_color=T.MUTED, anchor="w", wraplength=860, justify="left",
                     font=T.font(12)).pack(fill="x", padx=18)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=10)
        ctk.CTkLabel(row, text="API key", width=150, anchor="w").pack(side="left")
        self.set_key = ctk.CTkEntry(row, show="•", width=420)
        self.set_key.insert(0, self.settings.get("anthropic_api_key", ""))
        self.set_key.pack(side="left")
        self.btn(row, "Prova chiave", self.test_api_key, kind="ghost", width=130).pack(side="left", padx=8)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 16))
        ctk.CTkLabel(row, text="Modello", width=150, anchor="w").pack(side="left")
        self.set_model = ctk.CTkComboBox(row, width=260, values=["claude-sonnet-5-5", "claude-opus-5-5",
                                                                  "claude-haiku-5-5"])
        self.set_model.set(self.settings.get("ai_model", "claude-sonnet-5-5"))
        self.set_model.pack(side="left")

        # --- prezzi
        c = self.card(p, "Listino prezzi")
        c.pack(fill="x", padx=6, pady=6)
        data = prices.load()
        ctk.CTkLabel(c, text=f"Ultimo aggiornamento: {data.get('updated')} · fonte: {data.get('source')} · "
                             f"{len(data.get('items', []))} articoli", anchor="w", font=T.font(13)).pack(fill="x", padx=18)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=10)
        ctk.CTkLabel(row, text="URL listino", width=150, anchor="w").pack(side="left")
        self.set_url = ctk.CTkEntry(row, width=420, placeholder_text="https://…/prices.json (opzionale)")
        self.set_url.insert(0, self.settings.get("prices_url", ""))
        self.set_url.pack(side="left")
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 16))
        self.btn(row, "Aggiorna prezzi…", self.update_prices_dialog, width=160).pack(side="left")
        self.btn(row, "Apri file listino", lambda: self._open_path(user_file(prices.PRICES_FILE)), kind="ghost",
                 width=160).pack(side="left", padx=8)
        self.btn(row, "Ripristina listino iniziale", self._reset_prices, kind="ghost", width=200).pack(side="left")

        # --- aspetto
        c = self.card(p, "Aspetto")
        c.pack(fill="x", padx=6, pady=6)
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(0, 16))
        self.set_mode = ctk.CTkSegmentedButton(row, values=["Scuro", "Chiaro", "Sistema"], command=self._change_mode)
        self.set_mode.set({"dark": "Scuro", "light": "Chiaro"}.get(self.settings.get("appearance"), "Sistema"))
        self.set_mode.pack(side="left")
        self.set_anim = ctk.CTkSwitch(row, text="Animazioni", command=self._toggle_anim)
        if self.settings.get("animations", True):
            self.set_anim.select()
        self.set_anim.pack(side="left", padx=24)

        self.btn(p, "Salva impostazioni", self.save_settings_ui, height=42, width=220).pack(anchor="e", padx=8, pady=14)

    def _collect_settings(self):
        self.settings["anthropic_api_key"] = self.set_key.get().strip()
        self.settings["ai_model"] = self.set_model.get().strip() or "claude-sonnet-5-5"
        self.settings["prices_url"] = self.set_url.get().strip()
        self.settings["update_repo"] = self.set_repo.get().strip()
        self.settings["update_branch"] = self.set_branch.get().strip() or "main"
        self.settings["check_updates"] = bool(self.set_autoupd.get())

    def save_settings_ui(self):
        self._collect_settings()
        save_settings(self.settings)
        self.toast("Impostazioni salvate")
        # ricostruisce le pagine che dipendono dalle impostazioni (IA)
        for k in ("ai",):
            if k in self.pages:
                self.pages.pop(k).destroy()

    def test_api_key(self):
        self._collect_settings()

        def work():
            try:
                ai_advisor.test_key(self.settings)
                msg, kind = "La chiave API funziona", "ok"
            except Exception as e:
                msg, kind = str(e), "err"
            self.after(0, lambda: self.toast(msg, kind, ms=5000))

        threading.Thread(target=work, daemon=True).start()

    def _change_mode(self, v):
        mode = {"Scuro": "dark", "Chiaro": "light"}.get(v, "system")
        self.settings["appearance"] = mode
        ctk.set_appearance_mode(mode)
        save_settings(self.settings)
        self.after(80, lambda: self.invalidate_pages())

    def _toggle_anim(self):
        self.settings["animations"] = bool(self.set_anim.get())
        self.anim.enabled = self.settings["animations"]
        save_settings(self.settings)

    def _reset_prices(self):
        if messagebox.askyesno(APP_TITLE, "Ripristinare il listino prezzi iniziale?"):
            prices.reset_to_default()
            self.refresh_analysis()
            self.toast("Listino ripristinato")

    @staticmethod
    def _open_path(path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror(APP_TITLE, str(e))

    def _open_uri(self, uri: str):
        try:
            if sys.platform.startswith("win"):
                os.startfile(uri)  # type: ignore[attr-defined]
            else:
                webbrowser.open(uri)
        except Exception as e:
            self.toast(str(e), "err")

    # ------------------------------------------------------------------ aggiornamenti app
    def _auto_check_update(self):
        if not self.settings.get("check_updates", True) or updater.is_frozen():
            return
        repo, _ = updater.repo_config(self.settings)
        if not repo:
            return

        def work():
            try:
                info = updater.check(self.settings)
            except Exception:
                return
            if info["available"] and info["remote"] != self.settings.get("skip_version"):
                self.update_info = info
                self.after(0, lambda: self.toast(f"È disponibile PC Analyzer {info['remote']}", "info",
                                                 action=("Dettagli", self.update_dialog), ms=12000))
        threading.Thread(target=work, daemon=True).start()

    def check_updates_now(self):
        self._collect_settings()
        save_settings(self.settings)
        self.upd_status.configure(text="Controllo in corso…", text_color=T.MUTED)

        def work():
            try:
                info = updater.check(self.settings)
                err = None
            except Exception as e:
                info, err = None, str(e)

            def ui():
                if not self.upd_status.winfo_exists():
                    return
                if err:
                    self.upd_status.configure(text=err, text_color=T.BAD)
                elif info["available"]:
                    self.update_info = info
                    self.upd_status.configure(text=f"Nuova versione disponibile: {info['remote']} "
                                                   f"(installata {info['local']})", text_color=T.ACCENT_TEXT)
                    self.update_dialog()
                else:
                    self.upd_status.configure(text=f"Hai già l'ultima versione ({info['local']}).", text_color=T.OK)
            self.after(0, ui)

        threading.Thread(target=work, daemon=True).start()

    def update_dialog(self):
        info = self.update_info
        if not info:
            return
        win = ctk.CTkToplevel(self)
        win.title("Aggiornamento disponibile")
        win.geometry("560x440")
        win.transient(self)
        if sys.platform.startswith("win"):
            win.after(250, lambda: win.winfo_exists() and win.iconbitmap(str(asset_path("icon.ico"))))
        win.after(150, lambda: win.winfo_exists() and win.grab_set())
        ctk.CTkLabel(win, text="AGGIORNAMENTO", font=T.font(12, "bold"), text_color=T.ACCENT_TEXT).pack(
            anchor="w", padx=24, pady=(22, 0))
        ctk.CTkLabel(win, text=f"PC Analyzer {info['remote']}", font=T.font(24, "bold")).pack(anchor="w", padx=24)
        ctk.CTkLabel(win, text=f"Installata: {info['local']}   ·   pubblicata il {info.get('date') or '—'}",
                     text_color=T.MUTED).pack(anchor="w", padx=24, pady=(0, 10))
        box = ctk.CTkTextbox(win, height=150, wrap="word", font=T.font(13))
        box.pack(fill="x", padx=24)
        box.insert("end", "\n".join(f"•  {n}" for n in info.get("notes") or ["Miglioramenti e correzioni"]))
        box.configure(state="disabled")
        status = ctk.CTkLabel(win, text="", text_color=T.MUTED, wraplength=500, justify="left")
        status.pack(anchor="w", padx=24, pady=(12, 4))
        bar = ctk.CTkProgressBar(win, height=6, corner_radius=3)
        bar.set(0)
        bar.pack(fill="x", padx=24)
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=18)
        state = {"frac": 0.0}

        def prog(msg, frac):
            def ui():
                if win.winfo_exists():
                    status.configure(text=msg)
                    self.anim.bar("updbar", bar, frac, 300, start=state["frac"])
                    state["frac"] = frac
            self.after(0, ui)

        def do_update():
            b_upd.configure(state="disabled", text="Aggiornamento…")
            b_later.configure(state="disabled")

            def work():
                try:
                    res = updater.apply(self.settings, prog)
                    self.after(0, lambda: finished(res, None))
                except Exception as e:
                    err = str(e)
                    self.after(0, lambda: finished(None, err))
            threading.Thread(target=work, daemon=True).start()

        def finished(res, err):
            if err:
                status.configure(text=err, text_color=T.BAD)
                b_upd.configure(state="normal", text="Riprova")
                b_later.configure(state="normal")
                if updater.is_frozen():
                    b_upd.configure(text="Apri GitHub", command=lambda: webbrowser.open(
                        f"https://github.com/{info['repo']}"))
                return
            status.configure(text="Aggiornamento installato. Riavvio dell'app…", text_color=T.OK)
            self.after(1200, updater.restart)

        def skip():
            self.settings["skip_version"] = info["remote"]
            save_settings(self.settings)
            win.destroy()

        b_upd = self.btn(row, "Aggiorna ora", do_update, width=160)
        b_upd.pack(side="right")
        b_later = self.btn(row, "Più tardi", win.destroy, kind="ghost", width=110)
        b_later.pack(side="right", padx=8)
        self.btn(row, "Ignora versione", skip, kind="ghost", width=140).pack(side="left")

    # ------------------------------------------------------------------ prezzi
    def update_prices_dialog(self):
        win = ctk.CTkToplevel(self)
        win.title("Aggiorna prezzi")
        win.geometry("540x350")
        win.transient(self)
        if sys.platform.startswith("win"):
            win.after(250, lambda: win.winfo_exists() and win.iconbitmap(str(asset_path("icon.ico"))))
        win.after(150, lambda: win.winfo_exists() and win.grab_set())
        ctk.CTkLabel(win, text="LISTINO", font=T.font(12, "bold"), text_color=T.ACCENT_TEXT).pack(anchor="w", padx=24,
                                                                                                pady=(22, 0))
        ctk.CTkLabel(win, text="Aggiorna prezzi", font=T.font(22, "bold")).pack(anchor="w", padx=24)
        ctk.CTkLabel(win, text="Scegli la fonte. I prezzi aggiornati vengono usati subito nei suggerimenti.",
                     text_color=T.MUTED, wraplength=480, justify="left").pack(anchor="w", padx=24, pady=(0, 14))
        status = ctk.CTkLabel(win, text="", wraplength=480, justify="left")
        bar = ctk.CTkProgressBar(win, height=6, corner_radius=3)
        bar.set(0)
        st = {"frac": 0.0}

        def done(msg):
            if not win.winfo_exists():
                return
            status.configure(text=msg)
            self.anim.bar("pbar", bar, 1, 300, start=st["frac"])
            for b in (b1, b2):
                b.configure(state="normal")
            self.refresh_analysis()

        def run(kind):
            for b in (b1, b2):
                b.configure(state="disabled")
            status.configure(text="Aggiornamento in corso…")

            def prog(msg, frac):
                def ui():
                    if win.winfo_exists():
                        status.configure(text=msg)
                        self.anim.bar("pbar", bar, frac, 300, start=st["frac"])
                        st["frac"] = frac
                self.after(0, ui)

            def work():
                try:
                    if kind == "url":
                        url = self.settings.get("prices_url", "")
                        if not url:
                            raise RuntimeError("Imposta prima l'URL del listino in Impostazioni.")
                        _, msg = prices.update_from_url(url)
                    else:
                        if not self.settings.get("anthropic_api_key"):
                            raise RuntimeError("Serve una API key Anthropic (Impostazioni).")
                        _, msg = prices.update_with_ai(self.settings, prog)
                except Exception as e:
                    msg = f"Errore: {e}"
                self.after(0, lambda: done(msg))

            threading.Thread(target=work, daemon=True).start()

        b1 = self.btn(win, "Cerca prezzi attuali con IA (ricerca web)", lambda: run("ai"), height=40)
        b1.pack(fill="x", padx=24, pady=4)
        b2 = self.btn(win, "Scarica listino da URL configurato", lambda: run("url"), kind="ghost", height=40)
        b2.pack(fill="x", padx=24, pady=4)
        bar.pack(fill="x", padx=24, pady=(16, 8))
        status.pack(anchor="w", padx=24)

    # ------------------------------------------------------------------ export
    def export_report(self):
        if not self.report:
            return
        path = filedialog.asksaveasfilename(
            title="Esporta report", defaultextension=".txt", initialfile="report_pc.txt",
            filetypes=[("Testo", "*.txt"), ("JSON", "*.json")])
        if not path:
            return
        fn = report_mod.to_json if path.lower().endswith(".json") else report_mod.to_text
        with open(path, "w", encoding="utf-8") as f:
            f.write(fn(self.report, self.ev, self.an, self.speed_result))
        self.toast(f"Report salvato: {os.path.basename(path)}")

    # ------------------------------------------------------------------ live
    def _live_loop(self):
        try:
            if self.live_label is not None and self.live_label.winfo_exists():
                s = hardware.live_stats()
                self.live_label.configure(text=f"CPU {s['cpu_percent']:.0f}%    ·    {s['cpu_mhz']} MHz    ·    "
                                               f"RAM {s['ram_used_gb']} GB ({s['ram_percent']:.0f}%)")
                v = s["cpu_percent"] / 100
                self.anim.bar("live", self.live_bar, v, 600, start=getattr(self, "_live_val", 0.0))
                self._live_val = v
        except Exception:
            pass
        self.after(1000, self._live_loop)


def main():
    app = App()
    app.mainloop()
