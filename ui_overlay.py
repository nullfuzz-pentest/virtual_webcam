"""
ui_overlay.py
-------------
Ventana de overlay (texto + imagen sobre el stream).
Exporta: open_overlay_window(app)
"""

import tkinter as tk
import tkinter.ttk as ttk
from tkinter import filedialog

import cv2
import numpy as np

import constants as _c
from overlay import OverlayConfig

_CV_FONTS = {
    "Duplex":          cv2.FONT_HERSHEY_DUPLEX,
    "Simplex":         cv2.FONT_HERSHEY_SIMPLEX,
    "Complex":         cv2.FONT_HERSHEY_COMPLEX,
    "Triplex":         cv2.FONT_HERSHEY_TRIPLEX,
    "Plain":           cv2.FONT_HERSHEY_PLAIN,
    "Small":           cv2.FONT_HERSHEY_COMPLEX_SMALL,
    "Script Simplex":  cv2.FONT_HERSHEY_SCRIPT_SIMPLEX,
    "Script Complex":  cv2.FONT_HERSHEY_SCRIPT_COMPLEX,
    "Duplex Italic":   cv2.FONT_HERSHEY_DUPLEX   | cv2.FONT_ITALIC,
    "Simplex Italic":  cv2.FONT_HERSHEY_SIMPLEX  | cv2.FONT_ITALIC,
    "Complex Italic":  cv2.FONT_HERSHEY_COMPLEX  | cv2.FONT_ITALIC,
    "Triplex Italic":  cv2.FONT_HERSHEY_TRIPLEX  | cv2.FONT_ITALIC,
}
_CV_FONT_NAMES = list(_CV_FONTS.keys())
_CV_FONT_IDS   = {v: k for k, v in _CV_FONTS.items()}


# ------------------------------------------------------------------
# Helpers de overlay (usados dentro de open_overlay_window)
# ------------------------------------------------------------------

def _load_overlay_image(app, path: str) -> None:
    """Carga y escala un PNG con canal alfa en app._overlay.img_bgra."""
    try:
        img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if img is None:
            return
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        app._overlay.img_path = path
        _apply_overlay_scale(app, img)
    except Exception:
        pass


def _apply_overlay_scale(app, raw_bgra: np.ndarray) -> None:
    s = app._overlay.img_scale
    h, w = raw_bgra.shape[:2]
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    app._overlay.img_bgra  = cv2.resize(raw_bgra, (nw, nh), interpolation=cv2.INTER_AREA)
    app._overlay._raw_bgra = raw_bgra


def _reload_overlay_image(app) -> None:
    raw = getattr(app._overlay, "_raw_bgra", None)
    if raw is not None:
        _apply_overlay_scale(app, raw)


def _build_pos_grid(app, parent: tk.Frame, ov: OverlayConfig, attr: str) -> None:
    """Crea una cuadrícula 3×3 de radiobuttons para elegir posición."""
    BG      = _c.BG
    BG_BTN  = _c.BG_BTN
    FG      = _c.FG

    POS_GRID = [
        ["top-left",    "top-center",    "top-right"   ],
        ["center",      "center",        "center"      ],
        ["bottom-left", "bottom-center", "bottom-right"],
    ]
    LABELS = [
        ["↖", "↑", "↗"],
        ["",  "·", "" ],
        ["↙", "↓", "↘"],
    ]
    var  = tk.StringVar(value=getattr(ov, attr))
    grid = tk.Frame(parent, bg=BG)
    grid.pack(side="left", padx=(8, 0))
    for ri, row in enumerate(POS_GRID):
        for ci, pos in enumerate(row):
            lbl = LABELS[ri][ci]
            if not lbl:
                tk.Label(grid, width=3, bg=BG).grid(row=ri, column=ci)
                continue
            xy_attr = "text_xy" if attr == "text_pos" else "img_xy"
            rb = tk.Radiobutton(
                grid, text=lbl, value=pos, variable=var,
                command=lambda p=pos, a=attr, xa=xy_attr: (
                    setattr(ov, a, p), setattr(ov, xa, None)),
                bg=BG, fg=FG, activebackground=BG, selectcolor=BG_BTN,
                font=("Segoe UI", 10), indicatoron=False,
                relief="flat", padx=4, pady=2, cursor="hand2",
            )
            rb.grid(row=ri, column=ci, padx=1, pady=1)


# ------------------------------------------------------------------
# Ventana principal de overlay
# ------------------------------------------------------------------

def open_overlay_window(app) -> None:
    """Abre (o cierra si ya está abierta) la ventana de overlay."""
    if app._overlay_win and app._overlay_win.winfo_exists():
        app._overlay_win.destroy()
        return

    BG      = _c.BG
    BG_BTN  = _c.BG_BTN
    FG      = _c.FG
    FG_DIM  = _c.FG_DIM
    ACCENT  = _c.ACCENT
    ACCENT2 = _c.ACCENT2

    ov  = app._overlay
    win = tk.Toplevel(app)
    app._overlay_win = win
    win.title(app.t("overlay_title"))
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.bind("<Escape>", lambda _: win.destroy())

    def _lbl(parent, key):
        tk.Label(parent, text=app.t(key), width=14, anchor="w",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left")

    def _section(title):
        tk.Label(win, text=f"── {app.t(title)} ──",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=ACCENT2,
                 anchor="w").pack(fill="x", padx=16, pady=(10, 4))

    def _row():
        f = tk.Frame(win, bg=BG)
        f.pack(fill="x", padx=16, pady=3)
        return f

    enable_var = tk.BooleanVar(value=ov.enabled)

    def _toggle_enable():
        ov.enabled = enable_var.get()

    tk.Frame(win, bg=BG, height=8).pack()
    tk.Checkbutton(win, text=app.t("lbl_ovl_enable"), variable=enable_var,
                   command=_toggle_enable,
                   font=("Segoe UI", 10, "bold"), bg=BG, fg=FG,
                   activebackground=BG, selectcolor=BG_BTN,
                   cursor="hand2").pack(anchor="w", padx=16)

    # ══════════════════ TEXTO ══════════════════
    _section("ovl_section_text")

    r = _row(); _lbl(r, "lbl_ovl_text")
    text_var = tk.StringVar(value=ov.text)
    tk.Entry(r, textvariable=text_var, width=26,
             bg=BG_BTN, fg=FG, insertbackground=FG,
             relief="flat", font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True)

    def _upd_text(*_):
        ov.text = text_var.get()

    text_var.trace_add("write", _upd_text)

    r = _row(); _lbl(r, "lbl_ovl_size")
    size_var = tk.DoubleVar(value=ov.font_scale)
    size_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
    size_lbl.pack(side="right")

    def _upd_size(v):
        ov.font_scale = float(v)
        size_lbl.config(text=f"{float(v):.1f}")

    size_lbl.config(text=f"{ov.font_scale:.1f}")
    ttk.Scale(r, from_=0.4, to=12.0, orient="horizontal",
              variable=size_var, command=_upd_size).pack(
        side="left", fill="x", expand=True, padx=(8, 8))

    r = _row(); _lbl(r, "lbl_ovl_font")
    _cur_font_name = _CV_FONT_IDS.get(ov.font_id, "Duplex")
    font_var = tk.StringVar(value=_cur_font_name)

    def _upd_font(_, *__):
        ov.font_id = _CV_FONTS.get(font_var.get(), cv2.FONT_HERSHEY_DUPLEX)

    font_cb = ttk.Combobox(r, textvariable=font_var, values=_CV_FONT_NAMES,
                           state="readonly", width=18)
    font_cb.pack(side="left", padx=(0, 4))
    font_cb.bind("<<ComboboxSelected>>", _upd_font)

    r = _row(); _lbl(r, "lbl_ovl_color")
    _color_hex = [f"#{ov.text_color_bgr[2]:02x}{ov.text_color_bgr[1]:02x}{ov.text_color_bgr[0]:02x}"]
    color_preview = tk.Label(r, width=3, bg=_color_hex[0], relief="flat")
    color_preview.pack(side="left", padx=(0, 6))

    def _pick_color():
        import tkinter.colorchooser as cc
        result = cc.askcolor(color=_color_hex[0], parent=win)
        if result[1]:
            _color_hex[0] = result[1]
            color_preview.config(bg=result[1])
            hex_col = result[1].lstrip("#")
            r2, g2, b2 = int(hex_col[0:2], 16), int(hex_col[2:4], 16), int(hex_col[4:6], 16)
            ov.text_color_bgr = (b2, g2, r2)

    tk.Button(r, text=app.t("btn_pick_color"), command=_pick_color,
              bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
              relief="flat", font=("Segoe UI", 9), padx=8, pady=2,
              cursor="hand2", bd=0).pack(side="left")

    r = _row(); _lbl(r, "lbl_ovl_text_pos")
    _build_pos_grid(app, r, ov, "text_pos")

    r = _row(); _lbl(r, "lbl_ovl_text_bg")
    bg_var = tk.DoubleVar(value=ov.text_bg_alpha)
    bg_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
    bg_lbl.pack(side="right")

    def _upd_bg(v):
        ov.text_bg_alpha = float(v)
        bg_lbl.config(text=f"{float(v):.0%}")

    bg_lbl.config(text=f"{ov.text_bg_alpha:.0%}")
    ttk.Scale(r, from_=0.0, to=1.0, orient="horizontal",
              variable=bg_var, command=_upd_bg).pack(
        side="left", fill="x", expand=True, padx=(8, 8))

    # ══════════════════ IMAGEN ══════════════════
    tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=16, pady=(8, 0))
    _section("ovl_section_img")

    r = _row(); _lbl(r, "lbl_ovl_img_file")
    img_path_var = tk.StringVar(value=ov.img_path)
    tk.Entry(r, textvariable=img_path_var, width=20,
             bg=BG_BTN, fg=FG, insertbackground=FG,
             relief="flat", font=("Segoe UI", 9)).pack(
        side="left", fill="x", expand=True, padx=(0, 4))

    def _browse_img():
        p = filedialog.askopenfilename(
            parent=win, title=app.t("dlg_pick_img"),
            filetypes=[("PNG", "*.png"), ("All", "*.*")])
        if p:
            img_path_var.set(p)
            _load_overlay_image(app, p)

    tk.Button(r, text=app.t("btn_browse"), command=_browse_img,
              bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
              relief="flat", font=("Segoe UI", 9), padx=6, pady=2,
              cursor="hand2", bd=0).pack(side="left")

    r = _row(); _lbl(r, "lbl_ovl_img_pos")
    _build_pos_grid(app, r, ov, "img_pos")

    r = _row(); _lbl(r, "lbl_ovl_img_scale")
    sc_var = tk.DoubleVar(value=ov.img_scale)
    sc_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
    sc_lbl.pack(side="right")

    def _upd_scale(v):
        ov.img_scale = float(v)
        sc_lbl.config(text=f"{float(v):.2f}×")
        _reload_overlay_image(app)

    sc_lbl.config(text=f"{ov.img_scale:.2f}×")
    ttk.Scale(r, from_=0.05, to=3.0, orient="horizontal",
              variable=sc_var, command=_upd_scale).pack(
        side="left", fill="x", expand=True, padx=(8, 8))

    r = _row(); _lbl(r, "lbl_ovl_img_alpha")
    al_var = tk.DoubleVar(value=ov.img_alpha)
    al_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
    al_lbl.pack(side="right")

    def _upd_alpha(v):
        ov.img_alpha = float(v)
        al_lbl.config(text=f"{float(v):.0%}")

    al_lbl.config(text=f"{ov.img_alpha:.0%}")
    ttk.Scale(r, from_=0.0, to=1.0, orient="horizontal",
              variable=al_var, command=_upd_alpha).pack(
        side="left", fill="x", expand=True, padx=(8, 8))

    tk.Frame(win, bg=BG, height=10).pack()
    win.update_idletasks()
    x = app.winfo_x() + app.winfo_width() + 8
    y = app.winfo_y() + 220
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    x = min(x, sw - win.winfo_width()  - 4)
    y = min(y, sh - win.winfo_height() - 4)
    x = max(x, 0)
    y = max(y, 0)
    win.geometry(f"+{x}+{y}")
