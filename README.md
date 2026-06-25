# Call Copilot

Pipeline de transcripción en vivo + LLM para sugerir respuestas en llamadas,
disparado por silencio (fin de turno) o detección de pregunta.

## Arquitectura

```
AudioSource ──► VAD (Silero) ──► STTProvider ──► TriggerDetector ──► LLMProvider ──► OutputSink
(WASAPI)         (silencio)       (Deepgram/         (pregunta /                      (consola,
                                    Whisper local)      silencio)                     placeholder)
```

Cada bloque está definido como interfaz en `src/core/interfaces.py`. El
pipeline (`src/core/pipeline.py`) orquesta sin conocer implementaciones
concretas — `main.py` es el único lugar donde se decide qué provider usar.

## Por qué estas decisiones

- **VAD real (Silero), no timeout fijo.** El trigger genuino es "la otra
  persona dejó de hablar", no "pasaron N segundos" ni "se acumularon N
  oraciones" (como hacía el enfoque de fact-checking del que partimos).
- **Heurística de pregunta sin LLM extra.** Regex + signos de interrogación
  dispara en microsegundos. Una confirmación vía LLM agregaría 200-400ms
  por cada evaluación — en una llamada en vivo eso se nota. Queda como
  mejora futura si la heurística sola da demasiados falsos positivos.
- **STT intercambiable desde el día uno.** `STT_BACKEND=deepgram` para
  latencia mínima en la nube, `STT_BACKEND=whisper_local` para correr en
  tu RTX 4060 sin costo recurrente ni dependencia de red. Mismo contrato,
  cero cambios en el resto del pipeline.
- **Claude Haiku, no Sonnet/Opus.** Para una sugerencia de 2-3 oraciones en
  tiempo real, la latencia importa más que el razonamiento profundo.
- **Streaming obligatorio en el LLM.** Ver las primeras palabras mientras
  el modelo sigue generando es la diferencia entre "útil en vivo" y
  "llegó tarde a la conversación".
- **Output sin definir todavía.** `ConsoleOutput` es un placeholder para
  validar el pipeline end-to-end. Falta decidir overlay / ventana / TTS.

## Setup

```bash
pip install -r requirements.txt
```

Si usás `STT_BACKEND=deepgram`:
```bash
export DEEPGRAM_API_KEY="tu-key"
```

Si usás `STT_BACKEND=whisper_local`, no hace falta key — pero la primera
ejecución descarga el modelo (`base` por defecto, configurable en
`main.py::build_stt_provider`).

Siempre necesario:
```bash
export ANTHROPIC_API_KEY="tu-key"
```

## Correr

```bash
# STT en la nube (Deepgram) — recomendado para latencia mínima
set STT_BACKEND=deepgram
python main.py

# STT local en tu RTX 4060 — sin costo recurrente, mayor latencia
set STT_BACKEND=whisper_local
python main.py
```

## Pendiente / próximos pasos

1. **Resampling en `WASAPILoopbackSource`** — si el sample rate nativo de
   tu dispositivo de salida no es 16kHz, hay un TODO marcado en
   `src/audio/wasapi_source.py` para resamplear antes de enviar a VAD/STT.
   No lo resolví a ciegas porque depende de tu hardware real — confirmá
   el sample rate nativo (`native_rate` se loggea al iniciar) antes de
   implementarlo.
2. **Captura de pestaña/navegador** (`tabCapture`) — para el caso
   "agnóstico de plataforma" cuando la llamada es vía navegador en vez de
   una app nativa. Mismo contrato `AudioSource`, falta la implementación.
3. **Definir `OutputSink` real** — overlay flotante, ventana separada, o
   TTS. Bloqueado por tu decisión, no por el código.
4. **Tuning de `silence_threshold_ms`** — 700ms es punto de partida
   razonable, pero el valor correcto depende de cómo hablás vos y con
   quién — ajustar empíricamente una vez que esté corriendo.
# call-copilot
