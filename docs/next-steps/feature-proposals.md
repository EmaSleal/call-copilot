# Propuestas de features — Call Copilot

Ideas evaluadas contra la arquitectura real del repo (no genéricas). Cada una
reutiliza subsistemas ya existentes en vez de pedir infraestructura nueva.
Ordenadas de menor a mayor riesgo/esfuerzo. Los 5 puntos están
implementados. El punto 5 es un MVP deliberado: cubre concurrencia y el
caso base de vida del proceso (validado contra Claude Desktop real), pero
deja afuera límite de duración, cancelación y reconciliación de jobs
huérfanos — ver su sección de riesgos abiertos.

## 1. Reporte HTML portable, con video embebido y acceso desde la TUI — ✅ IMPLEMENTADO

**Problema.** `src/video/report.py` referencia las keyframes por ruta
relativa al nombre de archivo. Si el `.html` se mueve o comparte sin la
carpeta de imágenes, el reporte queda roto. Además, `video.mp4` se
descarga completo en la misma carpeta de sesión (`src/video/pipeline.py`)
y nunca se borra, pero el reporte no lo usa — y no hay ninguna forma de
llegar al reporte desde la TUI, hay que ir a buscarlo a mano al
filesystem.

**Propuesta.** Empaquetar el reporte como `.zip` con manifest (report.html
+ keyframes + `video.mp4` si existe), agregando un `<video>` al HTML que
solo se muestra cuando el archivo de video está presente en el paquete.
Descartado el single-file HTML con base64: embeber un video de cientos de
MB en base64 es inviable, mientras que el zip resuelve el player gratis —
el video queda como asset referenciado por ruta relativa, igual que ya se
hace hoy con las keyframes. Sumar en `src/tui/tabs/video.py` un link/acción
en la lista de sesiones para abrir el reporte generado.

**Alcance.** `src/video/report.py` (empaquetado + player condicional) y
un cambio menor en `src/tui/tabs/video.py` (acción de apertura). Sin
trade-offs de diseño reales — es deuda técnica ya identificada más una
extensión natural del mismo paquete, no una feature nueva con riesgo
asociado.

**Prioridad sugerida.** Más alta relación esfuerzo/beneficio de las
cuatro, y la más potente de encarar primero: resuelve portabilidad,
agrega el player de video y cierra el gap de acceso desde la TUI en un
solo cambio acotado.

**Resultado real.** El player no necesitó zip: `report.html`, las
keyframes y `video.mp4` ya viven en el mismo `session_dir`
(`src/video/pipeline.py`), así que el `<video src="video.mp4">` se agregó
por ruta relativa igual que las keyframes existentes — sin cambiar el
formato del artefacto. El empaquetado zip se implementó como acción
**on-demand** (`export_report_zip()` en `src/video/report.py`, botón
"Exportar zip" en el modal de sesión), no automático en cada
procesamiento, para no duplicar `video.mp4` en disco en sesiones que
nunca se comparten. El zip excluye `audio.mp3` (artefacto interno de
transcripción). Además se sumó un botón "Abrir reporte" en
`SessionModal`/`src/tui/tabs/video.py` para acceder al `.html` sin salir
de la TUI. Tests: `tests/unit/test_video_report.py`.

## 2. Resource MCP para reportes ya generados — ✅ IMPLEMENTADO

**Problema.** El servidor MCP (`src/mcp/server.py`) expone datos
estructurados (segmentos, categorías, tools) pero no los `.html` que
`video/report.py` ya genera. `get_session` tampoco lo resuelve: su
`UnifiedSession` (`src/db/unified.py`) no tiene campo `html_report` — las
sesiones de llamada no tienen reporte, así que no forma parte del modelo
unificado video/llamada. Para llegar a un reporte hoy hay que ir a
buscarlo a mano en el filesystem.

**Propuesta.** Agregar un tool `list_reports` / `get_report_url` que
permita a un cliente MCP externo (Claude Desktop) linkear directo al
reporte de una sesión.

**Alcance.** Mismo patrón que los 5 tools ya registrados en
`build_server()` — mismo estilo, mismo límite de alcance (solo lectura).

**Resultado real.** Dos tools nuevas en `src/mcp/tools.py`, reutilizando
`database.get_video_sessions()` sin tocar el DAO: `list_reports(title_query=None)`
lista sesiones con reporte + URL `file://`, filtrable por substring de
título; `get_report_url(session_id)` es el equivalente puntual para un
cliente que ya tiene el id (p. ej. desde `get_session`). Ambas devuelven
`None`/omiten la fila si el `.html` fue borrado del disco después de
grabarse en la DB, en vez de devolver un link roto. Deliberadamente
**no** se expone el `export_report_zip()` del punto 1 acá — generar un
archivo desde un servidor documentado como "solo lectura" rompería esa
garantía; el zip se queda como acción manual desde la TUI. Registradas en
`build_server()`, documentadas en el README, tests en
`tests/mcp/test_tools.py` y `tests/mcp/test_integration.py`.

## 3. Trigger en vivo contra el catálogo de Tools — ✅ IMPLEMENTADO

**Problema.** El `TriggerDetector` dispara hoy solo por pregunta/silencio.
El catálogo de Tools con RAG (`src/rag/tools_store.py`,
`ToolsCatalogStore`) existe pero solo se consulta post-sesión — dos
subsistemas que conviven sin hablarse en tiempo real.

**Propuesta.** Cuando se detecte la mención de un tool durante la llamada,
disparar `semantic_search` contra el catálogo propio y devolver como
sugerencia el contexto de la última vez que se discutió ese tool.

**Riesgo a resolver antes de implementar (evaluación original).** El
pipeline en vivo hoy evita deliberadamente cualquier llamada LLM/vector-store
extra en el camino crítico (streaming, Haiku, heurística de pregunta sin
LLM) para no romper la latencia percibida. Hay que medir el costo de la
consulta a Chroma antes de meterla ahí — si no se puede mantener por
debajo del umbral perceptible, esta feature necesita rediseño (ej.
prefetch asíncrono) antes de salir a producción.

**Corrección tras investigar el código real.** La premisa de arriba es
parcialmente falsa: `_handle_trigger()` (`src/core/pipeline.py:254`) ya
llama `self._rag.search(query=block_text, top_k=5)` — un embedding de
OpenAI + Chroma — **en cada trigger, antes del LLM**, para el RAG de
segmentos de la sesión. El `TriggerDetector` (`src/trigger/heuristic.py`)
sí es heurística pura, pero el resto del hot path no evita llamadas de
red; ya paga una. Sumar una segunda consulta contra `ToolsCatalogStore`
es incremental, no una categoría de riesgo nueva — pero tampoco es gratis,
así que el diseño la trata como tal:

1. **Gate barato antes de gastar cualquier consulta**: matchear `block_text`
   contra los nombres normalizados del catálogo (`db.get_tools()` +
   `normalize_tool_name`, `src/db/tools.py:24-51`) — sin red, sin LLM.
2. **Sin UI nueva**: el contexto del tool se mezcla en el mismo
   `rag_context` que ya se inyecta al prompt (`pipeline.py:254`) — reusa
   `OutputSink`/`#suggestion-live`/`#suggestion-log` (`src/tui/tabs/call.py`)
   sin widget nuevo; el LLM decide si lo menciona.

**Resultado real — más simple aún que el diseño de arriba.** Al
implementar, `ToolsCatalogStore.search()` (embedding semántico) resultó
innecesario: el gate de matching exacto contra `normalized_name`
(`src/db/tools.py`) ya resuelve el `tool_id` sin ambigüedad, así que no
hay nada que desambiguar con una búsqueda semántica — agregarla habría
sido una llamada de red de más sin ganancia real. El diseño final no
agrega **ninguna** llamada de red nueva al hot path, ni falta hacer
`asyncio.gather`: es puro regex en memoria + una lectura sqlite
(`get_tool_mentions`), condicional a que haya match.

Nuevo módulo puro `src/processing/live_tool_context.py`:
- `detect_mentioned_tools(text, tools)`: regex `\bnombre_normalizado\b`
  case-insensitive contra cada tool del catálogo (cacheado una vez en
  `CallCopilotPipeline._known_tools` al llamar `start()`); ignora nombres
  de menos de 3 caracteres para no matchear ruido dentro de otras
  palabras (ej. "Go" dentro de "Google").
- `build_live_tool_context(tools)`: por cada tool detectado, busca su
  mención más reciente vía `get_tool_mentions()` (`src/db/tool_mentions.py`
  — poblada post-sesión por `tool_extractor.py::ingest_tools`) y arma una
  línea con el `context_snippet` de esa última vez, ignorado si el tool
  nunca fue mencionado antes.

`_handle_trigger()` (`src/core/pipeline.py`) llama a ambas justo después
del RAG de segmentos existente y concatena el resultado a `rag_context`
antes de armar `base` — cero cambios en la firma de `self.llm.respond()`
ni en la TUI. Tests: `tests/unit/test_live_tool_context.py` (9 casos) +
`tests/integration/test_pipeline_live_tool_context.py` (3 casos,
mismo harness que `test_pipeline_rolling_buffer.py`).

**Prioridad sugerida.** La más alineada al caso de uso original del
proyecto (asistir en vivo). Terminó siendo, además, la de menor riesgo de
las cuatro: no agrega ninguna llamada de red al camino crítico.

## 4. Escritura acotada en el servidor MCP (aprobación de pending actions) — ✅ IMPLEMENTADO

**Problema.** El servidor MCP es hoy 100% read-only por diseño. El
mecanismo "agente propone, humano aprueba" (`pending_actions`,
`audit_log`, `src/agent/maintenance.py`) ya existe para las tabs de
Aprobaciones en la TUI, pero solo es accesible ahí.

**Propuesta.** Agregar tools de escritura muy acotados —
`approve_pending_action`, `reject_pending_action` — que reutilicen la
lógica de validación/marcado/logging que ya vive en
`src/agent/maintenance.py`, para poder aprobar o rechazar deletes del
catálogo desde Claude Desktop sin abrir la TUI.

**Riesgo a resolver antes de implementar.** Rompe la premisa "solo
lectura" que hoy es el argumento de seguridad del servidor MCP en el
README. Debe quedar explícito en la documentación y probablemente detrás
de un flag de configuración explícito, no habilitado por default.

**Corrección tras investigar el código real.** El doc apuntaba al archivo
equivocado: `approve_pending_action`/`reject_pending_action` viven en
`src/agent/commands.py` (líneas 79-91), no en `maintenance.py` (ese es
solo el loop de tool-calling que *propone*). Hoy solo hay dos tipos de
acción registrados — `delete_category`/`delete_tool` — nada de
video/call. Un hallazgo que quedó fuera de este alcance pero vale
documentar: `db.resolve_pending_action()` no escribe en `audit_log` por
sí sola (el registro depende de que el handler del comando lo haga, y
esos handlers están hardcodeados a `actor="agent"` sin importar quién
aprobó) — comportamiento preexistente e idéntico al de la TUI, no
introducido por esta feature.

**Resultado real.** Dos tools nuevas en `src/mcp/tools.py`,
`approve_pending_action`/`reject_pending_action`, envolviendo
`src.agent.commands` sin tocarlo. Ambas devuelven `{"ok": True}` o
`{"ok": False, "error": ...}` en vez de dejar cruzar la excepción cruda
al protocolo MCP — `reject_pending_action` en particular chequea el id
explícitamente antes de llamar al DAO, porque `resolve_pending_action`
hace no-op silencioso sobre un id inexistente (un `UPDATE` que no matchea
ninguna fila) y sin ese chequeo el cliente leería un falso `{"ok": True}`.
`resolved_by` default es `"mcp-client"`, no `"human"`, para que
`pending_actions.resolved_by` distinga de dónde vino la aprobación.

**Gate**: `MCP_ALLOW_APPROVALS=true` en `build_server()`
(`src/mcp/server.py`) — apagado por default, las dos tools ni siquiera se
registran (no aparecen en `list_tools`) sin la variable. Verificado con
un cliente MCP real (proceso `call-copilot-mcp` instalado, protocolo
stdio real): sin la variable, 7 tools; con `MCP_ALLOW_APPROVALS=true`,
9. Detalle operativo que quedó documentado en el README: un cliente MCP
(Claude Desktop incluido) no hereda el entorno del shell al lanzar el
proceso — la variable tiene que ir en el `env` de la config del cliente.
Tests: `tests/mcp/test_tools.py` (4 casos) + `tests/mcp/test_integration.py`
(3 casos: default off, `"true"` la activa, cualquier otro valor la deja
apagada).

**Prioridad sugerida.** La más barata de construir (la lógica de negocio
ya existe), pero la que más impacto tiene sobre el modelo de seguridad
actual — requiere decisión consciente, no solo implementación.

## 5. Procesar video disparado desde un cliente MCP externo — ✅ IMPLEMENTADO (MVP)

**Problema.** Hoy la única forma de que call-copilot procese un video
(descarga con yt-dlp, transcripción Whisper, clasificación LLM, keyframes,
reporte) es arrancarlo a mano desde la TUI
(`src/tui/tabs/video.py::_process_video`). Un cliente MCP externo (Claude
Desktop) puede leer reportes ya generados (punto 2) pero no puede pedir
que se genere uno nuevo — tiene que volver a la TUI para eso.

**Propuesta.** Dos tools nuevas, complementarias, sobre el patrón
fire-and-forget + poll (nunca un tool que bloquea hasta terminar):

- `start_video_processing(url: str) -> {"session_id": int, "status": "pending"}`
  — crea la sesión (mismo `db.create_video_session` que usa la TUI) y
  lanza `run_pipeline()` en background sin esperar a que termine.
- `get_video_processing_status(session_id: int) -> {"status": ..., "report_url": ... | None, "error_msg": ... | None}`
  — poll sobre `video_sessions.status`, mismo shape que ya expone
  `list_reports`/`get_report_url` del punto 2.

**Riesgos identificados (a resolver antes de implementar, no solo
documentar).**

1. **`run_pipeline()` es síncrono, bloqueante y sin timeout**
   (`src/video/pipeline.py:37`, docstring explícito: "llamarlo siempre
   desde run_in_executor") — minutos de CPU/GPU (Whisper) + red (yt-dlp) +
   subprocess (ffmpeg), sin ningún límite hoy. Un tool que lo esperara
   (`await asyncio.to_thread(run_pipeline, ...)` completo, como hacen las
   7 tools de lectura actuales) dejaría la llamada MCP colgada minutos —
   inaceptable. Única opción viable: `asyncio.create_task(asyncio.to_thread(...))`
   sin awaitear, devolviendo el `session_id` de inmediato.

2. **Vida del proceso stdio durante el job en background** — el riesgo
   más serio, y el que menos se resuelve solo leyendo código.
   **Validado empíricamente contra Claude Desktop real** (ver sección de
   abajo): sí sobrevive un job de 3 minutos en reposo. Sigue habiendo
   matices sin cerrar (ver validación) — jobs más largos, app en segundo
   plano, o standby del sistema operativo no se probaron.

3. **Superficie de agotamiento de recursos.** A diferencia del punto 4
   (que solo resuelve decisiones ya vetadas por el agente interno), esto
   origina trabajo nuevo desde una URL arbitraria que manda un cliente
   externo — sin límite de tamaño de video, sin control de jobs
   concurrentes, sin validación de dominio. Un cliente MCP con errores (o
   mal intencionado) podría encolar videos de varias horas y llenar disco
   o saturar CPU. Mitigaciones a definir antes de implementar:
   - **Concurrencia = 1**: ✅ resuelto y validado — ver Hallazgo 3 en la
     sección de validación empírica. `try_start_processing_session()`
     (`src/db/video_sessions.py`) reemplaza el chequeo ingenuo original
     (que tenía una carrera real) por un claim atómico vía `BEGIN
     IMMEDIATE`.
   - **Flag propio**, separado de `MCP_ALLOW_APPROVALS` — perfil de riesgo
     distinto, apagado por default (ej. `MCP_ALLOW_VIDEO_PROCESSING=true`).
   - Posible límite de duración antes de descargar completo: yt-dlp puede
     consultar metadata sin descargar (`--dump-json`) para cortar antes de
     gastar ancho de banda en algo de varias horas.

4. **Sin cancelación.** No existe hoy ningún mecanismo para abortar un
   pipeline en curso, ni desde la TUI. Si un cliente MCP arranca un job
   por error, no hay forma de pararlo salvo matar el proceso entero —
   perdiendo también cualquier otro tool call en curso en esa misma
   conexión stdio.

**Alcance estimado.** Dos tools nuevas en `src/mcp/tools.py` + gate propio
en `build_server()` (mismo patrón que el punto 4) + chequeo de
concurrencia. Reutiliza `db.create_video_session`/`update_session_status`/
`run_pipeline` sin tocarlos.

### Validación empírica contra Claude Desktop real

Se armaron dos prototipos aislados (fuera de `src/`, nunca tocaron código
de producción) y se probaron contra la instalación real de Claude
Desktop del usuario (`~/.config/Claude/claude_desktop_config.json`,
backupeado antes de tocarlo y restaurado al terminar).

**Hallazgo 0 — bug real encontrado y arreglado de paso.** La primera
prueba (7 tools de solo lectura ya implementadas, sin nada de punto 5)
falló con `"unable to open database file"`. Causa: `app_home()`
(`src/core/paths.py`) devolvía `Path(".")` en dev checkouts — relativo al
`cwd` del proceso que lo llama, no a la raíz del repo. Nunca se notó
porque siempre se lanzaba todo desde la raíz del repo; Claude Desktop lo
lanzó desde otro `cwd` y expuso el bug. **Esto afectaba a los puntos 2 y 4
ya implementados**, no solo a esta investigación — cualquier uso real de
`call-copilot-mcp` desde un cliente externo en un dev checkout estaba
roto. Arreglado (`app_home()` ahora devuelve la raíz absoluta del repo,
`tests/unit/test_paths.py` actualizado, TDD) — un efecto colateral fue
tener que normalizar una fila vieja de la DB real (`html_report` con ruta
relativa grabada desde antes del fix).

**Hallazgo 1 — el proceso NO es único ni persistente por sesión.**
Confirmado con logging de lifecycle (pid + timestamp por start/exit/señal):
Claude Desktop lanzó **3 procesos** del mismo servidor configurado en 2
segundos, con **2 corriendo en simultáneo** en un momento dado (ambos
hijos directos del proceso `claude-desktop`, confirmado con `ps -o ppid`).
Esto **confirma, no solo hipotéticamente**, que cualquier estado de
coordinación (ej. "hay un video procesándose") tiene que vivir en
almacenamiento compartido (la DB), nunca en memoria de un proceso — pero
también, como se ve en el Hallazgo 3 de abajo, que un simple
"leer con `db.get_video_sessions(status_filter="processing")`, después
escribir" no alcanza: dos procesos reales pueden ejecutar esa lectura al
mismo tiempo, antes de que cualquiera escriba.

**Hallazgo 2 — un job de 3 minutos en background sobrevivió intacto.**
Segundo prototipo: un servidor MCP aislado con dos tools,
`start_slow_job`/`get_slow_job_status`, que simulan exactamente la forma
fire-and-forget + poll propuesta arriba — `asyncio.create_task(asyncio.to_thread(time.sleep(180)))`
sin awaitear, estado persistido en un archivo JSON (haciendo de stand-in
de `video_sessions.status`). Se arrancó el job desde Claude Desktop real,
y **sin ninguna otra llamada de por medio** (para no mantener el proceso
"caliente" artificialmente) pasaron los 3 minutos completos. Resultado,
confirmado por log — mismo PID (1724633) arrancó y terminó el job:

```
15:16:04 pid=1724633 job_started   job_id=job-1787433364
15:16:04 pid=1724633 job_thread_start
15:19:04 pid=1724633 job_thread_done   ← exactamente 180s después
```

Claude Desktop no mató ni recicló ese proceso mientras el job corría en
background, en este escenario concreto (app abierta, sin otra actividad,
~3 minutos).

**Límite real de esta validación** — la prueba terminó de forma
interrumpida: se cortó la luz de la casa a mitad de la verificación final
(confirmar el resultado también a través de una llamada real a
`get_slow_job_status`, no solo leyendo el archivo de estado desde afuera).
El corte reinició la máquina completa — **no fue Claude Desktop matando
el proceso por su cuenta**, así que no contradice el Hallazgo 2, pero
tampoco alcanzamos a cerrar esa última confirmación end-to-end. Lo que
sigue sin probar: jobs más largos que 3 minutos (un video real puede
tardar bastante más), la app en segundo plano o minimizada, y standby/
suspensión del sistema operativo.

**Hallazgo 3 — el gate de concurrencia=1 propuesto tenía una carrera real,
ya corregida.** Directamente motivado por el Hallazgo 1 (procesos
concurrentes de verdad, no hipotéticos): "leer con
`get_video_sessions(status_filter="processing")`, después insertar si no
hay nada" es un time-of-check-to-time-of-use clásico — dos procesos
pueden hacer la lectura al mismo tiempo, ambos ven "nada procesando",
ambos insertan. Se reemplazó por `try_start_processing_session()`
(`src/db/video_sessions.py`), que envuelve el chequeo + insert en una
única transacción `BEGIN IMMEDIATE` (toma el lock de escritura de SQLite
antes de leer, no después de escribir). Validado con un test de
integración real — 8 procesos del SO (no threads; `multiprocessing`
con contexto `fork`) atacando la misma DB en simultáneo,
`tests/integration/test_video_processing_concurrency_guard.py` — y
confirmado por mutación manual: la versión ingenua (sin `BEGIN
IMMEDIATE`) fallaba el test 10/10 corridas, la versión con el fix lo pasó
15/15.

**Conclusión.** El riesgo #2 pasa de "incertidumbre total, no resoluble
leyendo código" a "validado en el caso base (app abierta y activa,
~3 min)". El diseño fire-and-forget + poll respaldado por la DB (no por
memoria de proceso) queda respaldado por evidencia directa, no solo por
precaución. Antes de implementar en serio, valdría la pena repetir la
prueba con una duración más realista (10-15 min) y con la app en segundo
plano, dado que esta corrida se interrumpió por causas externas antes de
cubrir esos casos.

**Prioridad sugerida.** Sigue siendo la de mayor riesgo de las cinco por
la superficie de agotamiento de recursos (riesgo #3, sin cambios) y la
falta de cancelación (riesgo #4) — pero el riesgo #2, que era el bloqueo
principal para siquiera diseñarla con confianza, ya no es una
incertidumbre completa.

### Resultado real (MVP)

- `src/db/video_sessions.py::try_start_processing_session(title, url)` —
  el claim atómico validado en el Hallazgo 3. Crea la sesión directo en
  `status="processing"` (sin pasar por `"pending"`, a diferencia del flujo
  normal de la TUI) o devuelve `None` si ya hay una procesándose.
- `src/video/pipeline.py::run_pipeline()` gana un parámetro opcional
  `session` — si se lo pasan (ya reservado atómicamente), salta el
  `_get_title()`+`create_video_session()` internos en vez de crear una
  segunda fila duplicada; sin el parámetro, comportamiento idéntico al de
  siempre (la TUI no cambia). Extraído a `_resolve_session()`, testeado en
  aislamiento — `run_pipeline()` en sí sigue sin test propio, mismo
  criterio que ya usaba el proyecto (mockear whisper/yt-dlp completo no
  vale la pena para esto).
- `src/mcp/tools.py`: `start_video_processing(url)` — obtiene el título
  (yt-dlp, acotado), reclama el slot atómicamente, y recién ahí lanza
  `run_pipeline()` como tarea de fondo (`asyncio.create_task` sin
  awaitear) — la llamada MCP nunca espera al pipeline completo.
  `get_video_processing_status(session_id)` — poll de solo lectura,
  reusa el mismo `_report_url()` helper del punto 2.
- Gate propio en `build_server()`: `MCP_ALLOW_VIDEO_PROCESSING=true`,
  independiente de `MCP_ALLOW_APPROVALS` — perfil de riesgo distinto,
  apagado por default, verificado que ambos flags no se pisan entre sí.
- Verificado con cliente MCP real (proceso `call-copilot-mcp` instalado):
  9 tools con el flag activo, `get_video_processing_status` responde
  correctamente sobre un id inexistente a través del protocolo stdio real
  — no se disparó ninguna descarga real como parte de esta verificación
  (deliberado: hubiera consumido red/CPU sin necesidad).
- Tests: `tests/integration/test_video_processing_concurrency_guard.py`
  (3 casos, incluida la carrera con 8 procesos reales),
  `tests/unit/test_video_pipeline_resolve_session.py` (2 casos),
  `tests/mcp/test_tools.py` (6 casos), `tests/mcp/test_integration.py`
  (3 casos nuevos de gating).

**Lo que queda deliberadamente fuera de este MVP** (riesgos #3/#4, sin
resolver):
- Límite de duración del video antes de descargar completo (yt-dlp
  `--dump-json` para cortar videos de varias horas antes de gastar ancho
  de banda).
- Cualquier mecanismo de cancelación — coincide con la limitación actual
  de la TUI, no es una regresión de esta feature.
- Reconciliación de sesiones `"processing"` huérfanas (un proceso que
  muere a mitad de un job dejaría la fila colgada para siempre; el
  Hallazgo 2 sugiere que es poco frecuente en el caso base, pero no
  imposible).
