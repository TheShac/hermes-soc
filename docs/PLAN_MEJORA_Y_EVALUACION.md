# Plan de mejora de los agentes y banco de pruebas realista

Objetivo: tener una línea de evaluación progresiva. Cada versión de los agentes se mide con **el mismo banco de pruebas, las mismas métricas y las mismas semillas**, para poder comparar "agentes actuales" contra "agentes mejorados/entrenados".

## 1. Diagnóstico: por qué los agentes fallan hoy (datos del piloto v0)

| Síntoma observado | Causa probable | Tipo |
|---|---|---|
| 14/40 saltos expiran a los 300 s (12 del agente único) | Límite A2A de Hermes (`A2A_REPLY_TIMEOUT`) + modelo lento (qwen3.5:9b va ~30 % CPU / 70 % GPU en 8 GB) + muchos turnos de herramientas | Plataforma / rendimiento |
| Tareas "zombi" contaminan la corrida siguiente | El agente no se detiene al expirar | Plataforma (mitigado con `quiesce`) |
| Mitigación declara acciones que no ejecutó (`bruteforce_multi_00/_02`, `fault_single_03`) | El modelo escribe el JSON final antes o sin llamar a la herramienta | Fiabilidad del LLM |
| Errores de clasificación en fallas (memoria→attack, redis_down→latency, healthy) | Las señales están dispersas; el modelo debe razonar sobre números crudos | Diseño de herramientas / prompt |
| Agente único casi nunca termina | Hace 3 fases en una sola tarea: más turnos, más contexto, más tiempo | Diseño (esperable) |
| 20–40 % de coherencia de evidencia en algunas celdas | Tolerancia de la métrica o el informe cita números inventados | Métrica + prompt |

## 2. Mejoras propuestas (de menor a mayor costo)

Cada nivel es **una versión congelada** (se registra el hash de `hermes_profiles/` y `mcp_servers/`).

- **v0 – línea base actual.** Congelar tal cual. Es el punto de comparación. Se re-ejecuta el piloto con `A2A_REPLY_TIMEOUT=1800` y `quiesce`.
- **v1 – ingeniería de herramientas y prompt (sin entrenar).** La mejora con mejor retorno:
  1. Que `get_traffic_summary` devuelva además **indicadores ya calculados** (`rps_vs_baseline`, `ip_concentration`, `login_401_rate`, `error_5xx_rate`, `mem_ratio`, `redis_ok`) y una lista `signals_triggered`. El modelo clasifica sobre señales, no sobre números crudos.
  2. **Una sola herramienta de diagnóstico** (`diagnose_snapshot`) que llame a las tres actuales: menos turnos y menos oportunidades de saltarse una.
  3. Prompts más cortos, con **2–3 ejemplos (few-shot)** por clase (fault/attack/healthy) y regla "sin llamada, sin acción".
  4. **Validación en el ejecutor**: si `actions` declaradas ≠ acciones reales, el ejecutor lo rechaza y pide corrección (1 reintento, contado como métrica).
  5. Rendimiento: desactivar el "thinking" de qwen3.5 si Hermes lo permite, bajar `OLLAMA_CONTEXT_LENGTH` de 64000 a 16000–32000 para que más capas queden en GPU, y restringir toolsets (sin herramientas de archivos/terminal).
  6. Desactivar memoria/skills/session_search de Hermes para que no varíen entre corridas.
- **v2 – conocimiento externo (RAG ligero).** Un `playbook.md` de respuesta a incidentes (qué hacer ante DDoS, fuerza bruta, fallas) expuesto como herramienta `get_playbook(tipo)`. Es "entrenar" sin tocar pesos y es auditable.
- **v3 – entrenamiento real (opcional, costoso).** Afinar con LoRA/QLoRA un modelo pequeño (≈4B; un 9B no cabe cómodo en 8 GB para entrenar) usando **trazas de corridas correctas de v1/v2** como datos (destilación). Riesgo: pocos datos y sobreajuste a los escenarios del banco; por eso se separan escenarios de entrenamiento y de prueba (§4).

Qué significa "entrenado" en el paper: v0 = solo prompt de rol; v1/v2 = optimizados sin cambiar pesos; v3 = ajustado con datos. Hay que declarar cuál se usa en cada comparación.

## 3. Banco de pruebas Docker "medio real"

Se extiende `testbed/` (misma red 172.28.0.0/24), sin cambiar lo que ya funciona.

**Tráfico de fondo más realista**
- Generador legítimo con **patrón diurno** (rampa suave), usuarios con sesiones (login → navegar → logout), ráfagas legítimas.
- Ruido: errores 404 normales, algunos 401 por contraseñas mal escritas, picos de latencia ocasionales.

**Catálogo de escenarios (YAML, cada uno con verdad de terreno)**

| ID | Escenario | Clase | Qué pone a prueba |
|---|---|---|---|
| F1 | Fuga de memoria gradual | fault | Distinguir de ataque por tendencia |
| F2 | Redis caído | fault | Causa raíz ≠ latencia |
| F3 | Despliegue con mala configuración (5xx tras "deploy") | fault | Correlación temporal |
| F4 | CPU saturada por vecino ruidoso | fault | No bloquear IPs |
| A1 | DDoS HTTP con 3 IPs | attack | Caso actual |
| A2 | Fuerza bruta de login | attack | Caso actual |
| A3 | Fuerza bruta lenta (low-and-slow) | attack | Umbrales no triviales |
| A4 | Credential stuffing distribuido (muchas IPs, pocos intentos c/u) | attack | Rate-limit vs bloqueo |
| A5 | Escaneo de rutas (`/admin`, `../`) | attack | Señal distinta a volumen |
| N1 | **Flash crowd legítimo** (pico sin ataque) | normal | Falso positivo clave |
| N2 | Día normal con ruido | normal | Falsos positivos |
| M1 | **Falla + ataque simultáneos** | mixto | Priorización |

**Reglas del banco**
- Cada ejecución guarda: escenario, semilla, verdad de terreno, `access.jsonl`, métricas Prometheus, acciones reales. Así es reproducible y se pueden **reproducir (replay)** corridas con otro agente.
- **Partición**: escenarios de *desarrollo* (se usan para ajustar prompts/herramientas) y de *prueba* (congelados, solo se miran al final). Evita ajustar al examen.
- Métricas igual que Tabla I (exactitud, TTD, TTM, MTTR, falsos positivos, acciones innecesarias, calidad del informe) más: tasa de timeout, reintentos, acciones declaradas≠ejecutadas.

## 4. Protocolo de comparación progresiva

1. Congelar versión (`git tag agentes-v0`, registrar hashes y versión de Hermes/Ollama/modelo).
2. Ejecutar catálogo de **desarrollo** × {multi, single} × n repeticiones (≥5, idealmente 10) con semillas fijas.
3. Analizar con `analysis/analyze.py` (IC por bootstrap) y guardar en `results/raw/<version>/`.
4. Aplicar la siguiente mejora, tag `agentes-v1`, repetir. Solo se cambia **una cosa por versión** para atribuir la mejora.
5. Al final, una única pasada sobre los escenarios de **prueba** para todas las versiones.
6. Tabla final: versión × condición × métrica, con intervalos; reportar también los timeouts como resultado.

## 5. Orden de trabajo sugerido

1. Prueba corta `prueba3` (agente único con timeout 1800) y repetir piloto → **cierra v0**.
2. v1.1–v1.3 (señales calculadas, herramienta única, few-shot) → medir.
3. Ampliar el banco: N1, A3, F3 primero (los de mayor valor para falsos positivos y umbrales).
4. v2 (playbook) → medir.
5. Decidir si v3 vale la pena según lo que quede de error.

## 6. Riesgos
- Modelo local pequeño: la varianza es alta; usar n≥5–10 y reportar IC.
- Más escenarios = más horas (cada corrida ≈ 5–10 min): planificar tandas nocturnas con `--resume`.
- Ajustar a los escenarios de desarrollo: mitigado con la partición.
- Cambios de plataforma (Hermes/Ollama): fijar versiones.
