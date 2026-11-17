# Notas metodológicas para el paper / taller

Información para citar o adaptar en la metodología y en las limitaciones. Se ajusta con lo que ocurra en el piloto.
Última actualización: 2026-11-16.

## 1. Los agentes no están entrenados: son agentes guiados por prompts
- Todos los agentes usan el mismo modelo base, `qwen3.5:9b` (contexto 64 000 tokens, servido por Ollama), **sin fine-tuning ni modificación de pesos** y sin base de conocimiento externa (no hay RAG). Enfoque *zero-shot* guiado por instrucciones.
- Qué define el comportamiento de cada agente:

| Elemento | Qué aporta | Dónde está |
|---|---|---|
| Prompt de rol (`SOUL.md`) | Rol, procedimiento paso a paso, criterios de clasificación orientativos, formato JSON de salida, reglas de no inventar datos | `hermes_profiles/<agente>/SOUL.md` |
| Herramientas (MCP) | Qué puede observar y qué puede hacer | `mcp_servers/detection_tools.py`, `mitigation_tools.py` |
| Mensaje de disparo y relevo | Texto con el que se inicia cada tarea y paso del resultado al siguiente agente | `runner/chain.py` |

- Condiciones comparadas: **multiagente** (3 agentes especializados, cada uno con su prompt y sus herramientas) y **agente único** (el mismo modelo con un solo prompt que cubre las tres fases y todas las herramientas). La diferencia es la arquitectura y el reparto del trabajo, no el modelo.
- Redacción sugerida: "Los agentes se configuraron mediante prompts de rol y herramientas, sin entrenamiento adicional del modelo."

## 2. Ingeniería de prompts durante el desarrollo (declararlo)
Los prompts se ajustaron tras corridas de prueba. Cambios principales y motivo:
1. Herramientas de monitoreo obligatorias antes de responder: Detección respondió "healthy" sin consultar nada y copió las cifras del baseline del prompt.
2. Baseline marcado como "referencia, no medición", y texto de disparo explícito.
3. Salida solo en JSON y relevo entre agentes por el ejecutor (ver §4).
4. Regla "no escribir el JSON antes de que las herramientas respondan; sin herramienta, `actions` vacío": Mitigación declaró un `block_ip` que no ejecutó.
5. Reintento de formato (máx. 1 por salto, igual en ambas condiciones): respuestas con texto de razonamiento o JSON cortado.

**Riesgo a declarar**: esas pruebas usaron los mismos tipos de escenario que la evaluación, así que el prompt puede estar afinado a ellos. Mitigación recomendada: **congelar los prompts antes del piloto** (guardar el hash o el commit de `hermes_profiles/`) y no modificarlos durante la evaluación; si hay que cambiarlos, repetir todo el experimento.

## 3. Funciones de aprendizaje/memoria de Hermes
Hermes incluye memoria, skills y búsqueda de sesiones. No se usan deliberadamente. Cada tarea A2A abre una sesión nueva; falta desactivar esas funciones en los perfiles (pendiente en `PLAN.md`) para garantizar que un agente no mejore entre corridas.

## 4. Desviación respecto al diseño del paper
El diseño plantea que los agentes se comuniquen entre sí. En la implementación cada salto es un mensaje A2A real, pero **el ejecutor** lleva el resultado de un agente al siguiente. Causa: la herramienta `a2a_call` de Hermes tiene un tiempo máximo fijo de 120 s y cada agente tarda 100-200 s con el modelo local; en la prueba anidada Detección expiró y Mitigación no llegó a llamar a Documentación. Consecuencia: la decisión de "a quién delegar" no la toma el agente.

## 5. Medición y validez
- Tiempos y recuperación se miden **objetivamente** (monitor del servicio cada 5 s y registro de acciones reales), no con lo que los agentes declaran.
- TTD solo existe en multiagente; en ambas condiciones se mide el tiempo hasta la primera acción real y el MTTR.
- Métricas de fiabilidad propias: JSON válido, reintentos, acciones declaradas ≠ ejecutadas, evidencia coherente con la medición real, texto en otros alfabetos en el reporte, IP erróneas bloqueadas.
- Hallazgos del humo (n=1 por celda, solo orientativos): clasificación correcta en las 6 corridas; en una corrida multiagente Mitigación declaró una acción que no ejecutó.
- **Piloto v0 descartado**: el servidor A2A de Hermes corta cada tarea a los 300 s sin detener al agente; esas tareas "zombi" ejecutaron acciones durante la corrida siguiente (4 casos) y el agente único expiró en 12 de 20 corridas. Antes de comparar condiciones hay que eliminar esa contaminación y declarar cuántas corridas expiran por condición (el tiempo de tarea es en sí un resultado: el agente único hace todo en una tarea más larga).
- Tamaño de muestra: piloto de 5 repeticiones por escenario y condición (+ escenario `normal` para falsos positivos). Intervalos bootstrap del 95 %; con n tan bajo son amplios y no se deben presentar como diferencias concluyentes.

## 6. Limitaciones a mencionar
- Un solo modelo local de 9B parámetros y un solo banco de pruebas en un equipo; no se prueban otros modelos.
- Escenarios sintéticos: DDoS de capa 7 desde 3 contenedores y fuerza bruta desde 1; sin inundación L4 y sin `scale` en la mitigación.
- El DDoS no genera errores 5xx, solo sube latencia y CPU.
- Comunicación local (127.0.0.1, sin tokens A2A); los ataques apuntan solo al objetivo del banco.
- Los reportes los evalúan comprobaciones automáticas simples (4 secciones, IP correctas, texto ajeno); falta una rúbrica humana.

## 7. Datos que citar (versiones)
Hermes Agent v0.21.5+4108.g105568c · Ollama 0.40.11 · Docker Desktop (WSL2) · Python 3.14 · `mcp` 2.3.0 · `qwen3.5:9b` en los 4 perfiles (verificado en `config.yaml`) · equipo: i9-14900HX, 32 GB RAM, RTX 5070 Laptop 8 GB.
