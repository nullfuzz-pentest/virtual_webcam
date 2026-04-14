"""
ui_filters.py
-------------
Ventana de filtros de imagen (brillo / contraste / saturación / blur).
Exporta: open_filter_window(app)
"""

import tkinter as tk
import tkinter.ttk as ttk

import constants as _c


def open_filter_window(app) -> None:
    """Abre (o cierra si ya está abierta) la ventana de filtros."""
    if app._filter_win and app._filter_win.winfo_exists():
        app._filter_win.destroy()
        return

    BG      = _c.BG
    BG_BTN  = _c.BG_BTN
    FG      = _c.FG
    FG_DIM  = _c.FG_DIM
    ACCENT  = _c.ACCENT
    ACCENT2 = _c.ACCENT2

    win = tk.Toplevel(app)
    app._filter_win = win
    win.title(app.t("filters_title"))
    win.configure(bg=BG)
    win.resizable(False, False)
    win.attributes("-topmost", True)

    def _slider_row(parent, label_key, var, from_, to_, fmt):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=16, pady=4)
        tk.Label(row, text=app.t(label_key), width=13, anchor="w",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left")
        val_lbl = tk.Label(row, width=5, anchor="e",
                           font=("Consolas", 9), bg=BG, fg=ACCENT2)
        val_lbl.pack(side="right")

        def _update(v):
            val_lbl.config(text=fmt(float(v)))

        sl = ttk.Scale(row, from_=from_, to=to_, orient="horizontal",
                       variable=var, command=_update)
        sl.pack(side="left", fill="x", expand=True, padx=(8, 8))
        val_lbl.config(text=fmt(var.get()))
        return sl

    def _sync_brightness(v):
        if app._thread and app._thread.is_alive():
            app._thread.filter_brightness = float(v)

    def _sync_contrast(v):
        if app._thread and app._thread.is_alive():
            app._thread.filter_contrast = float(v)

    def _sync_saturation(v):
        if app._thread and app._thread.is_alive():
            app._thread.filter_saturation = float(v)

    def _sync_blur(v):
        if app._thread and app._thread.is_alive():
            app._thread.filter_blur = int(float(v))

    tk.Frame(win, bg=BG, height=8).pack()
    _slider_row(win, "lbl_brightness", app._bri_var, -100, 100, lambda v: f"{v:+.0f}")
    _slider_row(win, "lbl_contrast",   app._con_var,  0.5,  2.0, lambda v: f"{v:.2f}")
    _slider_row(win, "lbl_saturation", app._sat_var,  0.0,  2.0, lambda v: f"{v:.2f}")
    _slider_row(win, "lbl_blur",       app._blur_var,   0,   10, lambda v: f"{int(v)}")

    app._bri_var.trace_add("write",  lambda *_: _sync_brightness(app._bri_var.get()))
    app._con_var.trace_add("write",  lambda *_: _sync_contrast(app._con_var.get()))
    app._sat_var.trace_add("write",  lambda *_: _sync_saturation(app._sat_var.get()))
    app._blur_var.trace_add("write", lambda *_: _sync_blur(app._blur_var.get()))

    def _reset():
        app._bri_var.set(0.0)
        app._con_var.set(1.0)
        app._sat_var.set(1.0)
        app._blur_var.set(0.0)

    tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=16, pady=(10, 0))
    tk.Button(win, text=app.t("btn_reset_filters"), command=_reset,
              bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
              relief="flat", font=("Segoe UI", 9), padx=12, pady=5,
              cursor="hand2", bd=0).pack(pady=8)

    win.update_idletasks()
    x = app.winfo_x() + app.winfo_width() + 8
    y = app.winfo_y()
    win.geometry(f"+{x}+{y}")
