# Comparativa de STT: Deepgram vs Alternativas (Junio 2026)

## Resumen ejecutivo

Para el caso de uso del **copiloto de llamadas** (streaming, baja latencia, detección de fin de turno), las opciones relevantes se reducen a tres: **Deepgram**, **AssemblyAI** y **Whisper (local o API)**. El resto de proveedores (Google, Azure, AWS, Speechmatics, ElevenLabs) compiten en nichos específicos que no aplican directamente a tu pipeline.

**Conclusión corta:** Deepgram sigue siendo la elección correcta que ya hicimos, pero AssemblyAI es ahora un competidor serio y en algunos benchmarks independientes le gana en velocidad y precisión.

---

## Tabla comparativa — proveedores relevantes para streaming

| Proveedor | Precio streaming | Latencia (P50) | WER (real-world) | Diferenciador clave |
|---|---|---|---|---|
| **Deepgram Nova-3** | $0.0077/min (~$0.46/hora) | ~300ms | ~18% (AA-WER mixed) / 5.26% (benchmark propio) | Mejor latencia de fin de turno con **Flux** (<300ms, sin VAD externo) |
| **Deepgram Flux** | Mismo bundle que Nova-3 | <300ms EOT | — | End-of-turn detection integrado — reemplaza tu VAD externo (Silero) |
| **AssemblyAI Universal-3 Pro Streaming** | ~$0.45/hora | 307ms (vs 516ms Nova-3 en benchmark Hamming.ai) | 8.14% (vs 9.87% Nova-3, mismo benchmark) | Mejor accuracy en entidades (teléfonos, emails, montos); prompting en lenguaje natural |
| **Whisper API (OpenAI)** | $0.006/min (~$0.36/hora) | Sin streaming nativo (ventaneo) | 7.4% (mixed benchmarks) | Solo batch — no apto para tu caso sin aproximar streaming por chunks |
| **GPT-Realtime-Whisper** | $0.017/min | Streaming real | — | Versión streaming-dedicada de OpenAI, lanzada mayo 2026 — más cara que Deepgram |
| **faster-whisper (self-hosted)** | Solo costo de GPU | Pseudo-streaming (buffer por segundos) | Similar a Whisper Large | Tu RTX 4060 — cero costo recurrente, mayor latencia |

---

## Lo que cambia el análisis: dos benchmarks contradictorios

Hay una tensión real en los datos que vale la pena que sepas, no la voy a suavizar:

- **Benchmark propio de Deepgram / fuentes generalistas**: Nova-3 gana en latencia (~300ms) y es competitivo en WER (~5.26% en su propio dataset).
- **Benchmark independiente (Hamming.ai)**: AssemblyAI Universal-3 Pro Streaming es **más rápido** (307ms vs 516ms) y **más preciso** (8.14% vs 9.87% WER) que Nova-3 en la misma prueba.

Esto confirma lo que ya señalan varias de las fuentes: los benchmarks publicados por cada vendor están optimizados para favorecerlo. La diferencia real solo se conoce probando con tu audio específico.

---

## Comparativa por caso de uso (no solo precio)

| Tu prioridad | Proveedor recomendado | Por qué |
|---|---|---|
| **Latencia mínima end-to-end** | Deepgram Flux | EOT integrado, elimina tu capa de VAD por separado, mediana <300ms |
| **Precisión en datos críticos** (nombres, montos, teléfonos) | AssemblyAI Universal-3 Pro | Mejor accuracy en entidades — relevante si tu copiloto necesita capturar datos exactos en la llamada |
| **Cero costo recurrente** | faster-whisper local (RTX 4060) | Ya integrado en tu `call-copilot` como alternativa intercambiable |
| **Stack todo-en-uno (STT+LLM+TTS)** | AssemblyAI Voice Agent API ($4.50/hora flat) o Deepgram Voice Agent API | Reduce piezas a integrar, pero acopla tu LLM al proveedor de STT |
| **Soporte multilingüe amplio (99+ idiomas)** | Whisper / Google Chirp | Si tu copiloto necesita más que español/inglés |

---

## Precio: panorama completo

| Proveedor | Batch | Streaming |
|---|---|---|
| Deepgram Nova-3 | $0.0043/min ($0.258/hora) | $0.0077/min ($0.462/hora) |
| AssemblyAI Universal-2/3 | ~$0.15–0.21/hora (Nano) | ~$0.45/hora (Universal-3 Pro Streaming) |
| Whisper API (OpenAI) | $0.006/min ($0.36/hora) | No disponible (batch only) |
| GPT-Realtime-Whisper | — | $0.017/min ($1.02/hora) |
| faster-whisper self-hosted | Solo GPU | Solo GPU (pseudo-streaming) |
| Rev.ai Standard | $0.002/min (la más barata batch) | — |

---

## Recomendación directa para `call-copilot`

**Mantené Deepgram como default**, pero con una corrección sobre lo que ya implementamos:

1. **Evaluá migrar de Nova-3 + Silero VAD a Deepgram Flux.** Tu pipeline actual usa Silero como VAD externo — Flux integra el end-of-turn detection nativamente y reduce 200-600ms de latencia respecto a STT+VAD separados. Esto resolvería exactamente el problema que diseñamos manualmente con `SileroVAD`.

2. **AssemblyAI merece una prueba A/B real**, no descartarla por la elección inicial. Si tu copiloto necesita capturar datos exactos en la conversación (montos, nombres, fechas), su ventaja en accuracy de entidades es relevante para tu caso.

3. **No hay justificación para cambiar a Whisper API de OpenAI** en este pipeline — no soporta streaming nativo, que es un requisito no negociable para tu caso de uso.

4. La arquitectura que ya construimos (interfaz `STTProvider` intercambiable) te permite probar ambos sin reescribir el pipeline — es cuestión de implementar `AssemblyAIProvider` siguiendo el mismo contrato que `DeepgramSTT`.

---

## Nota sobre confiabilidad de los datos

Los benchmarks de WER varían según el dataset usado y casi siempre favorecen al proveedor que los publica. Las cifras de este informe combinan múltiples fuentes (benchmarks propios de cada vendor + benchmarks independientes como Hamming.ai), pero la única forma de saber qué funciona mejor para vos es correr ambos proveedores contra audio real de tus llamadas.

---

*Fuentes: deepgram.com/learn, assemblyai.com/blog, coval.ai, novascribe.ai, nextlevel.ai. Precios y benchmarks verificados a junio de 2026 — sujetos a cambio sin previo aviso.*
