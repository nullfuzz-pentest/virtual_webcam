"""
constants.py
------------
Constantes globales, flags de disponibilidad de dependencias opcionales
y clase base de la ventana principal (con o sin drag & drop).
"""

import tkinter as tk

# ---------------------------------------------------------------------------
# Dependencias opcionales
# ---------------------------------------------------------------------------

try:
    import pyvirtualcam
    from pyvirtualcam import PixelFormat
    PYVIRTUALCAM_AVAILABLE = True
except ImportError:
    pyvirtualcam = None          # type: ignore[assignment]
    PixelFormat   = None         # type: ignore[assignment]
    PYVIRTUALCAM_AVAILABLE = False

try:
    import mss  # noqa: F401
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False
    TkinterDnD = None   # type: ignore[assignment]
    DND_FILES   = None  # type: ignore[assignment]

# Clase base dinámica: TkinterDnD.Tk habilita drag & drop; fallback a tk.Tk
_AppBase = TkinterDnD.Tk if TKDND_AVAILABLE else tk.Tk

# ---------------------------------------------------------------------------
# Formatos soportados
# ---------------------------------------------------------------------------

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tiff", ".tif"}
SUPPORTED_GIFS   = {".gif"}
SUPPORTED_VIDEOS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"}

# ---------------------------------------------------------------------------
# Presets de aspecto  { etiqueta: (cam_w, cam_h, prev_w, prev_h) }
# ---------------------------------------------------------------------------

ASPECT_PRESETS: dict[str, tuple[int, int, int, int]] = {
    "16:9  1280×720" : (1280,  720, 854, 480),
    "16:9  1920×1080": (1920, 1080, 854, 480),
    "9:16  720×1280" : ( 720, 1280, 338, 600),
    "9:16  1080×1920": (1080, 1920, 338, 600),
    "4:3   640×480"  : ( 640,  480, 800, 600),
    "4:3   1280×960" : (1280,  960, 800, 600),
    "1:1   720×720"  : ( 720,  720, 600, 600),
    "1:1   1080×1080": (1080, 1080, 600, 600),
    "__custom__"     : (1280,  720, 854, 480),   # clave interna fija
}
_PRESET_NUMERIC_KEYS = [k for k in ASPECT_PRESETS if k != "__custom__"]

# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

PREVIEW_W            = 854
PREVIEW_H            = 480
PREVIEW_MAX_FPS      = 60
PREVIEW_MIN_INTERVAL = 1.0 / PREVIEW_MAX_FPS

# ---------------------------------------------------------------------------
# Paleta de colores (tema oscuro — valores iniciales)
# ---------------------------------------------------------------------------

BG        = "#1e1e2e"
BG_PANEL  = "#2a2a3e"
BG_BTN    = "#3b3b5c"
ACCENT    = "#7c6af7"
ACCENT2   = "#56cfb2"
FG        = "#e0e0f0"
FG_DIM    = "#888899"
RED       = "#f07070"
STATUS_BG = "#16161f"

# ---------------------------------------------------------------------------
# Temas disponibles
# ---------------------------------------------------------------------------

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "BG":        "#1e1e2e",
        "BG_PANEL":  "#2a2a3e",
        "BG_BTN":    "#3b3b5c",
        "ACCENT":    "#7c6af7",
        "ACCENT2":   "#56cfb2",
        "FG":        "#e0e0f0",
        "FG_DIM":    "#888899",
        "RED":       "#f07070",
        "STATUS_BG": "#16161f",
    },
    "blue": {
        "BG":        "#0d1b2a",
        "BG_PANEL":  "#152436",
        "BG_BTN":    "#1e3a56",
        "ACCENT":    "#4a9edd",
        "ACCENT2":   "#50d0a8",
        "FG":        "#d8eeff",
        "FG_DIM":    "#6a94bc",
        "RED":       "#f07070",
        "STATUS_BG": "#080f18",
    },
    "white": {
        "BG":        "#f0f0f8",
        "BG_PANEL":  "#ffffff",
        "BG_BTN":    "#d8d8e8",
        "ACCENT":    "#5b4fcf",
        "ACCENT2":   "#1a9e80",
        "FG":        "#1a1a2e",
        "FG_DIM":    "#555578",
        "RED":       "#c83030",
        "STATUS_BG": "#e0e0ec",
    },
    "halloween": {
        "BG":        "#1a0a00",
        "BG_PANEL":  "#2b1200",
        "BG_BTN":    "#4a2000",
        "ACCENT":    "#ff6a00",
        "ACCENT2":   "#b843e0",
        "FG":        "#ffd580",
        "FG_DIM":    "#a06030",
        "RED":       "#ff3030",
        "STATUS_BG": "#0f0500",
    },
}

THEME_KEYS = list(THEMES.keys())   # ["dark", "blue", "white", "halloween"]