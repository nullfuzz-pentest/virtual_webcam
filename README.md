# Virtual Webcam Emulator v1.2

Emula una webcam virtual usando imágenes, videos o captura de pantalla como fuente, con interfaz gráfica en tiempo real.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Version](https://img.shields.io/badge/Version-1.2-purple)

---

## Características

- Soporte para imágenes (JPG, PNG, BMP, WEBP, TIFF), videos (MP4, AVI, MOV, MKV, WEBM, FLV, WMV) y GIFs animados
- Captura de pantalla en tiempo real con selección de monitor y cursor visible opcional
- Preview en vivo con control de FPS
- Filtros de imagen: zoom digital, brillo, contraste, saturación y desenfoque
- Overlay de texto e imagen PNG con posicionamiento libre y arrastre con el mouse
- Espejo horizontal (flip)
- Modo Crop (relleno) y Letterbox (barras negras)
- Seek interactivo en videos
- Drag & drop de archivos (requiere `tkinterdnd2`)
- Clic en el área de preview para abrir el selector de archivos cuando no hay fuente cargada
- Interfaz multiidioma: Español, English, Português, 中文
- Temas de interfaz: Dark, Blue, White
- Detección automática del idioma del sistema
- LED de estado: cámara activa / solo preview / error

---

## Requisitos

```bash
pip install opencv-python pyvirtualcam numpy pillow
```

### Backend de cámara virtual

| Sistema | Requisito |
| --- | --- |
| Windows | [OBS Studio](https://obsproject.com/) → Herramientas → Iniciar cámara virtual |
| Windows | Alternativa: [Unity Capture](https://github.com/schellingb/UnityCapture) |
| Linux | `sudo modprobe v4l2loopback` |

### Dependencias opcionales

| Paquete | Función |
| --- | --- |
| `mss` | Captura de pantalla multi-monitor |
| `tkinterdnd2` | Drag & drop de archivos |

```bash
pip install mss tkinterdnd2
```

---

## Uso

```bash
python virtual_webcam.py
```

---

## Atajos de teclado

| Tecla | Acción |
| --- | --- |
| `Ctrl+O` | Abrir archivo |
| `S` | Iniciar transmisión |
| `Space` | Pausar / Reanudar |
| `Escape` | Detener |
| `H` | Activar/desactivar espejo |
| `F` | Abrir/cerrar ventana de filtros |
| `O` | Abrir/cerrar ventana de overlay |
| `+` / `=` | Aumentar zoom (+0.1×) |
| `-` | Reducir zoom (-0.1×) |

---

## Estructura del proyecto

```text
virtual_webcam.py   — punto de entrada
constants.py        — constantes, flags de dependencias, paleta de colores y temas
translations.py     — cadenas i18n (es, en, pt, zh)
image_utils.py      — procesamiento de frames (fit, zoom, filtros, GIF, conversión)
overlay.py          — overlay de texto e imagen PNG
stream_thread.py    — hilo de captura y emisión de frames
app.py              — ventana principal (GUI Tkinter)
```

---

## Changelog

### v1.2 (latest)

- Soporte de GIFs animados con temporización por frame
- Zoom digital (1×–5×) con slider y atajos de teclado `+` / `-`
- Arrastre del overlay directamente sobre el canvas
- Cursor del mouse visible en capturas de pantalla (configurable)
- Temas de interfaz: Dark, Blue, White
- Detección automática del idioma del sistema al iniciar
- Atajo `[O]` para la ventana de overlay y `[S]` para iniciar
- Información del archivo movida a la barra de estado
- Supresión de errores h264 en consola durante reproducción de video
- Área de preview interactiva: muestra zona de drop con icono ⬆, borde punteado y texto multiidioma; clic abre el selector de archivos directamente

### v1.0

- Versión inicial

---

## Autor

**nullfuzz** — [github.com/nullfuzz-pentest/webcam_virtual](https://github.com/nullfuzz-pentest/webcam_virtual)

Licencia MIT
