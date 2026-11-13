"""
Tema "Graphite Ember": grigio grafite + arancione.

Tutti i colori dell'interfaccia sono qui. Ogni colore è una coppia (chiaro, scuro)
come vuole CustomTkinter; il tema predefinito è quello scuro.
"""
from __future__ import annotations

import sys

import customtkinter as ctk

# ------------------------------------------------------------------ palette
BG = ("#F2F2F3", "#0E0F11")          # sfondo finestra
SIDE = ("#E8E9EB", "#141518")        # barra laterale
SURF = ("#FFFFFF", "#1A1C20")        # pannelli / card
SURF2 = ("#F0F1F3", "#24272C")       # elementi dentro le card, campi
SURF3 = ("#E2E4E7", "#2C3036")       # hover, pulsanti secondari
BORDER = ("#D6D9DD", "#30343A")
TEXT = ("#15171A", "#ECEDEE")
MUTED = ("#5B626B", "#9BA1A8")

ACCENT = "#FF6B1A"                   # arancione
ACCENT_HOVER = "#FF8A3D"
ACCENT_DEEP = "#C2410C"              # arancione scuro (sfondi con testo chiaro)
ACCENT_TEXT = ("#B84A08", "#FF8A3D")  # arancione usato come colore del testo
ACCENT_GLOW = ("#F5B28C", "#6B3A1E")  # bordo delle card al passaggio del mouse
ON_ACCENT = "#140A03"                # testo sopra l'arancione

OK = ("#1E9E5A", "#3DD68C")
WARN = ("#B07D00", "#F5B83D")
BAD = ("#D33A3F", "#F2555A")
INFO = ("#2F6FB3", "#6CA0DC")

SEVERITY = {"alta": BAD, "media": WARN, "bassa": MUTED, "info": INFO}
PRIORITY = {1: BAD, 2: ("#C2410C", "#FF6B1A"), 3: INFO, 4: ("#7A8089", "#9BA1A8")}

# ------------------------------------------------------------------ font
_FONTS = {"ui": None, "num": None, "mono": None}


def init_fonts(root) -> None:
    """Sceglie i font disponibili (da chiamare dopo aver creato la finestra)."""
    import tkinter.font as tkfont
    fams = set(tkfont.families(root))

    def first(*names):
        return next((n for n in names if n in fams), None)
    _FONTS["ui"] = first("Segoe UI Variable Text", "Segoe UI", "Inter", "Roboto")
    # Bahnschrift (Windows 10/11): carattere "da cruscotto" per i numeri
    _FONTS["num"] = first("Bahnschrift SemiBold", "Bahnschrift", "Barlow Semi Condensed", "DIN Alternate") or _FONTS["ui"]
    _FONTS["mono"] = first("Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono")


def font(size: int = 13, weight: str = "normal", kind: str = "ui") -> ctk.CTkFont:
    fam = _FONTS.get(kind) or _FONTS.get("ui")
    if kind == "num" and fam and fam.startswith("Bahnschrift SemiBold"):
        weight = "normal"  # la variante SemiBold è già "pesante"
    return ctk.CTkFont(family=fam, size=size, weight=weight) if fam else ctk.CTkFont(size=size, weight=weight)


# ------------------------------------------------------------------ CustomTkinter
def apply_ctk_theme() -> None:
    """Parte dal tema 'blue' incluso e sovrascrive solo le chiavi esistenti."""
    ctk.set_default_color_theme("blue")
    t = ctk.ThemeManager.theme

    def setc(widget: str, **kw):
        if widget not in t:
            return
        for k, v in kw.items():
            if k in t[widget]:
                t[widget][k] = list(v) if isinstance(v, tuple) else v

    setc("CTk", fg_color=BG)
    setc("CTkToplevel", fg_color=BG)
    setc("CTkFrame", fg_color=SURF, top_fg_color=SURF2, border_color=BORDER)
    setc("CTkButton", fg_color=(ACCENT, ACCENT), hover_color=(ACCENT_HOVER, ACCENT_HOVER),
         text_color=(ON_ACCENT, ON_ACCENT), text_color_disabled=("#8A8F96", "#6B7079"), border_color=BORDER,
         corner_radius=8)
    setc("CTkLabel", text_color=TEXT)
    setc("CTkEntry", fg_color=SURF2, border_color=BORDER, text_color=TEXT, placeholder_text_color=MUTED,
         corner_radius=8)
    setc("CTkProgressBar", fg_color=SURF2, progress_color=(ACCENT, ACCENT), border_color=BORDER)
    setc("CTkOptionMenu", fg_color=SURF2, button_color=SURF3, button_hover_color=BORDER, text_color=TEXT)
    setc("CTkComboBox", fg_color=SURF2, border_color=BORDER, button_color=SURF3, button_hover_color=BORDER,
         text_color=TEXT)
    setc("CTkScrollbar", button_color=SURF3, button_hover_color=BORDER)
    setc("CTkSegmentedButton", fg_color=SURF2, selected_color=(ACCENT_DEEP, ACCENT_DEEP),
         selected_hover_color=(ACCENT, ACCENT), unselected_color=SURF2, unselected_hover_color=SURF3,
         text_color=TEXT)
    setc("CTkTextbox", fg_color=SURF2, border_color=BORDER, text_color=TEXT, scrollbar_button_color=SURF3,
         scrollbar_button_hover_color=BORDER)
    setc("CTkScrollableFrame", label_fg_color=SURF2)
    setc("CTkSwitch", fg_color=SURF3, progress_color=(ACCENT_DEEP, ACCENT_DEEP), button_color=("#FFFFFF", "#ECEDEE"),
         button_hover_color=("#FFFFFF", "#FFFFFF"), text_color=TEXT)
    setc("CTkCheckBox", fg_color=(ACCENT_DEEP, ACCENT_DEEP), border_color=BORDER, hover_color=(ACCENT, ACCENT),
         checkmark_color=("#FFFFFF", "#FFFFFF"), text_color=TEXT)
    setc("DropdownMenu", fg_color=SURF2, hover_color=SURF3, text_color=TEXT)
    if "CTkFont" in t:
        osk = "Windows" if sys.platform.startswith("win") else ("macOS" if sys.platform == "darwin" else "Linux")
        if osk in t["CTkFont"] and sys.platform.startswith("win"):
            t["CTkFont"][osk]["family"] = "Segoe UI"


def pick(color) -> str:
    """Colore effettivo per la modalità corrente (per i widget tkinter puri)."""
    if isinstance(color, (tuple, list)):
        return color[1] if ctk.get_appearance_mode() == "Dark" else color[0]
    return color


def rating_color(r: float):
    if r < 2:
        return BAD
    if r < 3:
        return WARN
    if r < 4:
        return ("#7A9A00", "#C6E25A")
    return OK
