# 🧬 Mr. ADN — Desktop AI Assistant

> *"Life, uh... finds a way."* — Dr. Malcolm  
> *"Your desktop, uh... finds help."* — Mr. ADN

Un asistente de escritorio flotante con estética **Mr. DNA de Jurassic Park**, inteligencia contextual, telemetría pasiva de ventanas y aprendizaje por refuerzo simple.

---

## 🚀 Inicio Rápido

### 1. Configurar entorno virtual e instalar dependencias

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. Configurar API Key

```powershell
copy .env.example .env
# Editar .env y agregar: GEMINI_API_KEY=tu_clave_aqui
```

### 3. Validar entorno

```powershell
.venv\Scripts\python.exe scripts\validate_env.py
```

### 4. Ejecutar

```powershell
.venv\Scripts\python.exe main.py
```

---

## 📁 Estructura del Proyecto

```
Mr. ADN/
├── main.py                    # Entry point
├── requirements.txt
├── .env.example
├── config/
│   └── config.json            # Toda la configuración
├── core/
│   ├── config_manager.py      # Dot-path config access
│   ├── database.py            # SQLite (historial + bandit)
│   └── event_bus.py           # Bus de eventos in-process
├── ai/
│   ├── brain.py               # Cerebro: Gemini / OpenAI / Ollama
│   └── bandit.py              # UCB1 Bandit para proactividad
├── telemetry/
│   ├── window_monitor.py      # Win32: ventana activa + taskbar
│   ├── monitor_detector.py    # Detección multi-monitor
│   └── screen_capture.py      # Captura de región con mss+Pillow
├── ui/
│   ├── main_window.py         # Ventana principal (frameless, always-on-top)
│   ├── sprite_widget.py       # ADN animado (sprites o procedural)
│   ├── chat_bubble.py         # Globo de respuesta con streaming
│   ├── chat_input.py          # Barra de entrada de texto
│   ├── capture_overlay.py     # Overlay para selección de región
│   ├── hotkey_manager.py      # Atajos globales (pynput)
│   └── settings_dialog.py     # Diálogo de configuración
├── scripts/
│   └── validate_env.py        # Validador de entorno
└── assets/
    └── sprites/
        ├── idle/              # PNGs para estado idle (opcional)
        ├── thinking/          # PNGs para estado thinking
        └── talking/           # PNGs para estado talking
```

---

## ⌨️ Atajos Globales

| Atajo | Acción |
|-------|--------|
| `Ctrl+Alt+M` | Abrir chat |
| `Ctrl+Alt+S` | Capturar región de pantalla |
| `Ctrl+Alt+Z` | Silenciar / Activar |

Configurables en `config/config.json` → sección `hotkeys`.

---

## 🤖 Proveedores de IA

Cambia en `config.json → ai.provider`:

| Provider | Config | API Key |
|----------|--------|---------|
| `gemini` | model: `gemini-3.8-flash` | `GEMINI_API_KEY` en `.env` |
| `openai` | model: `gpt-4o-mini` | `OPENAI_API_KEY` en `.env` |
| `ollama` | model: `llama3.2:3b` | no requiere (local) |

---

## 🧠 Bandit Algorithm (Proactividad)

El **UCB1 Multi-Armed Bandit** ajusta automáticamente con qué frecuencia Mr. ADN genera mensajes espontáneos:

- **Interactuó** → recompensa `+1.0` → más proactivo
- **Ignoró** → recompensa `0.0` → sin cambio
- **Silenciaste** → recompensa `-0.5` → menos frecuente + cooldown 5min

Los stats se pueden ver en el menú derecho → **📊 Estadísticas Bandit**.

---

## 🎨 Sprites (opcional)

Sin sprites: el sistema dibuja una **doble hélice de ADN animada** proceduralmente (comportamiento por defecto).

Con sprites: coloca archivos PNG numerados en:
```
assets/sprites/idle/0001.png, 0002.png, ...
assets/sprites/thinking/0001.png, ...
assets/sprites/talking/0001.png, ...
```

---

## 🖥️ Multimonitor

Mr. ADN detecta todos los monitores y se clampa para no salir de la pantalla al arrastrarlo entre monitores. La posición se guarda en `data/position.json`.

---

## ⚙️ Configuración Rápida

```json
// config/config.json (fragmentos clave)
{
  "ai": { "provider": "gemini", "model": "gemini-3.8-flash" },
  "ui": { "window": { "opacity": 0.95 }, "input_mode": "text" },
  "bandit": { "initial_proactivity": 0.3, "min_interval_between_interruptions_sec": 120 },
  "hotkeys": { "global_invoke": "<ctrl>+<alt>+m" }
}
```

---

## 🔐 Seguridad

- Las API keys **nunca** se guardan en `config.json` — solo en `.env` (ignorado por git).
- El `.gitignore` excluye `.env`, `data/` y los logs.
