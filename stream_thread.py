"""
stream_thread.py
----------------
Hilo de streaming: lee frames desde imagen, video o captura de pantalla
y los emite a la cámara virtual (pyvirtualcam) y al callback de preview.
"""

import threading
import time
from pathlib import Path

import cv2
import numpy as np

try:
    import ctypes
    import ctypes.wintypes
    _CTYPES_OK = True
except Exception:
    _CTYPES_OK = False

from constants import PYVIRTUALCAM_AVAILABLE, MSS_AVAILABLE
from image_utils import fit_frame, bgr_to_rgb, apply_filters, apply_zoom, apply_rotation, load_gif_frames
from overlay import OverlayConfig, apply_overlay

if PYVIRTUALCAM_AVAILABLE:
    import pyvirtualcam


class StreamThread(threading.Thread):
    """Hilo que lee frames y los emite a la cámara virtual + callback de preview."""

    def __init__(self, source: "Path | None", source_type: str, cam_width: int,
                 cam_height: int, fps: float, loop: bool, cover: bool,
                 on_frame, on_status, on_stopped, cam_kwargs: dict,
                 msg_cam_active: str, msg_preview_only: str,
                 monitor_idx: int = 0, mirror: bool = False,
                 on_cam_state=None, screen_region: "dict | None" = None):
        super().__init__(daemon=True)
        self.source           = source
        self.source_type      = source_type
        self.cam_width        = cam_width
        self.cam_height       = cam_height
        self.fps              = fps
        self.loop             = loop
        self.cover            = cover
        self.on_frame         = on_frame
        self.on_status        = on_status
        self.on_stopped       = on_stopped
        self.cam_kwargs       = cam_kwargs
        self.msg_cam_active   = msg_cam_active
        self.msg_preview_only = msg_preview_only
        self.monitor_idx      = monitor_idx
        self.mirror           = mirror
        self.on_cam_state     = on_cam_state
        self.screen_region    = screen_region  # {"left","top","width","height"} o None

        # cursor (capturas de pantalla)
        self.show_cursor: bool = True

        # filtros (actualizables en caliente desde la UI)
        self.filter_brightness: float = 0.0    # -100 .. 100
        self.filter_contrast:   float = 1.0    #  0.5 .. 2.0
        self.filter_saturation: float = 1.0    #  0.0 .. 2.0
        self.filter_blur:       int   = 0      #    0 .. 10
        self.zoom:              float = 1.0    #  1.0 .. 5.0 (zoom digital)
        self.zoom_cx:           float = 0.5    #  0.0 .. 1.0 (anchor horizontal)
        self.zoom_cy:           float = 0.5    #  0.0 .. 1.0 (anchor vertical)
        self.rotation:          int   = 0      #  0 / 90 / 180 / 270

        # overlay (referencia al objeto del App, modificable desde la UI)
        self.overlay: OverlayConfig = OverlayConfig()

        self._pause   = threading.Event()
        self._stop_event    = threading.Event()
        self._paused  = False

        self._seek_lock          = threading.Lock()
        self._seek_to: int | None = None

        self.current_frame = 0
        self.total_frames  = 0
        self.src_fps       = fps
        self.cam_device    = ""

        self._fps_count    = 0
        self._fps_window_t = time.monotonic()
        self.measured_fps  = 0.0

        # throttle del preview: sólo llamar on_frame cuando haya pasado el intervalo
        self.preview_interval: float = 0.0   # 0 = sin límite; setter desde App
        self._preview_last_t: float  = 0.0

    # ------------------------------------------------------------------
    # Control público
    # ------------------------------------------------------------------

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self):
        self._paused = True
        self._pause.clear()

    def resume(self):
        self._paused = False
        self._pause.set()

    def stop(self):
        self._stop_event.set()
        self._pause.set()

    def seek(self, frame_no: int):
        with self._seek_lock:
            self._seek_to = frame_no

    # ------------------------------------------------------------------
    # Ejecución principal
    # ------------------------------------------------------------------

    def run(self):
        self._pause.set()
        try:
            if PYVIRTUALCAM_AVAILABLE:
                with pyvirtualcam.Camera(**self.cam_kwargs) as cam:
                    self.cam_device = cam.device
                    self.on_status(self.msg_cam_active.format(device=cam.device))
                    if self.on_cam_state:
                        self.on_cam_state("active")
                    self._stream_loop(cam)
            else:
                self.cam_device = "preview-only"
                self.on_status(self.msg_preview_only)
                if self.on_cam_state:
                    self.on_cam_state("preview_only")
                self._stream_loop(None)
        except Exception as exc:
            self.on_stopped(str(exc))
            return
        self.on_stopped(None)

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _tick_fps(self):
        self._fps_count += 1
        now = time.monotonic()
        elapsed = now - self._fps_window_t
        if elapsed >= 2.0:
            self.measured_fps  = self._fps_count / elapsed
            self._fps_count    = 0
            self._fps_window_t = now

    def _tick_preview(self, frame_rgb) -> bool:
        """Llama on_frame sólo si ha pasado preview_interval desde la última vez.
        Retorna True si el frame fue enviado al callback."""
        if self.preview_interval <= 0.0:
            self.on_frame(frame_rgb)
            return True
        now = time.monotonic()
        if now - self._preview_last_t >= self.preview_interval:
            self._preview_last_t = now
            self.on_frame(frame_rgb)
            return True
        return False

    def _draw_cursor(self, frame_bgr: np.ndarray, x: int, y: int) -> np.ndarray:
        """Dibuja un cursor de flecha en las coordenadas (x, y) del frame."""
        h, w = frame_bgr.shape[:2]
        if x < 0 or y < 0 or x >= w or y >= h:
            return frame_bgr
        s = 18
        pts = np.array([
            [x,           y          ],
            [x,           y + s      ],
            [x + s // 3,  y + s * 2 // 3],
            [x + s // 2,  y + s + 4  ],
            [x + s * 2 // 3, y + s   ],
            [x + s // 3 + 2, y + s * 2 // 3 - 3],
            [x + s * 2 // 3, y + s // 3],
        ], dtype=np.int32)
        cv2.fillPoly(frame_bgr, [pts], (255, 255, 255))
        cv2.polylines(frame_bgr, [pts], True, (0, 0, 0), 1, cv2.LINE_AA)
        return frame_bgr

    def _get_cursor_pos(self):
        """Devuelve (x, y) del cursor en coordenadas de pantalla, o None."""
        if not _CTYPES_OK:
            return None
        try:
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return pt.x, pt.y
        except Exception:
            return None

    def _image_sig(self) -> tuple:
        """Firma de todos los parámetros que afectan el procesamiento de un frame estático."""
        ov = self.overlay
        return (
            self.mirror, self.zoom, self.rotation,
            self.filter_brightness, self.filter_contrast,
            self.filter_saturation, self.filter_blur,
            ov.enabled, ov.text, ov.font_scale,
            ov.text_color_bgr, ov.text_bg_alpha, ov.text_pos, ov.text_xy,
            id(ov.img_bgra), ov.img_pos, ov.img_scale, ov.img_alpha, ov.img_xy,
        )

    def _process(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Aplica zoom → flip → rotación → filtros → overlay y devuelve frame RGB listo para enviar."""
        if self.zoom > 1.0:
            frame_bgr = apply_zoom(frame_bgr, self.zoom, self.zoom_cx, self.zoom_cy)
        if self.mirror:
            frame_bgr = cv2.flip(frame_bgr, 1)
        if self.rotation:
            frame_bgr = apply_rotation(frame_bgr, self.rotation)
        frame_bgr = apply_filters(frame_bgr, self.filter_brightness,
                                  self.filter_contrast, self.filter_saturation,
                                  self.filter_blur)
        frame_bgr = apply_overlay(frame_bgr, self.overlay)
        return bgr_to_rgb(frame_bgr)

    def _stream_loop(self, cam):
        if self.source_type == "screen":
            self._loop_screen(cam)
        elif self.source_type == "image":
            self._loop_image(cam)
        elif self.source_type == "gif":
            self._loop_gif(cam)
        else:
            self._loop_video(cam)

    # ------------------------------------------------------------------
    # Bucles por tipo de fuente
    # ------------------------------------------------------------------

    def _loop_screen(self, cam):
        delay = 1.0 / self.fps
        if MSS_AVAILABLE:
            import mss as _mss
            with _mss.mss() as sct:
                monitors = sct.monitors   # [0]=all combined, [1+]=individual
                idx = min(self.monitor_idx, len(monitors) - 1)
                monitor = monitors[idx]
                # región personalizada toma precedencia sobre el monitor completo
                grab_target = self.screen_region if self.screen_region else monitor
                while not self._stop_event.is_set():
                    self._pause.wait()
                    if self._stop_event.is_set():
                        break
                    raw = sct.grab(grab_target)
                    frame_bgr  = cv2.cvtColor(np.frombuffer(raw.raw, dtype=np.uint8)
                                              .reshape(raw.height, raw.width, 4),
                                              cv2.COLOR_BGRA2BGR)
                    if self.show_cursor:
                        pos = self._get_cursor_pos()
                        if pos:
                            cx = pos[0] - grab_target["left"]
                            cy = pos[1] - grab_target["top"]
                            frame_bgr = self._draw_cursor(frame_bgr, cx, cy)
                    frame_bgr  = fit_frame(frame_bgr, self.cam_width, self.cam_height, self.cover)
                    frame_rgb  = self._process(frame_bgr)
                    if cam:
                        cam.send(frame_rgb)
                        cam.sleep_until_next_frame()
                    else:
                        time.sleep(delay)
                    self._tick_fps()
                    self._tick_preview(frame_rgb)
        else:
            # Fallback: PIL.ImageGrab (Windows / macOS only)
            try:
                from PIL import ImageGrab
            except ImportError:
                raise RuntimeError("Screen capture requires mss:  pip install mss")
            while not self._stop_event.is_set():
                self._pause.wait()
                if self._stop_event.is_set():
                    break
                if self.screen_region:
                    r = self.screen_region
                    bbox = (r["left"], r["top"],
                            r["left"] + r["width"], r["top"] + r["height"])
                    screenshot = ImageGrab.grab(bbox=bbox)
                    off_x, off_y = r["left"], r["top"]
                else:
                    screenshot = ImageGrab.grab()
                    off_x, off_y = 0, 0
                frame_pil  = np.array(screenshot)                   # RGB
                frame_bgr  = cv2.cvtColor(frame_pil, cv2.COLOR_RGB2BGR)
                if self.show_cursor:
                    pos = self._get_cursor_pos()
                    if pos:
                        frame_bgr = self._draw_cursor(frame_bgr,
                                                      pos[0] - off_x, pos[1] - off_y)
                frame_bgr  = fit_frame(frame_bgr, self.cam_width, self.cam_height, self.cover)
                frame_rgb  = self._process(frame_bgr)
                if cam:
                    cam.send(frame_rgb)
                    cam.sleep_until_next_frame()
                else:
                    time.sleep(delay)
                self._tick_fps()
                self._tick_preview(frame_rgb)

    def _loop_image(self, cam):
        frame_bgr = cv2.imread(str(self.source))
        if frame_bgr is None:
            raise RuntimeError(f"Cannot read image: {self.source}")
        frame_bgr = fit_frame(frame_bgr, self.cam_width, self.cam_height, self.cover)
        delay = 1.0 / self.fps

        _cached_rgb: "np.ndarray | None" = None
        _cached_sig: "tuple | None"      = None

        while not self._stop_event.is_set():
            self._pause.wait()
            if self._stop_event.is_set():
                break
            sig = self._image_sig()
            if sig != _cached_sig:
                _cached_rgb = self._process(frame_bgr)
                _cached_sig = sig
            frame_rgb = _cached_rgb
            if cam:
                cam.send(frame_rgb)
                cam.sleep_until_next_frame()
            else:
                time.sleep(delay)
            self._tick_fps()
            self._tick_preview(frame_rgb)

    def _loop_gif(self, cam):
        frames = load_gif_frames(self.source, self.cam_width, self.cam_height, self.cover)
        if not frames:
            raise RuntimeError(f"Cannot read GIF: {self.source}")
        delay = 1.0 / self.fps

        _cached: dict = {}   # {i: frame_rgb} para evitar reprocesar frames idénticos

        while not self._stop_event.is_set():
            for i, (frame_bgr, duration) in enumerate(frames):
                if self._stop_event.is_set():
                    break
                self._pause.wait()
                if self._stop_event.is_set():
                    break

                sig = self._image_sig()
                if _cached.get("sig") != sig or _cached.get("idx") != i:
                    _cached["frame"] = self._process(frame_bgr)
                    _cached["sig"]   = sig
                    _cached["idx"]   = i
                frame_rgb = _cached["frame"]

                # Mantener el frame durante su duración enviando a la cámara al fps del cam
                end_time = time.monotonic() + duration
                while time.monotonic() < end_time and not self._stop_event.is_set():
                    if cam:
                        cam.send(frame_rgb)
                        cam.sleep_until_next_frame()
                    else:
                        time.sleep(delay)
                    self._tick_fps()
                    self._tick_preview(frame_rgb)

            if not self.loop:
                break

    def _loop_video(self, cam):
        cap = cv2.VideoCapture(str(self.source))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {self.source}")

        self.src_fps      = cap.get(cv2.CAP_PROP_FPS) or self.fps
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        delay = 1.0 / self.fps

        try:
            while not self._stop_event.is_set():
                self._pause.wait()
                if self._stop_event.is_set():
                    break

                with self._seek_lock:
                    seek_target  = self._seek_to
                    self._seek_to = None
                if seek_target is not None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, seek_target)
                    self.current_frame = seek_target

                ret, frame_bgr = cap.read()
                if not ret:
                    if self.loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self.current_frame = 0
                        continue
                    else:
                        break

                self.current_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
                frame_bgr = fit_frame(frame_bgr, self.cam_width, self.cam_height, self.cover)
                frame_rgb = self._process(frame_bgr)

                if cam:
                    cam.send(frame_rgb)
                    cam.sleep_until_next_frame()
                else:
                    time.sleep(delay)

                self._tick_fps()
                self._tick_preview(frame_rgb)
        finally:
            cap.release()