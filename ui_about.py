"""
ui_about.py
-----------
Diálogo "Acerca de" de Virtual Webcam.
Exporta: open_about(app)
"""

import tkinter as tk
import webbrowser

import constants as _c

REPO_URL = "https://github.com/nullfuzz-pentest/virtual_webcam"


def open_about(app) -> None:
    """Abre (o cierra si ya está abierto) el diálogo About."""
    if app._about_win and app._about_win.winfo_exists():
        app._about_win.destroy()
        return

    BG      = _c.BG
    BG_BTN  = _c.BG_BTN
    FG      = _c.FG
    FG_DIM  = _c.FG_DIM
    ACCENT  = _c.ACCENT
    ACCENT2 = _c.ACCENT2

    win = tk.Toplevel(app)
    app._about_win = win
    win.title(app.t("about_title"))
    win.configure(bg=BG)
    win.resizable(False, False)

    hdr = tk.Frame(win, bg=ACCENT, pady=14)
    hdr.pack(fill="x")
    tk.Label(hdr, text="Virtual Webcam", font=("Segoe UI", 18, "bold"),
             bg=ACCENT, fg="#ffffff").pack()
    tk.Label(hdr, text=f"v1.7  ·  {app.t('title_sub')}", font=("Segoe UI", 11),
             bg=ACCENT, fg="#dde").pack()

    body = tk.Frame(win, bg=BG, padx=28, pady=20)
    body.pack(fill="x")

    def _row(label: str, value: str):
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text=label, font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=FG_DIM, width=12, anchor="e").pack(side="left", padx=(0, 10))
        tk.Label(row, text=value, font=("Segoe UI", 10),
                 bg=BG, fg=FG, anchor="w").pack(side="left")

    _row(app.t("about_creator"), "nullfuzz")
    _row(app.t("about_license"), "MIT")

    repo_row = tk.Frame(body, bg=BG)
    repo_row.pack(fill="x", pady=4)
    tk.Label(repo_row, text=app.t("about_repo"), font=("Segoe UI", 9, "bold"),
             bg=BG, fg=FG_DIM, width=12, anchor="e").pack(side="left", padx=(0, 10))
    link = tk.Label(repo_row, text=REPO_URL, font=("Segoe UI", 10, "underline"),
                    bg=BG, fg=ACCENT2, cursor="hand2", anchor="w")
    link.pack(side="left")
    link.bind("<Button-1>", lambda _: webbrowser.open(REPO_URL))

    tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=20)
    tk.Button(
        win, text=app.t("about_close"), command=win.destroy,
        bg=ACCENT, fg="#ffffff", activebackground=ACCENT, activeforeground="#ffffff",
        relief="flat", font=("Segoe UI", 10, "bold"),
        padx=24, pady=7, cursor="hand2", bd=0,
    ).pack(pady=16)

    win.update_idletasks()
    x = app.winfo_x() + (app.winfo_width()  - win.winfo_width())  // 2
    y = app.winfo_y() + (app.winfo_height() - win.winfo_height()) // 2
    win.geometry(f"+{x}+{y}")
