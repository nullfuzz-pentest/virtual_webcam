# Virtual Webcam Emulator v1.6

Emula una webcam virtual usando imágenes, videos o captura de pantalla como fuente, con interfaz gráfica en tiempo real.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Version](https://img.shields.io/badge/Version-1.6-purple)

---

## Características

- Soporte para imágenes (JPG, PNG, BMP, WEBP, TIFF), videos (MP4, AVI, MOV, MKV, WEBM, FLV, WMV) y GIFs animados
- Captura de pantalla en tiempo real con selección de monitor y cursor visible opcional
- **Selección de región de captura** — selecciona un área específica de la pantalla arrastrando
- Preview en vivo con control de FPS
- Filtros de imagen: zoom digital, brillo, contraste, saturación y desenfoque
- **Zoom direccional** — el punto de zoom sigue la posición del mouse sobre el preview
- Overlay de texto e imagen PNG con posicionamiento libre y arrastre con el mouse
- Espejo horizontal (flip)
- Modo Crop (relleno) y Letterbox (barras negras)
- Seek interactivo en videos
- Drag & drop de archivos (requiere `tkinterdnd2`)
- Clic en el área de preview para abrir el selector de archivos cuando no hay fuente cargada
- Interfaz multiidioma: Español, English, Português, 中文
- **Rotación** — 0° / 90° / 180° / 270° aplicable en tiempo real
- Temas de interfaz: Dark, Blue, White, **Halloween** 🎃
- Detección automática del idioma del sistema
- **Preferencias persistentes** — resolución, tema, idioma, filtros, zoom, rotación y espejo se guardan entre sesiones con auto-guardado (debounce 2s)
- Tooltips en botones mostrados en la barra de estado al pasar el cursor
- LED de estado: cámara activa / solo preview / error
- **Ventana redimensionable** — resize manual y maximizar con canvas adaptable
- **CPU y RAM en barra de estado** — porcentaje de uso actualizado cada 2s (requiere `psutil`)
- **Icono de aplicación personalizado** — icono visible en titlebar y barra de tareas de Windows

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
| `psutil` | CPU % y RAM % en barra de estado |

```bash
pip install mss tkinterdnd2 psutil
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
ui_filters.py       — ventana de filtros (brillo, contraste, saturación, blur)
ui_overlay.py       — ventana de overlay (texto + imagen PNG)
ui_about.py         — diálogo "Acerca de"
prefs.json          — preferencias guardadas (generado automáticamente)
icono.png           — icono de la aplicación
_app_icon.ico       — icono generado automáticamente al iniciar (Windows)
```

---

## Changelog

### v1.6 (latest)

- **RAM en barra de estado**: porcentaje de uso de memoria RAM mostrado junto al CPU, actualizado cada 2s (requiere `psutil`)
- **Icono personalizado en titlebar**: carga `icono.png` y lo aplica como icono de la ventana
- **Icono en barra de tareas de Windows**: genera `_app_icon.ico` con resoluciones 16/32/48/256px; se asigna vía `iconbitmap(default=...)` para que aparezca en la taskbar
- **AppUserModelID**: `SetCurrentProcessExplicitAppUserModelID` llamado antes de crear la ventana para que Windows agrupe la app con su propio icono en la barra de tareas (no el del intérprete Python)

### v1.5

- **Ventana redimensionable**: resize manual arrastrando bordes y botón maximizar habilitados
- **Canvas adaptable**: el área de preview se expande para llenar la ventana al maximizar; placeholder "Soltar archivo aquí" se redibuja centrado al cambiar el tamaño
- **Barra de estado anclada al fondo**: refactorización del order de pack (`side="bottom"`) para que la barra de estado quede siempre abajo, incluso al maximizar
- **Barra de progreso reubicada**: queda sobre el panel de botones, inmediatamente debajo del canvas
- **CPU en barra de estado**: porcentaje de uso de CPU actualizado cada 2s (requiere `psutil`)
- **Fix flickering**: canvas item persistente actualizado con `itemconfig` en vez de crear uno nuevo por frame
- **Fix distorsión de imagen**: letterbox correcto con `scale = min(pw/iw, ph/ih)` — sin estirado
- **Fix auto-resize al activar cámara**: `geometry()` con `WxH+x+y` bloquea el tamaño inicial; ventana no crece al aparecer texto largo en status
- **Fix placeholder descentrado**: `winfo_width() > 1` como guard antes de usar dims del canvas (evitaba bug donde `1 or 854` = `1`)
- **Fix tooltip layout shift**: `width=38` fijo en label de tooltip — no desplaza otros elementos al aparecer/desaparecer

### v1.4

- **Partición en módulos**: `ui_filters.py`, `ui_overlay.py`, `ui_about.py` — `app.py` reducido a ventana principal + coordinación
- **Rotación en tiempo real**: 0° / 90° / 180° / 270° con combobox en la UI principal
- **Tema Halloween**: paleta naranja/morada con decoración 🎃 👻 💀 en la barra de título
- **Tooltips en barra de estado**: descripción de cada botón al pasar el cursor
- **Preferencias extendidas**: filtros (brillo, contraste, saturación, blur), zoom, rotación y espejo ahora persisten en `prefs.json`
- Auto-guardado de `prefs.json` con debounce de 2s en cualquier cambio de preferencia
- Throttle del preview movido al hilo de stream para reducir carga en la UI
- Barra de zoom integrada en la UI principal (junto al botón de recorte)
- Eliminado el icono por defecto de la barra de título (Windows)

### v1.3

- Selección de región de captura de pantalla mediante drag interactivo
- Zoom direccional: el punto de zoom sigue el cursor sobre el preview; vuelve al centro al salir
- Preferencias persistentes: resolución, tema e idioma se guardan en `prefs.json` y se restauran al iniciar

### v1.2

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
