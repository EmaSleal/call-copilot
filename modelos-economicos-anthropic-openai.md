# Modelos Económicos: Anthropic vs OpenAI (Junio 2026)

## Resumen ejecutivo

Anthropic no tiene escalón "nano" — **Haiku 4.5 es el piso** de su lineup. OpenAI ofrece dos escalones por debajo de su flagship (**Mini** y **Nano**), siendo Nano el modelo más barato del mercado entre ambos proveedores.

---

## Tabla comparativa

| Modelo | Input ($/M tokens) | Output ($/M tokens) | Contexto | Ratio output/input |
|---|---|---|---|---|
| **Claude Haiku 4.5** | $1.00 | $5.00 | 200K | 5x |
| **GPT-5.4 Mini** | $0.75 | $4.50 | 400K | 6x |
| **GPT-5.4 Nano** | $0.20 | $1.25 | 400K | 6.25x |

---

## Detalle por proveedor

### Anthropic — Claude Haiku 4.5

- Pricing: $1.00 input / $5.00 output por millón de tokens
- Hasta 90% de ahorro con prompt caching, 50% con batch processing
- Iguala el desempeño de Sonnet 4 en coding, computer use y tareas de agentes
- Es el modelo más rápido y costo-eficiente de la línea Claude actual

### OpenAI — GPT-5.4 Mini

- Pricing: $0.75 input / $4.50 output por millón de tokens
- Contexto de 400K tokens
- Soporta texto e imágenes, tool use, function calling, web search, file search, computer use y skills

### OpenAI — GPT-5.4 Nano

- Pricing: $0.20 input / $1.25 output por millón de tokens
- Versión más pequeña y barata de la familia GPT-5.4
- Pensado para clasificación, extracción de datos, ranking y subagentes de coding en tareas de soporte simples

---

## Costo aplicado: copiloto de llamadas (call-copilot)

Estimado conservador: ~300 tokens input / ~80 tokens output por respuesta generada.

| Modelo | Costo por respuesta | Costo / 1,000 respuestas |
|---|---|---|
| Claude Haiku 4.5 | $0.0007 | $0.70 |
| GPT-5.4 Mini | $0.00059 | $0.59 |
| GPT-5.4 Nano | $0.00016 | $0.16 |

---

## Conclusión

1. **GPT-5.4 Nano es 5x más barato en input y 4x más barato en output que Haiku 4.5** — es el modelo más económico entre ambos proveedores, no Haiku.
2. A volúmenes de uso moderados (cientos a pocos miles de respuestas/mes), la diferencia de costo entre los tres modelos es de **centavos** — no es el criterio de decisión relevante.
3. Factores más relevantes que el precio para casos de baja latencia (ej. copiloto de llamadas en vivo):
   - Latencia real medida en producción, no solo el precio publicado
   - Calidad de instruction-following en contexto conversacional corto, donde los modelos "nano" tienden a degradar más que "mini" o equivalentes de gama media
4. Reevaluar el modelo solo se justifica si el volumen escala a miles de llamadas simultáneas — a esa escala, el ahorro relativo de Nano sí se vuelve significativo.

---

*Fuentes: páginas oficiales de pricing de Anthropic (claude.com/pricing, anthropic.com/claude/haiku) y OpenAI (openai.com/api/pricing). Precios verificados a junio de 2026 — sujetos a cambio sin previo aviso.*
