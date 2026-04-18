"""
app.py
------
Clase App: ventana principal de la aplicación (GUI Tkinter).
"""

import locale
import json
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
    MSS_AVAILABLE, PSUTIL_AVAILABLE, ASPECT_PRESETS, _PRESET_NUMERIC_KEYS,
    PREVIEW_W, PREVIEW_H, PREVIEW_MIN_INTERVAL,
    BG, BG_PANEL, BG_BTN, ACCENT, ACCENT2, FG, FG_DIM, RED, STATUS_BG,
    THEMES, THEME_KEYS,
)
from translations import TRANSLATIONS, LANG_ORDER
from image_utils import detect_source_type, fit_frame, bgr_to_rgb
from overlay import OverlayConfig, get_overlay_rects
from stream_thread import StreamThread
from ui_filters  import open_filter_window
from ui_overlay  import open_overlay_window
from ui_about    import open_about

_PREFS_PATH = Path(__file__).parent / "prefs.json"


class _RegionPicker:
    """Ventana fullscreen para seleccionar una región de pantalla arrastrando."""

    def __init__(self, parent: tk.Tk, monitor: dict, hint: str):
        self.result: "dict | None" = None
        ox = monitor["left"]
        oy = monitor["top"]
        sw = monitor["width"]
        sh = monitor["height"]
        self._ox = ox
        self._oy = oy
        self._x0 = self._y0 = 0

        # captura el fondo del monitor
        try:
            import mss as _mss
            with _mss.mss() as sct:
                raw = sct.grab(monitor)
                bg_img = Image.frombytes("RGB", (sw, sh), bytes(raw.rgb))
        except Exception:
            try:
                from PIL import ImageGrab
                bg_img = ImageGrab.grab(bbox=(ox, oy, ox + sw, oy + sh))
            except Exception:
                bg_img = Image.new("RGB", (sw, sh), "#1e1e2e")

        self._win = tk.Toplevel(parent)
        self._win.overrideredirect(True)
        self._win.geometry(f"{sw}x{sh}+{ox}+{oy}")
        self._win.attributes("-topmost", True)
        self._win.lift()
        self._win.focus_force()

        self._bg_photo = ImageTk.PhotoImage(bg_img)

        self._canvas = tk.Canvas(self._win, cursor="crosshair",
                                  highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)

        # fondo + overlay semitransparente
        self._canvas.create_image(0, 0, anchor="nw", image=self._bg_photo)
        self._canvas.create_rectangle(0, 0, sw, sh,
                                       fill="black", stipple="gray50", outline="")
        # rectángulo de selección
        self._rect = self._canvas.create_rectangle(0, 0, 1, 1,
                                                    outline="#00ff00", width=2, fill="")
        # etiqueta de dimensiones
        self._size_lbl = self._canvas.create_text(sw // 2, sh - 24, text="",
                                                   fill="white",
                                                   font=("Segoe UI", 11, "bold"))
        # instrucciones
        self._canvas.create_text(sw // 2, 22, text=hint,
                                  fill="white", font=("Segoe UI", 11, "bold"))

        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._win.bind("<Escape>",             self._on_cancel)

        self._win.grab_set()
        parent.wait_window(self._win)

    def _on_press(self, e: tk.Event):
        self._x0, self._y0 = e.x, e.y
        self._canvas.coords(self._rect, e.x, e.y, e.x, e.y)

    def _on_drag(self, e: tk.Event):
        x1, y1 = min(self._x0, e.x), min(self._y0, e.y)
        x2, y2 = max(self._x0, e.x), max(self._y0, e.y)
        self._canvas.coords(self._rect, x1, y1, x2, y2)
        self._canvas.itemconfig(self._size_lbl, text=f"{x2 - x1} × {y2 - y1}")

    def _on_release(self, e: tk.Event):
        x1 = min(self._x0, e.x) + self._ox
        y1 = min(self._y0, e.y) + self._oy
        x2 = max(self._x0, e.x) + self._ox
        y2 = max(self._y0, e.y) + self._oy
        w, h = x2 - x1, y2 - y1
        if w > 10 and h > 10:
            self.result = {"left": x1, "top": y1, "width": w, "height": h}
        self._win.destroy()

    def _on_cancel(self, _=None):
        self._win.destroy()


class App(_AppBase):
    def __init__(self):
        super().__init__()
        self.title("Virtual Webcam v1.7")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(640, 480)
        self.after(0, self._set_camera_icon)

        _prefs               = self._load_prefs()
        self._lang           = _prefs.get("lang", self._detect_lang())
        _saved_theme         = _prefs.get("theme", "dark")
        self._theme_name     = "dark"   # _build_ui usa colores dark del módulo; se corrige abajo
        self._thread: StreamThread | None = None
        self._last_photo     = None
        self._seek_dragging  = False
        self._file_loaded    = False
        self._use_screen     = False
        self._screen_monitor_idx = 0
        self._screen_region: "dict | None" = None
        self.mirror_var      = tk.BooleanVar(value=False)
        self._rotation_var   = tk.IntVar(value=0)
        self._thumb_photo    = None
        # filtros — DoubleVars sincronizadas con el hilo
        self._bri_var  = tk.DoubleVar(value=0.0)
        self._con_var  = tk.DoubleVar(value=1.0)
        self._sat_var  = tk.DoubleVar(value=1.0)
        self._blur_var = tk.DoubleVar(value=0.0)
        self._zoom_var = tk.DoubleVar(value=1.0)
        # anchor del zoom (coordenadas normalizadas del puntero sobre el canvas)
        self._zoom_cx: float = 0.5
        self._zoom_cy: float = 0.5
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
        # debounce para auto-guardado de preferencias
        self._save_after_id: "str | None" = None
        # id del item de canvas que muestra los frames del stream
        self._canvas_img_id: "int | None" = None
        # frame más reciente pendiente de renderizar (drop de frames obsoletos)
        self._pending_frame: "np.ndarray | None" = None
        self._frame_scheduled: bool = False

        self._build_ui()
        # aplicar preferencias guardadas que requieren widgets ya creados
        if _prefs:
            if _saved_theme != "dark":
                self._apply_theme(_saved_theme)
                _td = {"dark": "Dark", "blue": "Blue", "white": "White", "halloween": "Halloween"}
                self._theme_var.set(_td.get(_saved_theme, "Dark"))
            preset = _prefs.get("preset", "")
            if preset in _PRESET_NUMERIC_KEYS:
                self.preset_var.set(preset)
                self._apply_preset()
            if _prefs.get("preset") not in _PRESET_NUMERIC_KEYS:
                if "width" in _prefs:
                    self.width_var.set(_prefs["width"])
                if "height" in _prefs:
                    self.height_var.set(_prefs["height"])
            if "fps" in _prefs:
                self.fps_var.set(_prefs["fps"])
            # filtros y transforms
            if "brightness" in _prefs:
                self._bri_var.set(float(_prefs["brightness"]))
            if "contrast" in _prefs:
                self._con_var.set(float(_prefs["contrast"]))
            if "saturation" in _prefs:
                self._sat_var.set(float(_prefs["saturation"]))
            if "blur" in _prefs:
                self._blur_var.set(float(_prefs["blur"]))
            if "zoom" in _prefs:
                v = float(_prefs["zoom"])
                self._zoom_var.set(v)
                self._zoom_val_lbl.config(text=f"{v:.1f}×")
            if "rotation" in _prefs:
                deg = int(_prefs["rotation"])
                self._rotation_var.set(deg)
                self._rotation_cb.current(deg // 90)
            if "mirror" in _prefs:
                self.mirror_var.set(bool(_prefs["mirror"]))
            if "cover" in _prefs:
                self.cover_var.set(bool(_prefs["cover"]))
                self._refresh_fit_btn()
        # auto-guardado de preferencias al cambiar filtros / zoom
        for _var in (self._bri_var, self._con_var, self._sat_var,
                     self._blur_var, self._zoom_var):
            _var.trace_add("write", lambda *_: self._schedule_save_prefs())
        self.mirror_var.trace_add("write",    lambda *_: self._schedule_save_prefs())
        self.cover_var.trace_add("write",     lambda *_: self._schedule_save_prefs())
        # sync filtros → hilo (aquí para no acumular al reabrir ventana de filtros)
        self._bri_var.trace_add("write",  lambda *_: self._sync_filter("brightness", self._bri_var.get()))
        self._con_var.trace_add("write",  lambda *_: self._sync_filter("contrast",   self._con_var.get()))
        self._sat_var.trace_add("write",  lambda *_: self._sync_filter("saturation", self._sat_var.get()))
        self._blur_var.trace_add("write", lambda *_: self._sync_filter("blur",       self._blur_var.get()))
        self._rotation_var.trace_add("write", lambda *_: self._schedule_save_prefs())
        self.width_var.trace_add("write",     lambda *_: self._schedule_save_prefs())
        self.height_var.trace_add("write",    lambda *_: self._schedule_save_prefs())
        self.fps_var.trace_add("write",       lambda *_: self._schedule_save_prefs())
        self.preset_var.trace_add("write",    lambda *_: self._schedule_save_prefs())

        self._bind_keys()
        self._setup_dnd()
        self._center_window()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if PSUTIL_AVAILABLE:
            _constants_mod._psutil.cpu_percent(interval=None)  # primera llamada descartada (siempre 0)
        self.after(2000, self._poll_cpu)

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

    # ------------------------------------------------------------------
    # Preferencias persistentes
    # ------------------------------------------------------------------

    def _load_prefs(self) -> dict:
        try:
            return json.loads(_PREFS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _schedule_save_prefs(self):
        """Cancela el guardado pendiente y programa uno nuevo tras 2 segundos (debounce)."""
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
        self._save_after_id = self.after(2000, self._save_prefs)

    def _save_prefs(self):
        self._save_after_id = None
        prefs = {
            "lang":       self._lang,
            "theme":      self._theme_name,
            "preset":     self.preset_var.get(),
            "width":      self.width_var.get(),
            "height":     self.height_var.get(),
            "fps":        self.fps_var.get(),
            "brightness": self._bri_var.get(),
            "contrast":   self._con_var.get(),
            "saturation": self._sat_var.get(),
            "blur":       self._blur_var.get(),
            "zoom":       self._zoom_var.get(),
            "rotation":   self._rotation_var.get(),
            "mirror":     self.mirror_var.get(),
            "cover":      self.cover_var.get(),
        }
        try:
            _PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        except Exception:
            pass

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
        key = "btn_clear_region" if self._screen_region else "btn_pick_region"
        self._btn_pick_region.config(text=self.t(key))
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
        self._lbl_rotation.config(text=self.t("lbl_rotation"))
        self._lbl_zoom_main.config(text=self.t("lbl_zoom"))
        self._refresh_fit_btn()
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
        self._schedule_save_prefs()

    def _on_theme_change(self, _=None):
        display_to_key = {"Dark": "dark", "Blue": "blue", "White": "white", "Halloween": "halloween"}
        name = display_to_key.get(self._theme_var.get(), "dark")
        if name != self._theme_name:
            self._apply_theme(name)
            self._schedule_save_prefs()

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

        # decoración halloween
        if name == "halloween":
            self._lbl_halloween.config(bg=theme["BG"])
            self._lbl_halloween.pack(side="left", padx=(6, 0))
            self.title("🎃 Virtual Webcam v1.7 💀")
        else:
            self._lbl_halloween.pack_forget()
            self.title("Virtual Webcam v1.7")

        # canvas items (texto/bordes del placeholder) no son widgets — redibujar
        if not (self._thread and self._thread.is_alive()):
            self._draw_placeholder()

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
    # Tooltips
    # ------------------------------------------------------------------

    def _bind_tooltip(self, widget, key: str):
        """Muestra la traducción de `key` en el label de tooltip al entrar al widget."""
        widget.bind("<Enter>", lambda _: self._tooltip_var.set(self.t(key)))
        widget.bind("<Leave>", lambda _: self._tooltip_var.set(""))

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
        # decoración halloween (oculta por defecto)
        self._lbl_halloween = tk.Label(title_bar, text="  🎃 👻 💀",
                                       font=("Segoe UI", 15), bg=BG, fg="#ff6a00")
        # no se hace pack aquí; se muestra/oculta en _apply_theme

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
        _theme_display = {"dark": "Dark", "blue": "Blue", "white": "White", "halloween": "Halloween"}
        self._theme_var = tk.StringVar(value=_theme_display[self._theme_name])
        theme_cb = ttk.Combobox(
            lang_frame, textvariable=self._theme_var, width=10, state="readonly",
            values=["Dark", "Blue", "White", "Halloween"],
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

        # ── barra de estado (se empaqueta primero con side="bottom" para quedar siempre abajo)
        status_bar = tk.Frame(self, bg=STATUS_BG, pady=5)
        status_bar.pack(fill="x", side="bottom")

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

        # CPU + RAM usage
        self._mem_var = tk.StringVar(value="")
        tk.Label(status_bar, textvariable=self._mem_var, font=("Consolas", 9),
                 bg=STATUS_BG, fg=FG_DIM, anchor="e", width=8).pack(side="right", padx=(0, 4))
        self._cpu_var = tk.StringVar(value="")
        tk.Label(status_bar, textvariable=self._cpu_var, font=("Consolas", 9),
                 bg=STATUS_BG, fg=FG_DIM, anchor="e", width=8).pack(side="right", padx=(0, 4))

        # tooltip
        self._tooltip_var = tk.StringVar(value="")
        self._tooltip_lbl = tk.Label(status_bar, textvariable=self._tooltip_var,
                                     font=("Segoe UI", 9, "italic"),
                                     bg=STATUS_BG, fg=ACCENT, anchor="e",
                                     width=38)
        self._tooltip_lbl.pack(side="right", padx=(0, 16))

        # ── preview
        self.preview_outer = tk.Frame(self, bg="#000000", padx=2, pady=2)
        self.preview_outer.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        self.canvas = tk.Canvas(self.preview_outer, width=self.preview_w, height=self.preview_h,
                                bg="#000000", highlightthickness=0, cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>",        self._on_canvas_press)
        self.canvas.bind("<B1-Motion>",       self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Motion>",          self._on_canvas_motion)
        self.canvas.bind("<Leave>",           self._on_canvas_leave)
        self.canvas.bind("<Configure>",       self._on_canvas_resize)
        self._draw_placeholder()

        # ── panel de controles
        ctrl = tk.Frame(self, bg=BG_PANEL, padx=16, pady=12)
        ctrl.pack(fill="x", side="bottom", padx=16, pady=(0, 4))

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
        self.btn_screen = self._btn(row1, self.t("btn_screen"), self._select_screen, color=BG_BTN, fg=FG)
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
        self._btn_pick_region = self._btn(
            row1c, self.t("btn_pick_region"), self._pick_screen_region,
            color=BG_BTN, fg=FG,
        )
        self._btn_pick_region.pack(side="left", padx=(8, 0))
        self._btn_pick_region.config(state="disabled")

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

        self._lbl_rotation = tk.Label(row3, text=self.t("lbl_rotation"),
                                      font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM)
        self._lbl_rotation.pack(side="left", padx=(8, 4))
        self._rotation_str_var = tk.StringVar(value="0°")
        self._rotation_cb = ttk.Combobox(
            row3, textvariable=self._rotation_str_var,
            values=["0°", "90°", "180°", "270°"],
            width=5, state="readonly",
        )
        self._rotation_cb.current(0)
        self._rotation_cb.pack(side="left", padx=(0, 8))
        self._rotation_cb.bind("<<ComboboxSelected>>", self._on_rotation_change)

        self.cover_var = tk.BooleanVar(value=True)
        self.btn_fit = tk.Button(
            row3, text=self.t("btn_crop"), command=self._toggle_fit,
            bg=BG_BTN, fg=FG, activebackground=ACCENT, activeforeground="#fff",
            relief="flat", font=("Segoe UI", 9), padx=10, pady=5,
            cursor="hand2", bd=0,
        )
        self.btn_fit.pack(side="left")

        # zoom — inline en row3, a la derecha de recortar
        self._lbl_zoom_main = tk.Label(row3, text=self.t("lbl_zoom"),
                                       font=("Segoe UI", 9), bg=BG_PANEL, fg=FG_DIM)
        self._lbl_zoom_main.pack(side="left", padx=(12, 4))
        self._zoom_val_lbl = tk.Label(row3, text="1.0×", width=4, anchor="e",
                                      font=("Consolas", 9), bg=BG_PANEL, fg=ACCENT2)
        self._zoom_val_lbl.pack(side="left")
        ttk.Scale(row3, from_=1.0, to=5.0, orient="horizontal",
                  variable=self._zoom_var, length=150,
                  command=lambda v: self._zoom_val_lbl.config(text=f"{float(v):.1f}×")
                  ).pack(side="left", padx=(4, 0))
        self._zoom_var.trace_add("write", lambda *_: self._sync_zoom())

        # fila 5: controles de transporte — Play / Pause / Stop
        row4 = tk.Frame(ctrl, bg=BG_PANEL)
        row4.pack(fill="x")

        self.btn_play  = self._btn(row4, self.t("btn_start"),   self._start,               color=ACCENT2)
        self.btn_pause = self._btn(row4, self.t("btn_pause"),   self._pause,               color=BG_BTN, fg=FG)
        self.btn_stop  = self._btn(row4, self.t("btn_stop"),    self._stop,                color=RED)
        self.btn_filters_open  = self._btn(row4, self.t("btn_filters"), self._open_filter_window,  color=BG_BTN, fg=FG)
        self.btn_overlay_open  = self._btn(row4, self.t("btn_overlay"), self._open_overlay_window, color=BG_BTN, fg=FG)
        self.btn_play.pack(side="left", padx=(0, 8))
        self.btn_pause.pack(side="left", padx=(0, 8))
        self.btn_stop.pack(side="left", padx=(0, 20))
        self.btn_filters_open.pack(side="left", padx=(0, 8))
        self.btn_overlay_open.pack(side="left", padx=(0, 8))

        self.btn_pause.config(state="disabled")
        self.btn_stop.config(state="disabled")

        # ── barra de progreso (video)
        progress_frame = tk.Frame(self, bg=BG)
        progress_frame.pack(fill="x", side="bottom", padx=16, pady=(0, 4))

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

        # ── tooltips en widgets
        self._bind_tooltip(self.btn_open,          "tip_open")
        self._bind_tooltip(self.btn_screen,        "tip_screen")
        self._bind_tooltip(self._btn_pick_region,  "tip_pick_region")
        # tooltip de btn_fit lo gestiona _refresh_fit_btn()
        self._bind_tooltip(self._chk_mirror,       "tip_mirror")
        self._bind_tooltip(self._lbl_rotation,     "tip_rotation")
        self._bind_tooltip(self._rotation_cb,      "tip_rotation")
        self._bind_tooltip(self.btn_filters_open,  "tip_filters")
        self._bind_tooltip(self.btn_overlay_open,  "tip_overlay")
        self._refresh_fit_btn()

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
    def _btn(parent, text: str, cmd, color: str, fg: str = "#ffffff") -> tk.Button:
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg=fg,
                         activebackground=color, activeforeground=fg,
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
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    def _apply_preset(self, _=None):
        sel = self.preset_var.get()
        internal_key = sel if sel in ASPECT_PRESETS else "__custom__"
        cam_w, cam_h, prev_w, prev_h = ASPECT_PRESETS[internal_key]
        if internal_key != "__custom__":
            self.width_var.set(str(cam_w))
            self.height_var.set(str(cam_h))
        self.preview_w, self.preview_h = prev_w, prev_h
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
        _cw = self.canvas.winfo_width()
        _ch = self.canvas.winfo_height()
        pw = _cw if _cw > 1 else self.preview_w
        ph = _ch if _ch > 1 else self.preview_h
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, pw, ph, fill="#111118")

        # borde punteado de zona de drop
        pad = 18
        dash = (8, 6)
        self.canvas.create_rectangle(
            pad, pad, pw - pad, ph - pad,
            outline=FG_DIM, dash=dash, width=2,
        )

        cx, cy = pw // 2, ph // 2

        # icono de subida (flecha + bandeja)
        self.canvas.create_text(cx, cy - 36,
                                text="⬆", fill=ACCENT,
                                font=("Segoe UI", 36))

        # texto principal
        self.canvas.create_text(cx, cy + 18,
                                text=self.t("no_signal"), fill=FG,
                                font=("Segoe UI", 14, "bold"))

        # subtexto
        self.canvas.create_text(cx, cy + 44,
                                text=self.t("drop_hint"), fill=FG_DIM,
                                font=("Segoe UI", 10))

        # item persistente para los frames del stream (encima del placeholder)
        self._canvas_img_id = self.canvas.create_image(0, 0, anchor="nw")

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

    def _sync_filter(self, name: str, value: float):
        if not (self._thread and self._thread.is_alive()):
            return
        if name == "brightness":
            self._thread.filter_brightness = float(value)
        elif name == "contrast":
            self._thread.filter_contrast = float(value)
        elif name == "saturation":
            self._thread.filter_saturation = float(value)
        elif name == "blur":
            self._thread.filter_blur = int(float(value))

    def _toggle_mirror(self):
        # mirror_var ya fue cambiado por el Checkbutton antes de llamar aquí
        new_val = self.mirror_var.get()
        if self._thread and self._thread.is_alive():
            self._thread.mirror = new_val

    def _on_rotation_change(self, _=None):
        idx = self._rotation_cb.current()
        degrees = idx * 90
        self._rotation_var.set(degrees)
        if self._thread and self._thread.is_alive():
            self._thread.rotation = degrees

    # ------------------------------------------------------------------
    # Zoom digital
    # ------------------------------------------------------------------

    def _zoom_step(self, delta: float):
        """Incrementa o decrementa el zoom en `delta`, dentro del rango 1.0–5.0."""
        new_val = round(max(1.0, min(5.0, self._zoom_var.get() + delta)), 1)
        self._zoom_var.set(new_val)

    def _sync_zoom(self, *_):
        v = self._zoom_var.get()
        self._zoom_val_lbl.config(text=f"{v:.1f}×")
        if self._thread and self._thread.is_alive():
            self._thread.zoom    = v
            self._thread.zoom_cx = self._zoom_cx
            self._thread.zoom_cy = self._zoom_cy

    def _on_canvas_motion(self, event):
        """Actualiza el anchor de zoom según la posición del puntero sobre el canvas."""
        pw = self.canvas.winfo_width()  or self.preview_w
        ph = self.canvas.winfo_height() or self.preview_h
        self._zoom_cx = max(0.0, min(1.0, event.x / pw))
        self._zoom_cy = max(0.0, min(1.0, event.y / ph))
        if self._thread and self._thread.is_alive():
            self._thread.zoom_cx = self._zoom_cx
            self._thread.zoom_cy = self._zoom_cy

    def _on_canvas_leave(self, _event=None):
        """Cuando el puntero sale del canvas, el anchor vuelve al centro."""
        self._zoom_cx = 0.5
        self._zoom_cy = 0.5
        if self._thread and self._thread.is_alive():
            self._thread.zoom_cx = 0.5
            self._thread.zoom_cy = 0.5

    def _on_canvas_resize(self, *_):
        """Redibuja el placeholder centrado cuando el canvas cambia de tamaño."""
        if not self._file_loaded:
            self._draw_placeholder()

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
        cw = self.canvas.winfo_width()  or self.preview_w
        ch = self.canvas.winfo_height() or self.preview_h
        return cx / cw * cam_w, cy / ch * cam_h

    def _on_canvas_press(self, event):
        # Si no hay archivo cargado (placeholder "no signal"), abrir selector
        if not self._file_loaded and not self._use_screen:
            self._open_file()
            return
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
        elif self._drag_overlay_type == "clock":
            ov.clock_pos = "custom"
            ov.clock_xy  = (ox, oy)
        else:
            ov.img_pos = "custom"
            ov.img_xy  = (ox, oy)

    def _on_canvas_release(self, event):
        self._drag_overlay_type = None

    # ------------------------------------------------------------------
    # Helpers de overlay
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Ventana de filtros / overlay / about  →  delegados a módulos ui_*
    # ------------------------------------------------------------------

    def _open_filter_window(self):
        open_filter_window(self)

    def _open_overlay_window(self):
        open_overlay_window(self)

    def _show_about(self):
        open_about(self)

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
        self._screen_region = None
        self._btn_pick_region.config(text=self.t("btn_pick_region"))
        if self._use_screen:
            if idx == 0:
                self.source_var.set(self.t("screen_label_all"))
            else:
                self.source_var.set(self.t("screen_label", n=idx))

    def _select_screen(self):
        """Activa el modo captura de pantalla."""
        self._use_screen = True
        self._file_loaded = True
        self._screen_region = None
        self._refresh_monitor_list()
        self._monitor_cb.config(state="readonly")
        self._monitor_var.set(self._monitor_cb["values"][0])
        self._screen_monitor_idx = 0
        self._btn_pick_region.config(state="normal", text=self.t("btn_pick_region"))
        self.source_var.set(self.t("screen_label_all"))
        self.info_var.set("")
        self._update_thumbnail(None)
        self._set_status(self.t("status_screen"))
        self._draw_placeholder()

    def _pick_screen_region(self):
        """Abre el selector de región si ya hay una región, la limpia; si no, abre el picker."""
        if self._screen_region:
            # segunda pulsación: limpiar región
            self._screen_region = None
            self._btn_pick_region.config(text=self.t("btn_pick_region"))
            self._bind_tooltip(self._btn_pick_region, "tip_pick_region")
            idx = self._screen_monitor_idx
            if idx == 0:
                self.source_var.set(self.t("screen_label_all"))
            else:
                self.source_var.set(self.t("screen_label", n=idx))
            return

        if not MSS_AVAILABLE:
            return
        try:
            import mss as _mss
            with _mss.mss() as sct:
                monitors = sct.monitors
                idx = max(1, min(self._screen_monitor_idx, len(monitors) - 1))
                mon = monitors[idx]
        except Exception:
            return

        picker = _RegionPicker(self, mon, self.t("region_picker_hint"))
        if picker.result:
            self._screen_region = picker.result
            r = picker.result
            self.source_var.set(self.t("region_label",
                                        w=r["width"], h=r["height"],
                                        x=r["left"], y=r["top"]))
            self._btn_pick_region.config(text=self.t("btn_clear_region"))
            self._bind_tooltip(self._btn_pick_region, "tip_clear_region")

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
        # usar tamaño real del canvas para evitar doble-escala con ratio distinto
        _cw = self.canvas.winfo_width();  _ch = self.canvas.winfo_height()
        pw = _cw if _cw > 1 else self.preview_w
        ph = _ch if _ch > 1 else self.preview_h
        first_frame: "np.ndarray | None" = None
        video_meta:  "dict | None"       = None
        if stype == "image":
            frame = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
            if frame is not None:
                # compositar canal alfa sobre fondo negro si existe
                if frame.ndim == 3 and frame.shape[2] == 4:
                    alpha = frame[:, :, 3:4].astype(np.float32) / 255.0
                    bgr   = frame[:, :, :3].astype(np.float32)
                    frame = (bgr * alpha).astype(np.uint8)
                elif frame.ndim == 2:
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
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
                with _PilImg.open(str(src)) as gif:
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
            screen_region=self._screen_region,
        )
        self._thread.filter_brightness = self._bri_var.get()
        self._thread.filter_contrast   = self._con_var.get()
        self._thread.filter_saturation = self._sat_var.get()
        self._thread.filter_blur       = int(self._blur_var.get())
        self._thread.zoom              = self._zoom_var.get()
        self._thread.zoom_cx           = self._zoom_cx
        self._thread.zoom_cy           = self._zoom_cy
        self._thread.rotation          = self._rotation_var.get()
        self._thread.overlay           = self._overlay
        self._thread.show_cursor       = self._show_cursor_var.get()
        self._thread.preview_interval  = PREVIEW_MIN_INTERVAL
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
        self._refresh_fit_btn()
        if self._thread and self._thread.is_alive():
            self._thread.cover = cover

    def _refresh_fit_btn(self):
        """Actualiza texto, color y tooltip del botón Crop/Letterbox según el modo activo."""
        if self.cover_var.get():
            self.btn_fit.config(text=self.t("btn_crop"),       bg=ACCENT)
            self._bind_tooltip(self.btn_fit, "tip_crop")
        else:
            self.btn_fit.config(text=self.t("btn_letterbox"),  bg=BG_BTN)
            self._bind_tooltip(self.btn_fit, "tip_letterbox")

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
        # Sobrescribe el frame pendiente — si la UI no alcanzó a renderizar el anterior lo descarta
        self._pending_frame = rgb
        if not self._frame_scheduled:
            self._frame_scheduled = True
            self.after(0, self._render_pending_frame)
        if self._thread and self._thread.total_frames > 0 and not self._seek_dragging:
            prog    = self._thread.current_frame / self._thread.total_frames
            elapsed = self._thread.current_frame / max(self._thread.src_fps, 1)
            total   = self._thread.total_frames  / max(self._thread.src_fps, 1)
            self.after(0, self._update_progress, prog, elapsed, total)

    def _render_pending_frame(self):
        self._frame_scheduled = False
        rgb = self._pending_frame
        if rgb is None:
            return
        self._pending_frame = None
        self._show_frame(rgb)

    def _show_frame(self, rgb: np.ndarray):
        img = Image.fromarray(rgb)
        iw, ih = img.size
        _cw = self.canvas.winfo_width()
        _ch = self.canvas.winfo_height()
        pw = _cw if _cw > 1 else self.preview_w
        ph = _ch if _ch > 1 else self.preview_h
        if iw != pw or ih != ph:
            scale = min(pw / iw, ph / ih)
            nw, nh = int(iw * scale), int(ih * scale)
            img = img.resize((nw, nh), Image.BILINEAR)
            if nw != pw or nh != ph:
                canvas_img = Image.new("RGB", (pw, ph), (0, 0, 0))
                canvas_img.paste(img, ((pw - nw) // 2, (ph - nh) // 2))
                img = canvas_img
        photo = ImageTk.PhotoImage(img)
        self._last_photo = photo
        if self._canvas_img_id is None:
            self._canvas_img_id = self.canvas.create_image(0, 0, anchor="nw", image=photo)
        else:
            self.canvas.itemconfig(self._canvas_img_id, image=photo)

    def _update_progress(self, prog: float, elapsed: float, total: float):
        self.progress_var.set(prog)
        def fmt(s: float) -> str:
            return f"{int(s) // 60}:{int(s) % 60:02d}"
        self.time_label.config(text=f"{fmt(elapsed)} / {fmt(total)}")

    def _poll_cpu(self):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        if PSUTIL_AVAILABLE:
            cpu = _constants_mod._psutil.cpu_percent(interval=None)
            mem = _constants_mod._psutil.virtual_memory().percent
            self._cpu_var.set(f"CPU {cpu:.0f}%")
            self._mem_var.set(f"RAM {mem:.0f}%")
        self.after(2000, self._poll_cpu)

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

    def _set_camera_icon(self):
        """Carga icono.png, genera .ico con PIL y lo asigna a titlebar y taskbar."""
        try:
            from PIL import Image as _Img
            png_path = Path(__file__).parent / "icono.png"
            base = _Img.open(str(png_path)).convert("RGBA")

            ico_path = Path(__file__).parent / "_app_icon.ico"
            # PIL maneja correctamente el formato ICO incluyendo 256px
            base.save(str(ico_path), format="ICO",
                      sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
            self.iconbitmap(default=str(ico_path))
        except Exception as e:
            print(f"[icon] {e}")

    def _on_close(self):
        self._stop()
        self._save_prefs()
        self.destroy()  # UI desaparece inmediatamente; join ocurre tras mainloop()