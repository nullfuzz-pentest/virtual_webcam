"""
image_utils.py
--------------
Funciones de procesamiento de imagen/frame reutilizadas por el hilo
de streaming y la interfaz gráfica.
"""

from pathlib import Path

import cv2
import numpy as np

from constants import SUPPORTED_IMAGES, SUPPORTED_GIFS, SUPPORTED_VIDEOS


def detect_source_type(path: Path) -> str:
    """Devuelve 'image', 'gif', 'video' o 'unknown' según la extensión del archivo."""
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGES:
        return "image"
    if suffix in SUPPORTED_GIFS:
        return "gif"
    if suffix in SUPPORTED_VIDEOS:
        return "video"
    return "unknown"


def load_gif_frames(path: Path, width: int, height: int, cover: bool) -> list:
    """Carga todos los frames de un GIF animado.
    Retorna lista de (frame_bgr, duration_s)."""
    from PIL import Image as PilImage
    frames = []
    with PilImage.open(str(path)) as gif:
        try:
            while True:
                frame_rgb = np.array(gif.convert("RGB"))
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                frame_bgr = fit_frame(frame_bgr, width, height, cover)
                duration  = gif.info.get("duration", 100) / 1000.0
                frames.append((frame_bgr, max(duration, 0.02)))
                gif.seek(gif.tell() + 1)
        except EOFError:
            pass
    return frames


def fit_frame(frame: np.ndarray, width: int, height: int, cover: bool = True) -> np.ndarray:
    """
    Ajusta *frame* a (width × height).

    cover=True  → rellena recortando (crop/fill).
    cover=False → encaja con barras negras (letterbox).
    """
    h, w = frame.shape[:2]
    if w == width and h == height:
        return frame
    if cover:
        scale = max(width / w, height / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        xo = (nw - width) // 2
        yo = (nh - height) // 2
        return resized[yo : yo + height, xo : xo + width]
    else:
        scale = min(width / w, height / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((height, width, 3), dtype=np.uint8)
        yo, xo = (height - nh) // 2, (width - nw) // 2
        canvas[yo : yo + nh, xo : xo + nw] = resized
        return canvas


def apply_zoom(frame: np.ndarray, zoom: float,
               cx_frac: float = 0.5, cy_frac: float = 0.5) -> np.ndarray:
    """Aplica zoom digital recortando el frame alrededor del punto (cx_frac, cy_frac)
    (normalizado 0–1) y reescalando a la resolución original.

    zoom=1.0 → sin cambio; zoom=2.0 → amplía 2× el punto indicado; zoom=5.0 → máximo.
    cx_frac/cy_frac=0.5 → zoom centrado (comportamiento anterior).
    """
    if zoom <= 1.0:
        return frame
    h, w = frame.shape[:2]
    new_h = max(1, int(h / zoom))
    new_w = max(1, int(w / zoom))
    # Centro del recorte según el anchor, clampeado para no salir del frame
    cx = int(cx_frac * w)
    cy = int(cy_frac * h)
    x0 = max(0, min(w - new_w, cx - new_w // 2))
    y0 = max(0, min(h - new_h, cy - new_h // 2))
    cropped = frame[y0 : y0 + new_h, x0 : x0 + new_w]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)


def apply_rotation(frame: np.ndarray, degrees: int) -> np.ndarray:
    """Rota el frame en múltiplos de 90°. Para 90°/270° reajusta al tamaño original con letterbox."""
    if degrees == 0:
        return frame
    h, w = frame.shape[:2]
    if degrees == 90:
        rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif degrees == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    elif degrees == 270:
        rotated = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    else:
        return frame
    # 90/270: el frame quedó h×w; reajustar a w×h con letterbox
    return fit_frame(rotated, w, h, cover=False)


def bgr_to_rgb(frame: np.ndarray) -> np.ndarray:
    """Convierte un frame de BGR (OpenCV) a RGB."""
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def apply_filters(frame: np.ndarray, brightness: float, contrast: float,
                  saturation: float, blur: int) -> np.ndarray:
    """Aplica brillo/contraste/saturación/desenfoque sobre un frame BGR."""
    if brightness != 0.0 or contrast != 1.0:
        frame = np.clip(frame.astype(np.float32) * contrast + brightness, 0, 255).astype(np.uint8)
    if saturation != 1.0:
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
        np.multiply(hsv[:, :, 1], saturation, out=hsv[:, :, 1])
        np.clip(hsv[:, :, 1], 0, 255, out=hsv[:, :, 1])
        frame = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    if blur > 0:
        k = blur * 2 + 1          # kernel impar
        frame = cv2.GaussianBlur(frame, (k, k), 0)
    return frame