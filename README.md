# Call Copilot
 
[![CI](https://github.com/EmaSleal/call-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/EmaSleal/call-copilot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/EmaSleal/call-copilot)](https://github.com/EmaSleal/call-copilot/releases)
 
![Unified Copilot](docs/assets/promo-banner.svg)
 
TUI (Textual) para **Call Copilot**: transcripción en vivo de una llamada +
sugerencias de un LLM, disparadas por fin de turno o pregunta detectada.
 
## Arquitectura
 
```
AudioSource ──► VAD (Silero) ──► STTProvider ──► TriggerDetector ──► LLMProvider ──► OutputSink
(Pulse/WASAPI)   (fin de turno)   (Deepgram/         (pregunta /                      (TUI en vivo)
                                    Whisper local)     silencio)
```
 
Cada bloque está definido como interfaz en `src/core/interfaces.py`. El
pipeline (`src/core/pipeline.py`) orquesta sin conocer implementaciones
concretas — la elección de provider concreto vive en `src/tui/bootstrap.py`
(usado por la TUI) y, para el modo sin TUI, en `main.py`.
 
### La TUI (`src/tui/app.py`) — uso normal
 
Cinco tabs, todas sobre la misma base de datos:
 
| Tab | Qué hace |
|---|---|
| **[1] Call Copilot** | Transcripción en vivo de una llamada + sugerencias del LLM en tiempo real. Perfil activo, selector de dispositivo de audio, botón de Configuración. |
| **[2] Buscar** | Full-text search sobre los segmentos ya clasificados. |
| **[3] Categorías** | CRUD de la taxonomía de categorías — un nivel de subcategorías (`└─`), color por categoría. |
| **[4] Historial** | Sesiones de llamada (vista `unified_sessions`/`unified_segments` en SQLite). |
| **[5] Tools** | Catálogo de tecnologías/herramientas mencionadas en las llamadas, extraídas automáticamente post-sesión (`src/processing/tool_extractor.py`) o importadas desde tech-scout. Búsqueda por substring de nombre. |
 
`Ctrl+S` abre el panel de **Configuración** (modal) desde cualquier tab:
idioma de la interfaz (Español/English, cambia en caliente sin reiniciar),
proveedor LLM/STT en tiempo real, API keys (OpenAI/Anthropic/Deepgram),
tamaño de modelo Whisper por uso, el umbral de silencio del VAD, y un botón
para importar el catálogo de Tools desde una base externa (tech-scout, un
proyecto personal separado) — todo persistido directo a `.env`.
 
### `main.py` — modo alternativo sin TUI
 
Pipeline de consola equivalente, sin Textual — útil para debug rápido o si
no querés la interfaz. Mismas variables de entorno, misma lógica de
selección de provider (duplicada intencionalmente respecto a
`src/tui/bootstrap.py`: son dos entrypoints independientes, no una capa
compartida).
 
## Por qué estas decisiones
 
- **VAD real (Silero), no timeout fijo.** El trigger genuino es "la otra
  persona dejó de hablar", no "pasaron N segundos" ni "se acumularon N
  oraciones". El umbral de silencio (`SILENCE_THRESHOLD_MS`, default 2000ms)
  es configurable desde el panel de Configuración, pero requiere reiniciar
  la app — queda congelado en un singleton cargado antes de que Textual
  abra la terminal (`src/tui/bootstrap.py::_preload_models`).
- **Heurística de pregunta sin LLM extra.** Regex + signos de interrogación
  dispara en microsegundos. Una confirmación vía LLM agregaría latencia
  perceptible en una llamada en vivo.
- **STT intercambiable desde el día uno.** `STT_BACKEND=deepgram` para
  latencia mínima en la nube, `STT_BACKEND=whisper_local` para correr local
  sin costo recurrente ni dependencia de red. Mismo contrato
  (`STTProvider`), cero cambios en el resto del pipeline.
- **Audio de captura intercambiable por SO.** `PulseLoopbackSource` en Linux
  (con selector manual de sink desde la TUI — el sink "default" del sistema
  puede no ser el que realmente está sonando), `WASAPILoopbackSource` en
  Windows. Mismo contrato `AudioSource`.
- **Claude Haiku, no Sonnet/Opus, cuando `LLM_BACKEND=claude`.** Para una
  sugerencia de 2-3 oraciones en tiempo real, la latencia importa más que
  el razonamiento profundo. Con `LLM_BACKEND=gpt` (default) la elección es
  dinámica: nano/mini según `LLM_TOKEN_THRESHOLD`.
- **Streaming obligatorio en el LLM.** Ver las primeras palabras mientras
  el modelo sigue generando es la diferencia entre "útil en vivo" y
  "llegó tarde a la conversación".
- **Perfiles de llamada** (`src/profiles/`) — cada perfil define su propio
  `system_prompt_addon`, heurísticas de modo conservador, `response_mode` y
  override de modelo opcional. Gestionables desde la TUI sin editar código.
- **RAG opcional** (`src/rag/chroma_store.py`) — ChromaDB + embeddings de
  OpenAI para dar contexto de sesiones pasadas al LLM durante la llamada.
  Categorías (`src/rag/categories_store.py`) usa el mismo mecanismo para
  detectar duplicados al sugerir categorías nuevas desde Historial, con
  fallback a un juez LLM cuando no hay `OPENAI_API_KEY`.
- **Idioma de la UI en caliente, sin reiniciar** (`src/i18n/`) — cambiar
  Español/English desde Configuración reescribe en el momento los textos de
  todas las pantallas montadas (`App.retranslate_all()`), sin recomponer
  widgets ni perder estado en curso (transcripción viva, formularios a
  medio llenar). Única excepción: los atajos del footer se resuelven una
  sola vez al arrancar el proceso — cambiar el idioma no los actualiza
  hasta el próximo reinicio, porque Textual no expone una forma de
  reasignarlos en caliente.
## Instalación
 
Sin clonar el repo — instala como comando global vía [pipx](https://pipx.pypa.io)
(el script clona internamente):
 
```bash
curl -fsSL https://raw.githubusercontent.com/EmaSleal/call-copilot/main/install.sh | sh
```
 
En Windows (PowerShell):
 
```powershell
irm https://raw.githubusercontent.com/EmaSleal/call-copilot/main/install.ps1 | iex
```
 
Pregunta qué perfil instalar y arma el comando `call-copilot`. Config y
datos quedan en `~/.call-copilot/` (Linux/macOS) o `$HOME\.call-copilot\`
(Windows), no en el directorio del repo.
 
| Perfil | Incluye |
|---|---|
| Mínimo (default) | solo llamadas en vivo (Deepgram + GPT/Claude/Ollama) |
| Completo | + Whisper local (STT), catálogo de tools con RAG |
| A mano | elegís cada extra por separado |
 
También instalable directo con los extras de `pyproject.toml` (`whisper-local`,
`rag`, `mcp`, o `full` para los tres):
 
```bash
pipx install "call-copilot[whisper-local,rag] @ git+https://github.com/EmaSleal/call-copilot.git@main"
```
 
### Comandos
 
| Comando | Qué hace |
|---|---|
| `call-copilot` | arranca la TUI |
| `call-copilot --help` | lista los comandos (`-h` / `help` también andan) |
| `call-copilot version` | versión y commit instalado |
| `call-copilot check-update` | avisa si hay una versión nueva, sin instalarla |
| `call-copilot update` | instala la última versión |
| `call-copilot doctor` | diagnóstico: pipx, Python, extras opcionales, GPU/CUDA |
| `call-copilot install-mcp` | agrega el extra `mcp` (servidor MCP de solo lectura) a una instalación existente |
| `call-copilot uninstall` | desinstala (config/datos en `~/.call-copilot` quedan) |
 
## Setup (desde el repo, para desarrollo)
 
```bash
pip install -r requirements.txt
```
 
Copiá `example.env` a `.env` y completá lo que necesites, o arrancá la app
y configurá todo desde el panel de Configuración (`Ctrl+S`) — se persiste
solo a `.env`.
 
Siempre necesario: la API key del `LLM_BACKEND` que elijas
(`OPENAI_API_KEY` o `ANTHROPIC_API_KEY`). Si usás `STT_BACKEND=deepgram`,
también `DEEPGRAM_API_KEY`. `STT_BACKEND=whisper_local` no necesita key,
pero la primera ejecución descarga el modelo configurado.
 
## Correr
 
```bash
./run.sh                # crea/activa el venv e inicia la TUI
# o, con el venv ya activado:
python src/tui/app.py
 
# modo consola, sin TUI:
python main.py
```
 
## Base de datos
 
SQLite en `data/app.db` corriendo desde el repo, o `~/.call-copilot/data/app.db`
si instalaste vía pipx/`install.sh` (`src/core/paths.py` resuelve cuál según
si hay un checkout de git al lado del código corriendo). Seis tablas —
`categories`, `call_sessions`, `call_segments`, `tools`, `tool_mentions`,
`audit_log` — más dos vistas de solo lectura (`unified_segments`,
`unified_sessions`) sobre `call_sessions`/`call_segments` que alimentan el
tab Historial, con un campo `source` que queda por compatibilidad hacia
adelante. `tools`/`tool_mentions` alimentan el tab Tools — un tool
mencionado en varias llamadas es una sola fila en `tools` con una
`tool_mention` por cada mención (nunca se pisa el enriquecimiento del
LLM). `audit_log` registra cada delete humano sobre categorías/tools/
sesiones (actor, acción, fila) — no hay cola de aprobación: un delete
manual se ejecuta directo.
 
## Servidor MCP
 
`call-copilot-mcp` es un servidor [MCP](https://modelcontextprotocol.io)
de solo lectura (stdio) que expone los datos guardados por call-copilot —
historial de sesiones, categorías, catálogo de Tools y búsqueda de
contenido — a un cliente MCP externo (por ejemplo Claude Desktop), sin
tocar la TUI. Es un proceso separado y liviano: no importa `src.tui.*` ni
arrastra Textual.
 
Si ya tenés call-copilot instalado, la forma más simple es:

```bash
call-copilot install-mcp
```

Inyecta el extra en la instalación existente (`pipx inject`) y lo agrega
al perfil guardado en `~/.call-copilot/install-profile`, para que
`call-copilot update` no lo pise en la próxima actualización.

También instalable desde cero, mismo patrón que los extras
`whisper-local,rag` de más arriba:

```bash
pipx install "call-copilot[mcp] @ git+https://github.com/EmaSleal/call-copilot.git@main"
```
 
Tools que expone:
 
| Tool | Qué hace |
|---|---|
| `search_content` | búsqueda combinable sobre segmentos de llamadas (`category_id`, `technology`, `title_query`, `text_query`, `source`), siempre acotada por `limit`/`offset` |
| `list_categories` | taxonomía completa de categorías y subcategorías |
| `list_tools_catalog` | catálogo de Tools, con filtro opcional por substring |
| `get_session` | una sesión de llamada más todos sus segmentos, en un solo llamado |
| `semantic_search` | búsqueda semántica (embeddings) sobre segmentos de llamadas — best-effort, ver abajo |
 
`semantic_search` depende de `chromadb` y `OPENAI_API_KEY`; si cualquiera
de los dos falta en el entorno del servidor, devuelve una lista vacía en
vez de fallar — un resultado vacío no significa que el servidor esté roto,
solo que la búsqueda semántica no está disponible (usá `search_content`
para resultados garantizados).
 
Al ser un proceso stdio separado, no hereda el entorno de la TUI: necesita
las mismas variables de entorno que lee la TUI (mismo `.env`, vía
`load_dotenv()`) — típicamente ninguna es estrictamente obligatoria salvo
`OPENAI_API_KEY` si querés `semantic_search` funcionando.
 
Además existe una superficie de escritura opcional (`save_tool`),
**apagada por default**, flag: `MCP_ALLOW_TOOL_INGESTION=true`. Importante:
un cliente MCP (Claude Desktop incluido) **no hereda el entorno del
shell** al lanzar el proceso — la variable tiene que ir en el `env` de la
config del cliente, no alcanza con exportarla en la terminal.
 
## Pendiente / próximos pasos
 
1. **Captura de pestaña de navegador (`tabCapture`)** — no implementada.
   En la práctica, `PulseLoopbackSource`/`WASAPILoopbackSource` ya capturan
   el audio de salida a nivel de sistema operativo, así que una llamada por
   navegador ya se graba igual. Un `tabCapture` real (vía extensión de
   Chrome) solo aportaría algo si necesitás aislar una pestaña específica
   cuando hay más de una sonando a la vez — es una arquitectura distinta
   (extensión + servidor local), no una clase más de `AudioSource`.
2. **TTS como `OutputSink` alternativo** — hoy la única salida es la TUI en
   vivo (`TUIOutput` en `src/tui/tabs/call.py`). Un overlay flotante o TTS
   quedan como opciones no exploradas, sin que nada del código bloquee
   agregarlas (`OutputSink` es una interfaz chica).
3. **Tuning de `SILENCE_THRESHOLD_MS`** — ya expuesto en el panel de
   Configuración (rango 100-5000ms, default 2000), pero el valor correcto
   sigue dependiendo de cómo hablás vos y con quién — ajustar
   empíricamente una vez que esté corriendo.
