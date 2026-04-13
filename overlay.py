"""
overlay.py
----------
Configuración y renderizado del overlay de texto e imagen PNG
que se superpone sobre cada frame antes de enviarlo a la cámara.
"""

import cv2
import numpy as np


# Posiciones disponibles (clave interna → función (w, h, ow, oh) → (x, y))
_OV_POSITIONS: dict[str, object] = {
    "top-left":      lambda w, h, ow, oh: (6, 6),
    "top-center":    lambda w, h, ow, oh: ((w - ow) // 2, 6),
    "top-right":     lambda w, h, ow, oh: (w - ow - 6, 6),
    "center":        lambda w, h, ow, oh: ((w - ow) // 2, (h - oh) // 2),
    "bottom-left":   lambda w, h, ow, oh: (6, h - oh - 6),
    "bottom-center": lambda w, h, ow, oh: ((w - ow) // 2, h - oh - 6),
    "bottom-right":  lambda w, h, ow, oh: (w - ow - 6, h - oh - 6),
}
OV_POS_KEYS = list(_OV_POSITIONS.keys())


class OverlayConfig:
    """Contenedor de ajustes de overlay compartido entre App y StreamThread."""

    def __init__(self):
        self.enabled        = False
        # ── texto
        self.text           = ""
        self.font_scale     = 1.0
        self.text_color_bgr = (255, 255, 255)   # blanco
        self.text_bg_alpha  = 0.5
        self.text_pos       = "bottom-left"
        self.text_xy: "tuple[float, float] | None" = None  # posición libre (0..1)
        # ── imagen PNG
        self.img_path       = ""
        self.img_bgra: "np.ndarray | None" = None   # cacheado
        self.img_pos        = "top-right"
        self.img_scale      = 0.25
        self.img_alpha      = 1.0
        self.img_xy: "tuple[float, float] | None" = None   # posición libre (0..1)


def apply_overlay(frame_bgr: np.ndarray, ov: OverlayConfig) -> np.ndarray:
    """Dibuja el overlay de texto e imagen sobre frame_bgr (in-place seguro)."""
    if not ov.enabled:
        return frame_bgr
    fh, fw = frame_bgr.shape[:2]
    out = frame_bgr.copy()

    # ── imagen PNG ────────────────────────────────────────────────────────
    if ov.img_bgra is not None:
        ih, iw = ov.img_bgra.shape[:2]
        if ov.img_xy is not None:
            ix, iy = int(ov.img_xy[0] * fw), int(ov.img_xy[1] * fh)
        else:
            fn     = _OV_POSITIONS.get(ov.img_pos, _OV_POSITIONS["top-right"])
            ix, iy = fn(fw, fh, iw, ih)
        ix, iy = int(ix), int(iy)
        # región visible
        sx, sy = max(0, -ix), max(0, -iy)
        ex = min(iw, fw - ix);  ey = min(ih, fh - iy)
        dx, dy = max(0, ix),    max(0, iy)
        if ex > sx and ey > sy:
            patch = ov.img_bgra[sy:ey, sx:ex]
            alpha = patch[:, :, 3:4].astype(np.float32) / 255.0 * ov.img_alpha
            src   = patch[:, :, :3].astype(np.float32)
            dst   = out[dy:dy+(ey-sy), dx:dx+(ex-sx)].astype(np.float32)
            out[dy:dy+(ey-sy), dx:dx+(ex-sx)] = (src * alpha + dst * (1 - alpha)).astype(np.uint8)

    # ── texto ─────────────────────────────────────────────────────────────
    if ov.text:
        font      = cv2.FONT_HERSHEY_DUPLEX
        scale     = ov.font_scale
        thick     = max(1, round(scale * 1.5))
        (tw, th), base = cv2.getTextSize(ov.text, font, scale, thick)
        # posición (top-left del bloque de texto)
        if ov.text_xy is not None:
            bx, by_top = int(ov.text_xy[0] * fw), int(ov.text_xy[1] * fh)
        else:
            fn = _OV_POSITIONS.get(ov.text_pos, _OV_POSITIONS["bottom-left"])
            bx, by_top = fn(fw, fh, tw, th + base)
        bx, by_top = int(bx), int(by_top)
        ty = by_top + th       # y del baseline
        pad = 4
        # fondo semitransparente
        if ov.text_bg_alpha > 0:
            rx1 = max(0, bx - pad);         rx2 = min(fw, bx + tw + pad)
            ry1 = max(0, by_top - pad);     ry2 = min(fh, ty + base + pad)
            if rx2 > rx1 and ry2 > ry1:
                roi = out[ry1:ry2, rx1:rx2].astype(np.float32)
                bg  = np.zeros_like(roi)
                out[ry1:ry2, rx1:rx2] = (bg * ov.text_bg_alpha + roi * (1 - ov.text_bg_alpha)).astype(np.uint8)
        cv2.putText(out, ov.text, (bx, ty), font, scale,
                    ov.text_color_bgr, thick, cv2.LINE_AA)
    return out


def get_overlay_rects(ov: OverlayConfig, fw: int, fh: int) -> dict:
    """Retorna {kind: (x, y, w, h)} en coords de frame para hit-testing de drag."""
    rects = {}
    if ov.enabled and ov.img_bgra is not None:
        ih, iw = ov.img_bgra.shape[:2]
        if ov.img_xy is not None:
            ix, iy = int(ov.img_xy[0] * fw), int(ov.img_xy[1] * fh)
        else:
            fn     = _OV_POSITIONS.get(ov.img_pos, _OV_POSITIONS["top-right"])
            ix, iy = int(fn(fw, fh, iw, ih)[0]), int(fn(fw, fh, iw, ih)[1])
        rects["img"] = (ix, iy, iw, ih)
    if ov.enabled and ov.text:
        font  = cv2.FONT_HERSHEY_DUPLEX
        scale = ov.font_scale
        thick = max(1, round(scale * 1.5))
        (tw, th), base = cv2.getTextSize(ov.text, font, scale, thick)
        if ov.text_xy is not None:
            bx, by_top = int(ov.text_xy[0] * fw), int(ov.text_xy[1] * fh)
        else:
            fn = _OV_POSITIONS.get(ov.text_pos, _OV_POSITIONS["bottom-left"])
            bx, by_top = int(fn(fw, fh, tw, th + base)[0]), int(fn(fw, fh, tw, th + base)[1])
        rects["text"] = (bx, by_top, tw, th + base)
    return rects