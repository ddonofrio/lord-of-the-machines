# Lord of the Machines

Lord of the Machines es el nuevo laboratorio para construir una solución autónoma de IA que pueda leer su propio código, mejorar sus herramientas y avanzar hacia una misión dada.

Este primer corte crea solo la base correcta: un agente LLM genérico, configurable y testeado. Aún no hay servidor autónomo ni bucle de auto-programación; eso debe montarse encima de este núcleo.

## Estado Actual

Incluido:

- Estructura Python estándar con `src/`, `tests/`, `config/`, `pyproject.toml` y paquete instalable.
- `BaseAgent`, mantenido como nombre porque representa bien la primitiva base: una capa de abstracción sobre un LLM, no un agente de dominio.
- `BaseAgent` queda como fachada/orquestador; las piezas grandes viven en módulos dedicados:
  - `config.py`: configuración, defaults y números con nombre.
  - `payload.py`: construcción de payload, instructions, envelope e input.
  - `transport.py`: OpenAI Responses API, retries, rate-limit y verbosity fallback.
  - `history.py`: historial local y presupuesto de contexto.
  - `parser.py`: parsing/validación del contrato de salida.
  - `tools.py` y `memory.py`: registro/ejecución de herramientas y memoria interna.
  - `prompt_cache.py`: generación de `prompt_cache_key`.
  - `rate_limit.py`, `tokens.py`, `schema.py`, `replies.py`, `errors.py`: primitivas pequeñas.
- Configuración separada por responsabilidades:
  - `provider`: proveedor, modelo, API key env y override por env.
  - `agent`: prompt, memoria, reparaciones y rondas de herramientas.
  - `reply`: herramienta/metodo/campo usados para extraer mensajes finales.
  - `envelope`: contrato configurable de entrada y salida.
  - `context`: historial local y presupuesto de contexto.
  - `transport`: rate limit, retries y backoff.
  - `prompt_cache`: cache key estable y lista de campos usados como semilla.
  - `response_defaults`: parametros de OpenAI Responses API.
- `AgentEnvelopeSpec`: objeto que define los campos top-level del envelope de entrada.
- `ToolCallOutputSpec`: objeto que define los campos esperados de salida (`calls/tool/method/arguments` por defecto, pero renombrables).
- Memoria interna compatible con `memory.remember`, `memory.recall` y `memory.forget`.
- Reparación de protocolo si el modelo devuelve JSON inválido o una tool/method no permitida.
- Ejecución de herramientas internas y feedback de resultados al modelo hasta que responda.
- Historial local limpio: guarda mensajes reales, no envelopes ni prompts de reparación.
- Preflight token estimation, rate limiter local, retries ante 429 y retry por verbosity no soportada.
- Prompt cache configurable con `prompt_cache.fields`.
- Tests unitarios con cliente OpenAI fake.

## Configuración Principal

Archivo por defecto:

```text
config/base_agent.json
```

Override por variable de entorno:

```text
LORD_OF_THE_MACHINES_BASE_AGENT_CONFIG
```

Modelo por defecto:

```text
gpt-4.1
```

Se puede cambiar sin tocar el JSON con:

```text
OPENAI_MODEL
```

## Envelope Flexible

El agente ya no lleva el envelope incrustado como una forma fija. El objeto `AgentEnvelopeSpec` decide qué campos de entrada se mandan:

```python
AgentEnvelopeSpec(
    version="custom.agent.v1",
    input_fields=[
        EnvelopeField("protocol", "protocol"),
        EnvelopeField("history", "conversation_history"),
        EnvelopeField("context", "runtime_context"),
        EnvelopeField("request", "user"),
        EnvelopeField("contract", "output_contract"),
    ],
)
```

Y `ToolCallOutputSpec` decide qué forma de salida se valida:

```python
ToolCallOutputSpec(
    calls_field="actions",
    tool_field="tool_name",
    method_field="operation",
    arguments_field="args",
)
```

Esto permite que futuros agentes usen contratos distintos sin reescribir `BaseAgent`.

## Cache de Tokens / Prompt Cache

La config incluye:

```json
"prompt_cache": {
  "enabled": true,
  "key_prefix": "lotm",
  "retention": "24h",
  "fields": ["model", "instructions", "text", "tools", "envelope"]
}
```

La lista `fields` define qué partes estables entran en la `prompt_cache_key`. Por defecto no incluye `input`, para que la key no cambie en cada mensaje. Si una misión necesita aislar cache por prompt o por tenant, se puede añadir `input`, `metadata.tenant`, etc., sabiendo que eso reduce reutilización.

## Ejecutar Tests

Desde la carpeta del proyecto:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
```

## Próximo Trabajo

Falta construir la capa autónoma:

- CLI/server que arranque con una misión.
- Lector seguro del propio repositorio.
- Planner inicial que convierta la misión en backlog ejecutable.
- Herramientas de edición, ejecución de tests y análisis de resultados.
- Registro persistente de decisiones, cambios y objetivos.
- Sandboxing operativo para que el sistema pueda tocar código sin destruir trabajo humano.
- Agentes especializados: arquitecto, implementador, verificador, toolmaker, reviewer.
- API/MCP para exponer herramientas internas.
- Política de permisos y límites: qué puede editar, ejecutar, instalar o publicar.

La idea es que el servidor de misión viva en `src/lord_of_the_machines/mission` y use `llm.BaseAgent` como primitiva, no al revés.
