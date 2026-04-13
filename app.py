"""
app.py
------
Clase App: ventana principal de la aplicación (GUI Tkinter).
"""

import time
import locale
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk
import tkinter.ttk as ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

import constants as _constants_mod
from constants import (
    _AppBase, TKDND_AVAILABLE, DND_FILES, PYVIRTUALCAM_AVAILABLE, PixelFormat,
    MSS_AVAILABLE, ASPECT_PRESETS, _PRESET_NUMERIC_KEYS,
    PREVIEW_W, PREVIEW_H, PREVIEW_MIN_INTERVAL,
    BG, BG_PANEL, BG_BTN, ACCENT, ACCENT2, FG, FG_DIM, RED, STATUS_BG,
    THEMES, THEME_KEYS,
)
from translations import TRANSLATIONS, LANG_ORDER
from image_utils import detect_source_type, fit_frame, bgr_to_rgb
from overlay import OverlayConfig, get_overlay_rects
from stream_thread import StreamThread


class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("Virtual Webcam v1.1")
        self.configure(bg=BG)
        self.resizable(False, False)

        self._lang           = self._detect_lang()   # idioma activo
        self._theme_name     = "dark"                # tema activo
        self._thread: StreamThread | None = None
        self._last_photo     = None
        self._seek_dragging  = False
        self._last_preview_time = 0.0
        self._file_loaded    = False
        self._use_screen     = False
        self._screen_monitor_idx = 0
        self.mirror_var      = tk.BooleanVar(value=False)
        self._thumb_photo    = None
        # filtros — DoubleVars sincronizadas con el hilo
        self._bri_var  = tk.DoubleVar(value=0.0)
        self._con_var  = tk.DoubleVar(value=1.0)
        self._sat_var  = tk.DoubleVar(value=1.0)
        self._blur_var = tk.DoubleVar(value=0.0)
        self._zoom_var = tk.DoubleVar(value=1.0)
        # overlay compartido con el thread
        self._overlay      = OverlayConfig()
        self._filter_win   = None
        self._overlay_win  = None
        self._about_win    = None
        self.preview_w       = PREVIEW_W
        self.preview_h       = PREVIEW_H
        # drag overlay en canvas
        self._drag_overlay_type: "str | None" = None
        self._drag_frame_offset: tuple = (0.0, 0.0)

        self._build_ui()
        self._bind_keys()
        self._setup_dnd()
        self._center_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_lang() -> str:
        """Detecta el idioma del sistema y devuelve el código más cercano disponible."""
        _PREFIX_MAP = {"es": "es", "pt": "pt", "zh": "zh", "en": "en"}
        try:
            tag = locale.getlocale()[0] or ""          # e.g. "es_ES", "pt_BR", "zh_CN"
            prefix = tag[:2].lower()
            return _PREFIX_MAP.get(prefix, "es")
        except Exception:
            return "es"

    def t(self, key: str, **kwargs) -> str:
        """Devuelve la cadena traducida al idioma activo."""
        text = TRANSLATIONS[self._lang].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def _apply_lang(self):
        """Actualiza todos los textos de la UI al idioma activo."""
        self._lbl_subtitle.config(text=self.t("title_sub"))
        self._lbl_lang.config(text=self.t("language_label"))
        self._lbl_theme.config(text=self.t("lbl_theme"))
        self.btn_about.config(text=self.t("btn_about"))
        self.btn_open.config(text=self.t("btn_open"))
        self.btn_screen.config(text=self.t("btn_screen"))
        self._lbl_monitor.config(text=self.t("lbl_monitor"))
        self._chk_cursor.config(text=self.t("chk_cursor"))
        self._refresh_monitor_list()
        if not self._file_loaded:
            self.source_var.set(self.t("no_file_selected"))
        elif self._use_screen:
            idx = self._screen_monitor_idx
            if idx == 0:
                self.source_var.set(self.t("screen_label_all"))
            else:
                self.source_var.set(self.t("screen_label", n=idx))
        old_val = self.preset_var.get()
        new_values = _PRESET_NUMERIC_KEYS + [self.t("preset_custom")]
        self._preset_cb["values"] = new_values
        if old_val not in _PRESET_NUMERIC_KEYS:
            self.preset_var.set(self.t("preset_custom"))
        self._lbl_resolution.config(text=self.t("lbl_resolution"))
        self._lbl_width.config(text=self.t("lbl_width"))
        self._lbl_height.config(text=self.t("lbl_height"))
        self._lbl_fps_param.config(text=self.t("lbl_fps"))
        self._lbl_backend.config(text=self.t("lbl_backend"))
        self._chk_loop.config(text=self.t("lbl_loop"))
        self._chk_mirror.config(text=self.t("lbl_mirror"))
        if self.cover_var.get():
            self.btn_fit.config(text=self.t("btn_crop"))
        else:
            self.btn_fit.config(text=self.t("btn_letterbox"))
        self.btn_play.config(text=self.t("btn_start"))
        self.btn_stop.config(text=self.t("btn_stop"))
        self.btn_filters_open.config(text=self.t("btn_filters"))
        self.btn_overlay_open.config(text=self.t("btn_overlay"))
        if self._thread and self._thread.is_alive() and self._thread.is_paused:
            self.btn_pause.config(text=self.t("btn_resume"))
        else:
            self.btn_pause.config(text=self.t("btn_pause"))
        if not (self._thread and self._thread.is_alive()):
            if not self._file_loaded:
                self.status_var.set(self.t("status_ready"))
            elif self._use_screen:
                self.status_var.set(self.t("status_screen"))
        self._draw_placeholder()

    def _on_lang_change(self, _=None):
        display = self._lang_var.get()
        self._lang = next(
            (code for code in LANG_ORDER
             if TRANSLATIONS[code]["lang_display"] == display),
            "es"
        )
        self._apply_lang()

    def _on_theme_change(self, _=None):
        display_to_key = {"Dark": "dark", "Blue": "blue", "White": "white"}
        name = display_to_key.get(self._theme_var.get(), "dark")
        if name != self._theme_name:
            self._apply_theme(name)

    def _apply_theme(self, name: str):
        """Aplica el tema indicado recoloreando todos los widgets activos y actualizando
        las variables de módulo para que las ventanas que se abran después usen los colores nuevos."""
        theme    = THEMES[name]
        cur      = THEMES[self._theme_name]
        COLOR_KEYS = ("BG", "BG_PANEL", "BG_BTN", "ACCENT", "ACCENT2",
                      "FG", "FG_DIM", "RED", "STATUS_BG")

        # Mapa: hex_actual (minúsculas) → hex_nuevo
        old_new = {cur[k].lower(): theme[k] for k in COLOR_KEYS if cur[k].lower() != theme[k].lower()}
        if not old_new:
            return

        # Recolorear árbol de widgets
        def _walk(w):
            self._recolor_widget(w, old_new)
            for child in w.winfo_children():
                _walk(child)
        _walk(self)

        # Actualizar variables del módulo constants (para futuras ventanas)
        for k in COLOR_KEYS:
            setattr(_constants_mod, k, theme[k])

        # Actualizar los nombres importados en este módulo (para _open_*/_show_about)
        g = globals()
        for k in COLOR_KEYS:
            g[k] = theme[k]

        # Re-aplicar estilos ttk
        style = ttk.Style(self)
        style.configure("TScale",    background=theme["BG"],     troughcolor=theme["BG_BTN"],
                        sliderlength=14, sliderrelief="flat")
        style.configure("TCombobox", fieldbackground=theme["BG_BTN"],
                        background=theme["BG_BTN"], foreground=theme["FG"],
                        selectbackground=theme["ACCENT"], arrowcolor=theme["FG"])
        self.option_add("*TCombobox*Listbox.background", theme["BG_BTN"])
        self.option_add("*TCombobox*Listbox.foreground", theme["FG"])

        self._theme_name = name

    @staticmethod
    def _recolor_widget(w, old_new: dict):
        """Actualiza los colores de un widget según el mapa {hex_viejo: hex_nuevo}."""
        OPTIONS = ("bg", "background", "fg", "foreground",
                   "activebackground", "activeforeground",
                   "selectcolor", "insertbackground")
        cfg = {}
        for opt in OPTIONS:
            try:
                cur = w.cget(opt)
                if isinstance(cur, str) and cur.lower() in old_new:
                    cfg[opt] = old_new[cur.lower()]
            except tk.TclError:
                pass
        if cfg:
            try:
                w.config(**cfg)
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── título
        title_bar = tk.Frame(self, bg=BG, pady=8)
        title_bar.pack(fill="x", padx=16)

        tk.Label(title_bar, text="Virtual Webcam", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        self._lbl_subtitle = tk.Label(title_bar, text=self.t("title_sub"),
                                      font=("Segoe UI", 16), bg=BG, fg=FG_DIM)
        self._lbl_subtitle.pack(side="left", padx=(4, 0))

        lang_frame = tk.Frame(title_bar, bg=BG)
        lang_frame.pack(side="right")

        self.btn_about = tk.Button(
            title_bar, text=self.t("btn_about"), command=self._show_about,
            bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
            relief="flat", font=("Segoe UI", 9), padx=10, pady=3,
            cursor="hand2", bd=0,
        )
        self.btn_about.pack(side="right", padx=(0, 12))
        # selector de tema
        self._lbl_theme = tk.Label(lang_frame, text=self.t("lbl_theme"),
                                   font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self._lbl_theme.pack(side="left", padx=(0, 4))
        _theme_display = {"dark": "Dark", "blue": "Blue", "white": "White"}
        self._theme_var = tk.StringVar(value=_theme_display[self._theme_name])
        theme_cb = ttk.Combobox(
            lang_frame, textvariable=self._theme_var, width=6, state="readonly",
            values=["Dark", "Blue", "White"],
        )
        theme_cb.pack(side="left")
        theme_cb.bind("<<ComboboxSelected>>", self._on_theme_change)

        # selector de idioma
        self._lbl_lang = tk.Label(lang_frame, text=self.t("language_label"),
                                  font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self._lbl_lang.pack(side="left", padx=(14, 4))
        self._lang_var = tk.StringVar(value=self.t("lang_display"))
        lang_cb = ttk.Combobox(
            lang_frame, textvariable=self._lang_var, width=10, state="readonly",
            values=[TRANSLATIONS[c]["lang_display"] for c in LANG_ORDER],
        )
        lang_cb.pack(side="left")
        lang_cb.bind("<<ComboboxSelected>>", self._on_lang_change)

        # ── preview
        self.preview_outer = tk.Frame(self, bg="#000000", padx=2, pady=2)
        self.preview_outer.pack(padx=16, pady=(0, 10))
        self.canvas = tk.Canvas(self.preview_outer, width=self.preview_w, height=self.preview_h,
                                bg="#000000", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>",        self._on_canvas_press)
        self.canvas.bind("<B1-Motion>",       self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self._draw_placeholder()

        # ── barra de progreso (video)
        progress_frame = tk.Frame(self, bg=BG)
        progress_frame.pack(fill="x", padx=16, pady=(0, 6))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Scale(progress_frame, from_=0, to=1,
                                  orient="horizontal", variable=self.progress_var,
                                  command=self._on_seek_drag)
        self.progress.pack(fill="x")
        self.progress.bind("<Button-1>",        self._on_seek_click)
        self.progress.bind("<B1-Motion>",       self._on_seek_click)
        self.progress.bind("<ButtonRelease-1>", self._on_seek_release)

        time_row = tk.Frame(progress_frame, bg=BG)
        time_row.pack(fill="x")
        self.time_label = tk.Label(time_row, text="0:00 / 0:00",
                                   font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self.time_label.pack(side="left")
        self.fps_label = tk.Label(time_row, text="",
                                  font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self.fps_label.pack(side="right")

        # ── panel de controles
        ctrl = tk.Frame(self, bg=BG_PANEL, padx=16, pady=12)
        ctrl.pack(fill="x", padx=16, pady=(0, 6))

        # fila 1: thumbnail + archivo + botones abrir / capturar pantalla
        row1 = tk.Frame(ctrl, bg=BG_PANEL)
        row1.pack(fill="x", pady=(0, 4))

        self._thumb_label = tk.Label(row1, bg=BG_PANEL, width=64, height=36,
                                     relief="flat", bd=0)
        self._thumb_label.pack(side="left", padx=(0, 8))
        self._update_thumbnail(None)

        self.source_var = tk.StringVar(value=self.t("no_file_selected"))
        tk.Label(row1, textvariable=self.source_var, font=("Segoe UI", 9),
                 bg=BG_PANEL, fg=FG, anchor="w",
                 wraplength=360).pack(side="left", fill="x", expand=True)
        self.btn_open = self._btn(row1, self.t("btn_open"), self._open_file, color=ACCENT)
        self.btn_open.pack(side="right", padx=(8, 0))
        self.btn_screen = self._btn(row1, self.t("btn_screen"), self._select_screen, color=BG_BTN)
        self.btn_screen.pack(side="right")

        # fila 1c: selector de monitor
        row1c = tk.Frame(ctrl, bg=BG_PANEL)
        row1c.pack(fill="x", pady=(0, 4))
        self._lbl_monitor = tk.Label(row1c, text=self.t("lbl_monitor"),
                                     font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM)
        self._lbl_monitor.pack(side="left", padx=(0, 6))
        self._monitor_var = tk.StringVar(value=self.t("monitor_all"))
        self._monitor_cb = ttk.Combobox(row1c, textvariable=self._monitor_var,
                                        width=22, state="disabled",
                                        values=[self.t("monitor_all")])
        self._monitor_cb.pack(side="left")
        self._monitor_cb.bind("<<ComboboxSelected>>", self._on_monitor_change)
        self._refresh_monitor_list()
        self._show_cursor_var = tk.BooleanVar(value=True)
        self._chk_cursor = tk.Checkbutton(
            row1c, text=self.t("chk_cursor"), variable=self._show_cursor_var,
            command=self._on_cursor_toggle,
            font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM,
            activebackground=BG_PANEL, activeforeground=FG,
            selectcolor=BG_BTN, cursor="hand2",
        )
        self._chk_cursor.pack(side="left", padx=(12, 0))

        # fila 2: preset de aspecto
        row2a = tk.Frame(ctrl, bg=BG_PANEL)
        row2a.pack(fill="x", pady=(0, 8))
        self._lbl_resolution = tk.Label(row2a, text=self.t("lbl_resolution"),
                                        font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM)
        self._lbl_resolution.pack(side="left", padx=(0, 6))
        self.preset_var = tk.StringVar(value=_PRESET_NUMERIC_KEYS[0])
        self._preset_cb = ttk.Combobox(
            row2a, textvariable=self.preset_var, width=20, state="readonly",
            values=_PRESET_NUMERIC_KEYS + [self.t("preset_custom")],
        )
        self._preset_cb.pack(side="left")
        self._preset_cb.bind("<<ComboboxSelected>>", self._apply_preset)
        self.aspect_label = tk.Label(row2a, text="16:9", font=("Segoe UI", 9, "bold"),
                                     bg=BG_PANEL, fg=ACCENT2)
        self.aspect_label.pack(side="left", padx=(10, 0))

        # fila 3: parámetros manuales
        row2 = tk.Frame(ctrl, bg=BG_PANEL)
        row2.pack(fill="x", pady=(0, 10))
        self._lbl_width  = self._param(self.t("lbl_width"),  row2, "width_var",  "1280")
        self._lbl_height = self._param(self.t("lbl_height"), row2, "height_var", "720")
        self._lbl_fps_param = self._param(self.t("lbl_fps"), row2, "fps_var",    "30")
        self._lbl_backend = tk.Label(row2, text=self.t("lbl_backend"),
                                     font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM)
        self._lbl_backend.pack(side="left", padx=(16, 4))
        self.backend_var = tk.StringVar(value="auto")
        backend_cb = ttk.Combobox(row2, textvariable=self.backend_var, width=14,
                                  values=["auto", "obs", "unitycapture", "v4l2loopback"],
                                  state="readonly")
        backend_cb.pack(side="left")

        # fila 4: opciones de reproducción (loop + encuadre)
        row3 = tk.Frame(ctrl, bg=BG_PANEL)
        row3.pack(fill="x", pady=(0, 8))
        self.loop_var = tk.BooleanVar(value=True)
        self._chk_loop = tk.Checkbutton(
            row3, text=self.t("lbl_loop"), variable=self.loop_var,
            font=("Segoe UI", 10), bg=BG_PANEL, fg=FG,
            activebackground=BG_PANEL, activeforeground=FG,
            selectcolor=BG_BTN, cursor="hand2",
        )
        self._chk_loop.pack(side="left", padx=(0, 8))

        self._chk_mirror = tk.Checkbutton(
            row3, text=self.t("lbl_mirror"), variable=self.mirror_var,
            command=self._toggle_mirror,
            font=("Segoe UI", 10), bg=BG_PANEL, fg=FG,
            activebackground=BG_PANEL, activeforeground=FG,
            selectcolor=BG_BTN, cursor="hand2",
        )
        self._chk_mirror.pack(side="left", padx=(0, 8))

        self.cover_var = tk.BooleanVar(value=True)
        self.btn_fit = tk.Button(
            row3, text=self.t("btn_crop"), command=self._toggle_fit,
            bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
            relief="flat", font=("Segoe UI", 9), padx=10, pady=5,
            cursor="hand2", bd=0,
        )
        self.btn_fit.pack(side="left")

        # fila 5: controles de transporte — Play / Pause / Stop
        row4 = tk.Frame(ctrl, bg=BG_PANEL)
        row4.pack(fill="x")

        self.btn_play  = self._btn(row4, self.t("btn_start"),   self._start,               color=ACCENT2)
        self.btn_pause = self._btn(row4, self.t("btn_pause"),   self._pause,               color=BG_BTN)
        self.btn_stop  = self._btn(row4, self.t("btn_stop"),    self._stop,                color=RED)
        self.btn_filters_open  = self._btn(row4, self.t("btn_filters"), self._open_filter_window,  color=BG_BTN)
        self.btn_overlay_open  = self._btn(row4, self.t("btn_overlay"), self._open_overlay_window, color=BG_BTN)
        self.btn_play.pack(side="left", padx=(0, 8))
        self.btn_pause.pack(side="left", padx=(0, 8))
        self.btn_stop.pack(side="left", padx=(0, 20))
        self.btn_filters_open.pack(side="left", padx=(0, 8))
        self.btn_overlay_open.pack(side="left")

        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")

        # ── barra de estado
        status_bar = tk.Frame(self, bg=STATUS_BG, pady=5)
        status_bar.pack(fill="x", padx=0, pady=(8, 0))

        self._led = tk.Canvas(status_bar, width=12, height=12,
                              bg=STATUS_BG, highlightthickness=0)
        self._led.pack(side="left", padx=(10, 6))
        self._led_oval = self._led.create_oval(2, 2, 10, 10, fill="#44445a", outline="")

        self.status_var = tk.StringVar(value=self.t("status_ready"))
        tk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9),
                 bg=STATUS_BG, fg=FG_DIM, anchor="w").pack(side="left", fill="x", expand=True)

        # metadatos del archivo (derecha de la barra de estado)
        self.info_var = tk.StringVar(value="")
        tk.Label(status_bar, textvariable=self.info_var, font=("Consolas", 9),
                 bg=STATUS_BG, fg=ACCENT2, anchor="e").pack(side="right", padx=(0, 12))

        # ── estilos ttk
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TScale", background=BG, troughcolor=BG_BTN,
                        sliderlength=14, sliderrelief="flat")
        style.configure("TCombobox", fieldbackground=BG_BTN,
                        background=BG_BTN, foreground=FG, selectbackground=ACCENT,
                        arrowcolor=FG)
        self.option_add("*TCombobox*Listbox.background", BG_BTN)
        self.option_add("*TCombobox*Listbox.foreground", FG)

    def _param(self, label: str, parent, attr: str, default: str) -> tk.Label:
        """Crea un par Label+Entry y devuelve el Label para poder actualizarlo."""
        lbl = tk.Label(parent, text=label, font=("Segoe UI", 9),
                       bg=BG_PANEL, fg=FG_DIM)
        lbl.pack(side="left", padx=(0, 4))
        var = tk.StringVar(value=default)
        setattr(self, attr, var)
        tk.Entry(parent, textvariable=var, width=6,
                 bg=BG_BTN, fg=FG, insertbackground=FG,
                 relief="flat", font=("Segoe UI", 10)).pack(side="left", padx=(0, 12))
        return lbl

    @staticmethod
    def _btn(parent, text: str, cmd, color: str) -> tk.Button:
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg="#ffffff",
                         activebackground=color, activeforeground="#ffffff",
                         relief="flat", font=("Segoe UI", 10, "bold"),
                         padx=14, pady=6, cursor="hand2", bd=0)

    def _bind_keys(self):
        # ── Atajos de teclado ──────────────────────────────────────────
        # Ctrl+O   → Abrir archivo (imagen / video / GIF)
        # S        → Iniciar transmisión (Play)
        # Espacio  → Pausar / Reanudar transmisión
        # Escape   → Detener transmisión
        # H        → Alternar espejo horizontal (Mirror)
        # F        → Abrir ventana de Filtros
        # O        → Abrir ventana de Overlay
        # +        → Aumentar zoom (+0.1×)
        # -        → Reducir zoom  (-0.1×)
        # ──────────────────────────────────────────────────────────────
        self.bind("<Control-o>", lambda _: self._open_file())
        self.bind("<space>",     lambda _: self._pause())
        self.bind("<Escape>",    lambda _: self._stop())
        self.bind("<s>",         lambda _: self._start())
        self.bind("<S>",         lambda _: self._start())
        self.bind("<h>",         lambda _: (self.mirror_var.set(not self.mirror_var.get()), self._toggle_mirror()))
        self.bind("<H>",         lambda _: (self.mirror_var.set(not self.mirror_var.get()), self._toggle_mirror()))
        self.bind("<f>",         lambda _: self._open_filter_window())
        self.bind("<F>",         lambda _: self._open_filter_window())
        self.bind("<o>",         lambda _: self._open_overlay_window())
        self.bind("<O>",         lambda _: self._open_overlay_window())
        self.bind("<plus>",      lambda _: self._zoom_step(+0.1))
        self.bind("<equal>",     lambda _: self._zoom_step(+0.1))   # Shift no requerido
        self.bind("<minus>",     lambda _: self._zoom_step(-0.1))
        self.bind("<KP_Add>",    lambda _: self._zoom_step(+0.1))   # teclado numérico
        self.bind("<KP_Subtract>",lambda _: self._zoom_step(-0.1))

    def _center_window(self):
        self.update_idletasks()
        w  = self.winfo_width()
        h  = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    def _apply_preset(self, _=None):
        sel = self.preset_var.get()
        internal_key = sel if sel in ASPECT_PRESETS else "__custom__"
        cam_w, cam_h, prev_w, prev_h = ASPECT_PRESETS[internal_key]
        if internal_key != "__custom__":
            self.width_var.set(str(cam_w))
            self.height_var.set(str(cam_h))
        self.preview_w, self.preview_h = prev_w, prev_h
        self.canvas.config(width=prev_w, height=prev_h)
        ratio = cam_w / cam_h if cam_h else 1
        if ratio > 1:
            label = "16:9" if abs(ratio - 16/9) < 0.05 else f"{cam_w}:{cam_h}"
        elif ratio < 1:
            label = "9:16" if abs(ratio - 9/16) < 0.05 else f"{cam_w}:{cam_h}"
        else:
            label = "1:1"
        self.aspect_label.config(text=label)
        self._draw_placeholder()
        self.update_idletasks()

    def _draw_placeholder(self):
        pw, ph = self.preview_w, self.preview_h
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, pw, ph, fill="#111118")
        self.canvas.create_text(pw // 2, ph // 2,
                                text=self.t("no_signal"), fill=FG_DIM,
                                font=("Segoe UI", 20, "bold"))

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------

    def _setup_dnd(self):
        if TKDND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            path = raw[1:-1]
        else:
            path = raw
        self._open_file_path(path)

    # ------------------------------------------------------------------
    # Miniatura
    # ------------------------------------------------------------------

    def _update_thumbnail(self, frame_bgr: "np.ndarray | None"):
        W, H = 64, 36
        if frame_bgr is None:
            blank = np.full((H, W, 3), (46, 42, 42), dtype=np.uint8)
            rgb = blank
        else:
            rgb = bgr_to_rgb(fit_frame(frame_bgr, W, H, cover=True))
        img   = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(img)
        self._thumb_photo = photo
        self._thumb_label.config(image=photo, width=W, height=H)

    # ------------------------------------------------------------------
    # LED de estado
    # ------------------------------------------------------------------

    def _set_led(self, state: str):
        colors = {
            "idle":         "#44445a",
            "active":       ACCENT2,
            "preview_only": "#e8c040",
            "error":        RED,
        }
        self._led.itemconfig(self._led_oval, fill=colors.get(state, "#44445a"))

    def _on_cam_state(self, state: str):
        """Callback del StreamThread cuando se conoce el estado real de la cámara."""
        self.after(0, self._set_led, state)

    # ------------------------------------------------------------------
    # Espejo
    # ------------------------------------------------------------------

    def _toggle_mirror(self):
        # mirror_var ya fue cambiado por el Checkbutton antes de llamar aquí
        new_val = self.mirror_var.get()
        if self._thread and self._thread.is_alive():
            self._thread.mirror = new_val

    # ------------------------------------------------------------------
    # Zoom digital
    # ------------------------------------------------------------------

    def _zoom_step(self, delta: float):
        """Incrementa o decrementa el zoom en `delta`, dentro del rango 1.0–5.0."""
        new_val = round(max(1.0, min(5.0, self._zoom_var.get() + delta)), 1)
        self._zoom_var.set(new_val)

    def _sync_zoom(self, *_):
        if self._thread and self._thread.is_alive():
            self._thread.zoom = self._zoom_var.get()

    # ------------------------------------------------------------------
    # Cursor de pantalla
    # ------------------------------------------------------------------

    def _on_cursor_toggle(self):
        if self._thread and self._thread.is_alive():
            self._thread.show_cursor = self._show_cursor_var.get()

    # ------------------------------------------------------------------
    # Drag del overlay sobre el canvas
    # ------------------------------------------------------------------

    def _get_cam_dims(self) -> tuple:
        try:
            return int(self.width_var.get()), int(self.height_var.get())
        except ValueError:
            return self.preview_w, self.preview_h

    def _canvas_to_frame(self, cx: float, cy: float) -> tuple:
        cam_w, cam_h = self._get_cam_dims()
        return cx / self.preview_w * cam_w, cy / self.preview_h * cam_h

    def _on_canvas_press(self, event):
        if not self._overlay.enabled:
            return
        fx, fy = self._canvas_to_frame(event.x, event.y)
        cam_w, cam_h = self._get_cam_dims()
        rects = get_overlay_rects(self._overlay, cam_w, cam_h)
        MARGIN = 20
        for kind, (rx, ry, rw, rh) in rects.items():
            if (rx - MARGIN <= fx <= rx + rw + MARGIN and
                    ry - MARGIN <= fy <= ry + rh + MARGIN):
                self._drag_overlay_type  = kind
                self._drag_frame_offset  = (fx - rx, fy - ry)
                return

    def _on_canvas_drag(self, event):
        if self._drag_overlay_type is None:
            return
        fx, fy = self._canvas_to_frame(event.x, event.y)
        cam_w, cam_h = self._get_cam_dims()
        ox = max(0.0, min(1.0, (fx - self._drag_frame_offset[0]) / cam_w))
        oy = max(0.0, min(1.0, (fy - self._drag_frame_offset[1]) / cam_h))
        ov = self._overlay
        if self._drag_overlay_type == "text":
            ov.text_pos = "custom"
            ov.text_xy  = (ox, oy)
        else:
            ov.img_pos = "custom"
            ov.img_xy  = (ox, oy)

    def _on_canvas_release(self, event):
        self._drag_overlay_type = None

    # ------------------------------------------------------------------
    # Helpers de overlay
    # ------------------------------------------------------------------

    def _build_pos_grid(self, parent, ov: OverlayConfig, attr: str):
        """Crea una cuadrícula 3×3 de radiobuttons para elegir posición."""
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
        var = tk.StringVar(value=getattr(ov, attr))
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

    def _load_overlay_image(self, path: str):
        """Carga y escala un PNG con canal alfa en `_overlay.img_bgra`."""
        try:
            img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
            if img is None:
                return
            if img.shape[2] == 3:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
            self._overlay.img_path = path
            self._apply_overlay_scale(img)
        except Exception:
            pass

    def _apply_overlay_scale(self, raw_bgra: np.ndarray):
        s = self._overlay.img_scale
        h, w = raw_bgra.shape[:2]
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        self._overlay.img_bgra = cv2.resize(raw_bgra, (nw, nh), interpolation=cv2.INTER_AREA)
        self._overlay._raw_bgra = raw_bgra

    def _reload_overlay_image(self):
        raw = getattr(self._overlay, "_raw_bgra", None)
        if raw is not None:
            self._apply_overlay_scale(raw)

    # ------------------------------------------------------------------
    # Ventana de filtros
    # ------------------------------------------------------------------

    def _open_filter_window(self):
        if self._filter_win and self._filter_win.winfo_exists():
            self._filter_win.destroy(); return

        win = tk.Toplevel(self)
        self._filter_win = win
        win.title(self.t("filters_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        def _slider_row(parent, label_key, var, from_, to_, fmt):
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x", padx=16, pady=4)
            tk.Label(row, text=self.t(label_key), width=13, anchor="w",
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
            if self._thread and self._thread.is_alive():
                self._thread.filter_brightness = float(v)
        def _sync_contrast(v):
            if self._thread and self._thread.is_alive():
                self._thread.filter_contrast = float(v)
        def _sync_saturation(v):
            if self._thread and self._thread.is_alive():
                self._thread.filter_saturation = float(v)
        def _sync_blur(v):
            if self._thread and self._thread.is_alive():
                self._thread.filter_blur = int(float(v))

        tk.Frame(win, bg=BG, height=8).pack()
        _slider_row(win, "lbl_zoom",       self._zoom_var,  1.0, 5.0,  lambda v: f"{v:.1f}×")
        tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=16, pady=(4, 0))
        _slider_row(win, "lbl_brightness", self._bri_var,  -100, 100,  lambda v: f"{v:+.0f}")
        _slider_row(win, "lbl_contrast",   self._con_var,   0.5, 2.0,  lambda v: f"{v:.2f}")
        _slider_row(win, "lbl_saturation", self._sat_var,   0.0, 2.0,  lambda v: f"{v:.2f}")
        _slider_row(win, "lbl_blur",        self._blur_var,  0,   10,   lambda v: f"{int(v)}")

        self._zoom_var.trace_add("write", lambda *_: self._sync_zoom())
        self._bri_var.trace_add("write",  lambda *_: _sync_brightness(self._bri_var.get()))
        self._con_var.trace_add("write",  lambda *_: _sync_contrast(self._con_var.get()))
        self._sat_var.trace_add("write",  lambda *_: _sync_saturation(self._sat_var.get()))
        self._blur_var.trace_add("write", lambda *_: _sync_blur(self._blur_var.get()))

        def _reset():
            self._zoom_var.set(1.0)
            self._bri_var.set(0.0)
            self._con_var.set(1.0)
            self._sat_var.set(1.0)
            self._blur_var.set(0.0)

        tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=16, pady=(10, 0))
        tk.Button(win, text=self.t("btn_reset_filters"), command=_reset,
                  bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
                  relief="flat", font=("Segoe UI", 9), padx=12, pady=5,
                  cursor="hand2", bd=0).pack(pady=8)

        win.update_idletasks()
        x = self.winfo_x() + self.winfo_width() + 8
        y = self.winfo_y()
        win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Ventana de overlay
    # ------------------------------------------------------------------

    def _open_overlay_window(self):
        if self._overlay_win and self._overlay_win.winfo_exists():
            self._overlay_win.destroy(); return

        ov = self._overlay
        win = tk.Toplevel(self)
        self._overlay_win = win
        win.title(self.t("overlay_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        def _lbl(parent, key):
            tk.Label(parent, text=self.t(key), width=14, anchor="w",
                     font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left")

        def _section(title):
            tk.Label(win, text=f"── {self.t(title)} ──",
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
        tk.Checkbutton(win, text=self.t("lbl_ovl_enable"), variable=enable_var,
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
        def _upd_text(*_): ov.text = text_var.get()
        text_var.trace_add("write", _upd_text)

        r = _row(); _lbl(r, "lbl_ovl_size")
        size_var = tk.DoubleVar(value=ov.font_scale)
        size_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
        size_lbl.pack(side="right")
        def _upd_size(v):
            ov.font_scale = float(v); size_lbl.config(text=f"{float(v):.1f}")
        size_lbl.config(text=f"{ov.font_scale:.1f}")
        ttk.Scale(r, from_=0.4, to=4.0, orient="horizontal",
                  variable=size_var, command=_upd_size).pack(side="left", fill="x", expand=True, padx=(8,8))

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
                r2, g2, b2 = int(hex_col[0:2],16), int(hex_col[2:4],16), int(hex_col[4:6],16)
                ov.text_color_bgr = (b2, g2, r2)
        tk.Button(r, text=self.t("btn_pick_color"), command=_pick_color,
                  bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
                  relief="flat", font=("Segoe UI", 9), padx=8, pady=2,
                  cursor="hand2", bd=0).pack(side="left")

        r = _row(); _lbl(r, "lbl_ovl_text_pos")
        self._build_pos_grid(r, ov, "text_pos")

        r = _row(); _lbl(r, "lbl_ovl_text_bg")
        bg_var = tk.DoubleVar(value=ov.text_bg_alpha)
        bg_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
        bg_lbl.pack(side="right")
        def _upd_bg(v):
            ov.text_bg_alpha = float(v); bg_lbl.config(text=f"{float(v):.0%}")
        bg_lbl.config(text=f"{ov.text_bg_alpha:.0%}")
        ttk.Scale(r, from_=0.0, to=1.0, orient="horizontal",
                  variable=bg_var, command=_upd_bg).pack(side="left", fill="x", expand=True, padx=(8,8))

        # ══════════════════ IMAGEN ══════════════════
        tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=16, pady=(8, 0))
        _section("ovl_section_img")

        r = _row(); _lbl(r, "lbl_ovl_img_file")
        img_path_var = tk.StringVar(value=ov.img_path)
        tk.Entry(r, textvariable=img_path_var, width=20,
                 bg=BG_BTN, fg=FG, insertbackground=FG,
                 relief="flat", font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True, padx=(0,4))
        def _browse_img():
            p = filedialog.askopenfilename(
                parent=win, title=self.t("dlg_pick_img"),
                filetypes=[("PNG", "*.png"), ("All", "*.*")])
            if p:
                img_path_var.set(p)
                self._load_overlay_image(p)
        tk.Button(r, text=self.t("btn_browse"), command=_browse_img,
                  bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
                  relief="flat", font=("Segoe UI", 9), padx=6, pady=2,
                  cursor="hand2", bd=0).pack(side="left")

        r = _row(); _lbl(r, "lbl_ovl_img_pos")
        self._build_pos_grid(r, ov, "img_pos")

        r = _row(); _lbl(r, "lbl_ovl_img_scale")
        sc_var = tk.DoubleVar(value=ov.img_scale)
        sc_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
        sc_lbl.pack(side="right")
        def _upd_scale(v):
            ov.img_scale = float(v)
            sc_lbl.config(text=f"{float(v):.0%}")
            self._reload_overlay_image()
        sc_lbl.config(text=f"{ov.img_scale:.0%}")
        ttk.Scale(r, from_=0.05, to=1.0, orient="horizontal",
                  variable=sc_var, command=_upd_scale).pack(side="left", fill="x", expand=True, padx=(8,8))

        r = _row(); _lbl(r, "lbl_ovl_img_alpha")
        al_var = tk.DoubleVar(value=ov.img_alpha)
        al_lbl = tk.Label(r, width=4, anchor="e", font=("Consolas", 9), bg=BG, fg=ACCENT2)
        al_lbl.pack(side="right")
        def _upd_alpha(v):
            ov.img_alpha = float(v); al_lbl.config(text=f"{float(v):.0%}")
        al_lbl.config(text=f"{ov.img_alpha:.0%}")
        ttk.Scale(r, from_=0.0, to=1.0, orient="horizontal",
                  variable=al_var, command=_upd_alpha).pack(side="left", fill="x", expand=True, padx=(8,8))

        tk.Frame(win, bg=BG, height=10).pack()
        win.update_idletasks()
        x = self.winfo_x() + self.winfo_width() + 8
        y = self.winfo_y() + 220
        win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Diálogo About
    # ------------------------------------------------------------------

    def _show_about(self):
        if self._about_win and self._about_win.winfo_exists():
            self._about_win.destroy(); return

        REPO_URL = "https://github.com/nullfuzz-pentest/webcam_virtual/"

        win = tk.Toplevel(self)
        self._about_win = win
        win.title(self.t("about_title"))
        win.configure(bg=BG)
        win.resizable(False, False)

        hdr = tk.Frame(win, bg=ACCENT, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="Virtual Webcam", font=("Segoe UI", 18, "bold"),
                 bg=ACCENT, fg="#ffffff").pack()
        tk.Label(hdr, text=f"v1.1  ·  {self.t('title_sub')}", font=("Segoe UI", 11),
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

        _row(self.t("about_creator"), "nullfuzz")
        _row(self.t("about_license"), "MIT")

        repo_row = tk.Frame(body, bg=BG)
        repo_row.pack(fill="x", pady=4)
        tk.Label(repo_row, text=self.t("about_repo"), font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=FG_DIM, width=12, anchor="e").pack(side="left", padx=(0, 10))
        link = tk.Label(repo_row, text=REPO_URL, font=("Segoe UI", 10, "underline"),
                        bg=BG, fg=ACCENT2, cursor="hand2", anchor="w")
        link.pack(side="left")
        link.bind("<Button-1>", lambda _: webbrowser.open(REPO_URL))

        tk.Frame(win, bg=BG_BTN, height=1).pack(fill="x", padx=20)
        tk.Button(
            win, text=self.t("about_close"), command=win.destroy,
            bg=ACCENT, fg="#ffffff", activebackground=ACCENT, activeforeground="#ffffff",
            relief="flat", font=("Segoe UI", 10, "bold"),
            padx=24, pady=7, cursor="hand2", bd=0,
        ).pack(pady=16)

        win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - win.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{x}+{y}")

    # ------------------------------------------------------------------
    # Captura de pantalla
    # ------------------------------------------------------------------

    def _refresh_monitor_list(self):
        """Rellena el combobox de monitores consultando mss."""
        values = [self.t("monitor_all")]
        if MSS_AVAILABLE:
            import importlib
            _mss = importlib.import_module("mss")
            with _mss.mss() as sct:
                for i, mon in enumerate(sct.monitors[1:], start=1):
                    w, h = mon["width"], mon["height"]
                    values.append(f"Monitor {i}  ({w}×{h})")
        self._monitor_cb["values"] = values
        if self._monitor_var.get() not in values:
            self._monitor_var.set(values[0])

    def _on_monitor_change(self, _=None):
        sel = self._monitor_var.get()
        values = self._monitor_cb["values"]
        idx = list(values).index(sel) if sel in values else 0
        self._screen_monitor_idx = idx
        if self._use_screen:
            if idx == 0:
                self.source_var.set(self.t("screen_label_all"))
            else:
                self.source_var.set(self.t("screen_label", n=idx))

    def _select_screen(self):
        """Activa el modo captura de pantalla."""
        self._use_screen = True
        self._file_loaded = True
        self._refresh_monitor_list()
        self._monitor_cb.config(state="readonly")
        self._monitor_var.set(self._monitor_cb["values"][0])
        self._screen_monitor_idx = 0
        self.source_var.set(self.t("screen_label_all"))
        self.info_var.set("")
        self._update_thumbnail(None)
        self._set_status(self.t("status_screen"))
        self._draw_placeholder()

    # ------------------------------------------------------------------
    # Metadatos del archivo fuente
    # ------------------------------------------------------------------

    def _load_file_info(self, src: Path, stype: str, first_frame: np.ndarray | None,
                        video_meta: dict | None = None):
        try:
            size_mb = src.stat().st_size / 1_048_576
        except OSError:
            size_mb = 0.0
        ext = src.suffix.upper().lstrip(".")

        if stype == "image" and first_frame is not None:
            h, w = first_frame.shape[:2]
            info = f"{w} × {h}  ·  {ext}  ·  {size_mb:.1f} MB"
        elif stype == "video":
            if video_meta is None:
                cap      = cv2.VideoCapture(str(src))
                video_meta = {
                    "vw"      : int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    "vh"      : int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    "src_fps" : cap.get(cv2.CAP_PROP_FPS),
                    "n_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                    "fourcc"  : int(cap.get(cv2.CAP_PROP_FOURCC)),
                }
                cap.release()
            vw, vh    = video_meta["vw"], video_meta["vh"]
            src_fps   = video_meta["src_fps"]
            n_frames  = video_meta["n_frames"]
            fourcc    = video_meta["fourcc"]
            codec   = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip() or ext
            dur_s   = n_frames / src_fps if src_fps > 0 else 0
            dur     = f"{int(dur_s) // 60}:{int(dur_s) % 60:02d}"
            fps_str = f"{src_fps:.3f}".rstrip("0").rstrip(".")
            info = (f"{vw} × {vh}  ·  {fps_str} fps  ·  {dur}  ·  "
                    f"{n_frames} frames  ·  {codec}  ·  {size_mb:.1f} MB")
        else:
            info = ""

        self.info_var.set(info)

    # ------------------------------------------------------------------
    # Apertura de archivo
    # ------------------------------------------------------------------

    def _open_file(self):
        img_exts = "*.jpg *.jpeg *.png *.bmp *.webp *.tiff *.tif *.gif"
        vid_exts = "*.mp4 *.avi *.mov *.mkv *.webm *.flv *.wmv"
        filetypes = [
            (self.t("ft_all_supported"), f"{img_exts} {vid_exts}"),
            (self.t("ft_images"),        img_exts),
            (self.t("ft_videos"),        vid_exts),
            (self.t("ft_all"),           "*.*"),
        ]
        path = filedialog.askopenfilename(title=self.t("dlg_open_title"),
                                          filetypes=filetypes)
        if path:
            self._open_file_path(path)

    def _open_file_path(self, path: str):
        """Carga un archivo por ruta (desde diálogo o drag & drop)."""
        self.source_var.set(path)
        self._file_loaded = True
        self._use_screen  = False
        self._monitor_cb.config(state="disabled")
        src   = Path(path)
        stype = detect_source_type(src)
        pw, ph = self.preview_w, self.preview_h
        first_frame: "np.ndarray | None" = None
        video_meta:  "dict | None"       = None
        if stype == "image":
            frame = cv2.imread(str(src))
            if frame is not None:
                first_frame = frame
                self._show_frame(bgr_to_rgb(fit_frame(frame, pw, ph, self.cover_var.get())))
        elif stype == "video":
            cap = cv2.VideoCapture(str(src))
            video_meta = {
                "vw"      : int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                "vh"      : int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                "src_fps" : cap.get(cv2.CAP_PROP_FPS),
                "n_frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                "fourcc"  : int(cap.get(cv2.CAP_PROP_FOURCC)),
            }
            ret, frame = cap.read()
            cap.release()
            if ret:
                first_frame = frame
                self._show_frame(bgr_to_rgb(fit_frame(frame, pw, ph, self.cover_var.get())))
        elif stype == "gif":
            try:
                from PIL import Image as _PilImg
                gif = _PilImg.open(str(src))
                frame_rgb = np.array(gif.convert("RGB"))
                first_frame = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                self._show_frame(bgr_to_rgb(fit_frame(first_frame, pw, ph, self.cover_var.get())))
            except Exception:
                pass
        self._update_thumbnail(first_frame)
        self._load_file_info(src, stype, first_frame, video_meta)
        self._set_status(self.t("status_loaded", name=src.name))

    # ------------------------------------------------------------------
    # Control de reproducción
    # ------------------------------------------------------------------

    def _start(self):
        if self._thread and self._thread.is_alive():
            return

        if not self._file_loaded:
            messagebox.showwarning(self.t("warn_no_file_title"), self.t("warn_no_file_msg"))
            return

        if self._use_screen:
            source = None
            stype  = "screen"
        else:
            source = Path(self.source_var.get())
            if not source.exists():
                messagebox.showerror(self.t("err_not_found_title"),
                                     self.t("err_not_found_msg", path=source))
                return
            stype = detect_source_type(source)
            if stype == "unknown":
                messagebox.showerror(self.t("err_fmt_title"), self.t("err_fmt_msg"))
                return

        try:
            w   = int(self.width_var.get())
            h   = int(self.height_var.get())
            fps = float(self.fps_var.get())
        except ValueError:
            messagebox.showerror(self.t("err_params_title"), self.t("err_params_msg"))
            return

        cam_kwargs: dict = dict(width=w, height=h, fps=fps, fmt=PixelFormat.RGB) \
                           if PYVIRTUALCAM_AVAILABLE else {}
        backend = self.backend_var.get()
        if PYVIRTUALCAM_AVAILABLE and backend != "auto":
            cam_kwargs["backend"] = backend

        self._last_preview_time = 0.0
        self._thread = StreamThread(
            source=source, source_type=stype,
            cam_width=w, cam_height=h, fps=fps,
            loop=self.loop_var.get(),
            cover=self.cover_var.get(),
            on_frame=self._on_frame,
            on_status=self._set_status,
            on_stopped=self._on_stopped,
            cam_kwargs=cam_kwargs,
            msg_cam_active=self.t("status_cam_active"),
            msg_preview_only=self.t("status_preview_only"),
            monitor_idx=self._screen_monitor_idx,
            mirror=self.mirror_var.get(),
            on_cam_state=self._on_cam_state,
        )
        self._thread.filter_brightness = self._bri_var.get()
        self._thread.filter_contrast   = self._con_var.get()
        self._thread.filter_saturation = self._sat_var.get()
        self._thread.filter_blur       = int(self._blur_var.get())
        self._thread.zoom              = self._zoom_var.get()
        self._thread.overlay           = self._overlay
        self._thread.show_cursor       = self._show_cursor_var.get()
        self._set_led("active")
        self._thread.start()
        self._poll_fps()

        self.btn_play.config(state="disabled")
        self.btn_pause.config(state="normal")
        self.btn_stop.config(state="normal")
        self._set_status(self.t("status_streaming"))

    def _toggle_fit(self):
        cover = not self.cover_var.get()
        self.cover_var.set(cover)
        if cover:
            self.btn_fit.config(text=self.t("btn_crop"), bg=BG_BTN)
        else:
            self.btn_fit.config(text=self.t("btn_letterbox"), bg=ACCENT)
        if self._thread and self._thread.is_alive():
            self._thread.cover = cover

    def _pause(self):
        if not (self._thread and self._thread.is_alive()):
            return
        if self._thread.is_paused:
            self._thread.resume()
            self.btn_pause.config(text=self.t("btn_pause"))
            self._set_status(self.t("status_streaming"))
        else:
            self._thread.pause()
            self.btn_pause.config(text=self.t("btn_resume"))
            self._set_status(self.t("status_paused"))

    def _stop(self):
        if self._thread:
            self._thread.stop()

    # ------------------------------------------------------------------
    # Callbacks del hilo
    # ------------------------------------------------------------------

    def _on_frame(self, rgb: np.ndarray):
        now = time.monotonic()
        if now - self._last_preview_time >= PREVIEW_MIN_INTERVAL:
            self._last_preview_time = now
            self.after(0, self._show_frame, rgb)

        if self._thread and self._thread.total_frames > 0 and not self._seek_dragging:
            prog    = self._thread.current_frame / self._thread.total_frames
            elapsed = self._thread.current_frame / max(self._thread.src_fps, 1)
            total   = self._thread.total_frames  / max(self._thread.src_fps, 1)
            self.after(0, self._update_progress, prog, elapsed, total)

    def _show_frame(self, rgb: np.ndarray):
        h, w = rgb.shape[:2]
        if w != self.preview_w or h != self.preview_h:
            img = Image.fromarray(rgb).resize((self.preview_w, self.preview_h), Image.LANCZOS)
        else:
            img = Image.fromarray(rgb)
        photo = ImageTk.PhotoImage(img)
        self._last_photo = photo
        self.canvas.create_image(0, 0, anchor="nw", image=photo)

    def _update_progress(self, prog: float, elapsed: float, total: float):
        self.progress_var.set(prog)
        def fmt(s: float) -> str:
            return f"{int(s) // 60}:{int(s) % 60:02d}"
        self.time_label.config(text=f"{fmt(elapsed)} / {fmt(total)}")

    def _poll_fps(self):
        if self._thread and self._thread.is_alive():
            fps = self._thread.measured_fps
            if fps > 0:
                self.fps_label.config(text=f"{fps:.1f} fps")
            self.after(2000, self._poll_fps)
        else:
            self.fps_label.config(text="")

    def _set_status(self, msg: str):
        self.after(0, self.status_var.set, msg)

    def _on_stopped(self, error: str | None):
        def _ui():
            self._set_led("error" if error else "idle")
            self.btn_play.config(state="normal")
            self.btn_pause.config(state="disabled", text=self.t("btn_pause"))
            self.btn_stop.config(state="disabled")
            self.fps_label.config(text="")
            self.progress_var.set(0)
            self.time_label.config(text="0:00 / 0:00")
            if error:
                self._set_status(self.t("status_error", error=error))
                messagebox.showerror(
                    self.t("err_cam_title"),
                    error + "\n\n" + self.t("err_cam_hints"),
                )
            else:
                self._set_status(self.t("status_stopped"))
        self.after(0, _ui)

    # ------------------------------------------------------------------
    # Seek
    # ------------------------------------------------------------------

    def _on_seek_click(self, event):
        """Salta directamente a la posición clickeada en la barra."""
        w = self.progress.winfo_width()
        if w <= 0:
            return
        val = max(0.0, min(1.0, event.x / w))
        self._seek_dragging = True
        self.progress_var.set(val)
        # evita que ttk.Scale procese el clic con su lógica de pasos
        return "break"

    def _on_seek_drag(self, _=None):
        self._seek_dragging = True

    def _on_seek_release(self, _=None):
        self._seek_dragging = False
        if self._thread and self._thread.total_frames > 0:
            target = int(self.progress_var.get() * self._thread.total_frames)
            self._thread.seek(target)

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def _on_close(self):
        self._stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self.destroy()