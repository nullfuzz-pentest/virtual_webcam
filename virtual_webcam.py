"""
Virtual Webcam Emulator — GUI
------------------------------
Emula una webcam virtual usando imágenes o videos como fuente.
Incluye interfaz gráfica con preview en tiempo real.

Requisitos:
    pip install opencv-python pyvirtualcam numpy pillow

Backend Windows: OBS Virtual Camera (instalar OBS Studio)
Backend Linux:   v4l2loopback  (sudo modprobe v4l2loopback)

Atajos de teclado:
    Ctrl+O  → Abrir archivo
    Espacio → Pausar / Reanudar
    Escape  → Detener

Estructura de módulos:
    constants.py      — constantes, flags de dependencias, paleta de colores
    translations.py   — cadenas i18n (es, en, pt, zh)
    image_utils.py    — procesamiento de frames (fit, filtros, conversión)
    overlay.py        — overlay de texto e imagen PNG
    stream_thread.py  — hilo de captura y emisión de frames
    app.py            — ventana principal (GUI Tkinter)
    virtual_webcam.py — punto de entrada
"""

import sys
import os
import importlib

# Suprime mensajes de FFmpeg (ej. "mmco: unref short failure") en la consola
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")   # AV_LOG_QUIET
os.environ.setdefault("OPENCV_LOG_LEVEL", "OFF")

if importlib.util.find_spec("PIL") is None:
    print("[ERROR] Pillow not installed. Run: pip install pillow")
    sys.exit(1)

from app import App

if __name__ == "__main__":
    app = App()
    app.mainloop()
