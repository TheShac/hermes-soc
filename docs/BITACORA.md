# Bitácora de implementación: Hermes-SOC

Última actualización: 2026-11-09. Estado: banco de pruebas, agentes, herramientas, ejecutor y análisis funcionando. El primer piloto (40 corridas) se ejecutó pero **no es válido para comparar** (ver §5, últimas filas); se repetirá tras corregir los timeouts.

## 1. Objetivo y alcance
Implementar y probar el pre-paper "Hermes-SOC": un SOC multiagente sobre Hermes Agent con tres agentes que se comunican por A2A
(Detección: falla vs. ataque; Mitigación: contramedidas vía MCP; Documentación: reporte del incidente).
Se implementó solo lo pedido: resumen, contexto y problema, solución propuesta y metodología de validación (3 escenarios, métricas de la Tabla I, multiagente vs. agente único).
Trabajos Relacionados queda como comparación en texto. Restricciones: modelos locales gratuitos, todo en Windows (Docker solo para el banco de pruebas), Python, repositorio listo para GitHub.

## 2. Entorno
| Componente | Detalle |
|---|---|
| Equipo | Windows; i9-14900HX, 32 GB RAM, RTX 5070 Laptop 8 GB |
| Hermes Agent | v0.21.5+4108.g105568c (nativo en Windows) |
| Ollama | 0.40.11; `OLLAMA_CONTEXT_LENGTH=64000`, `FLASH_ATTENTION=1`, `KV_CACHE_TYPE=q8_0`, `NUM_PARALLEL=1`, `KEEP_ALIVE=-1` |
| Modelo | `qwen3.5:9b`, contexto 64000, 7.8 GB, 30 %/70 % CPU/GPU (el mismo en los 4 perfiles) |
| Docker | Docker Desktop con WSL2 (solo contenedores del banco de pruebas) |
| Python | 3.14 en `.venv`; `mcp` 2.3.0 (`requirements.txt`) |

## 3. Arquitectura final
```
ejecutor (runner/) ──A2A──> Detección (9901) ──JSON──> ejecutor ──A2A──> Mitigación (9902) ──JSON──> ejecutor ──A2A──> Documentación (9903) ──> reporte
                  └─A2A──> Agente único (9904): detecta + mitiga + documenta
Herramientas MCP: detection_tools.py (solo lectura)  |  mitigation_tools.py (acciones acotadas, auditadas)
Banco de pruebas (Docker, red 172.28.0.0/24): soc-target (.10) · soc-redis (.11) · soc-prometheus (.20) · soc-legit (.50) · soc-attacker1..3 (.101-.103)
```
- **Objetivo**: FastAPI con `/`, `/health`, `/api/data` (depende de Redis), `/login` (PBKDF2, costoso), `/metrics`; log JSON por petición y métricas Prometheus (incluye memoria/CPU del contenedor por cgroup).
- **Inyectores** (`injectors/inject.py`): falla (`latency` con tc netem, `memory` con stress-ng, `redis_down`), DDoS L7 desde 3 atacantes, fuerza bruta desde 1; cada uno escribe `ground_truth.json`.
- **Detección**: `get_traffic_summary`, `get_container_status`, `get_log_sample` (resúmenes, no logs crudos).
- **Mitigación**: `restart_service` (solo target/redis), `block_ip`, `rate_limit_ip`, `list_firewall_rules`, `verify_recovery`; IP protegidas no bloqueables, modo dry-run, registro en `results/raw/actions.jsonl`.
- **Ejecutor** (`runner/run_experiments.py`): escenario × condición × repetición, orden aleatorio por bloques, reanudable; monitor objetivo cada 5 s; guarda `run.json`, `report.md`, `summary.csv`. Escenario extra `normal` para falsos positivos.
- **Análisis** (`analysis/analyze.py`): Tabla I con IC bootstrap, fiabilidad, calidad automática del reporte, matrices de confusión, discrepancias acciones declaradas vs. ejecutadas.

## 4. Lo que funciona (verificado)
- Hermes + Ollama con 64K de contexto; 3 perfiles con servidor A2A (9901-9903) y el agente único (9904).
- Llamada A2A directa (`SendMessage`): `TASK_STATE_COMPLETED`, ~4-5 s con el modelo caliente.
- Llamada agente→agente con `a2a_call` (Detección→Mitigación): `PONG-MITIGACION` en 28.9 s con `qwen3.5:9b`.
- Banco de pruebas: `scripts/check_testbed.ps1` pasa las 12 comprobaciones (incluye `tc`, `iptables`, `stress-ng` dentro del contenedor).
- Inyectores, firmas observadas con `mcp_servers/summary.py`:

| Escenario | Firma |
|---|---|
| Base | ~5 rps, 1 IP, p95 0.6 ms |
| Latencia | p95 813 ms, mismo tráfico |
| Memoria | memory_ratio 0.89, CPU 1.0, p95 11 ms |
| Redis caído | 5xx 16 %, p95 15 s |
| DDoS | ~1145 rps, 4 IP (3 con ~33 %), p95 243 ms, CPU 0.5, sin 5xx |
| Fuerza bruta | 80 rps, 94 % de una IP, 401 = 99.7 %, CPU 1.0 |

- Herramientas MCP: `scripts/test_tools.py --real` bloquea y limita IP en el contenedor (`iptables` con `limit` funciona); rechaza IP protegidas y fuera de la red.
- Cadena multiagente completa con DDoS: Detección 18 s + Mitigación 82 s + Documentación 30 s; 3 `block_ip` reales; reporte en español con las 4 secciones.
- Humo (1 repetición por celda, 6 corridas), todas con clasificación correcta y sin falsos positivos en `normal`:

| Escenario | Cond. | Primera acción (s) | MTTR (s) | Nota |
|---|---|---|---|---|
| ddos | single | - | 110 | cadena 166 s |
| ddos | multi | - | 175 | cadena 307 s |
| bruteforce | single | 56 | 71 | |
| fault (latency) | single | 67 | 76 | |
| fault (latency) | multi | 58 | 66 | TTD 51 s, 1 reintento |
| bruteforce | multi | ninguna | - | Mitigación declaró un `block_ip` que no ejecutó |

Con n=1 por celda son datos de humo, no resultados.

## 5. Problemas encontrados y cómo se resolvieron
| Problema | Causa | Solución |
|---|---|---|
| Hermes rechaza `qwen3:8b` (mínimo 64K) | Ollama recorta al contexto de entrenamiento (40 960) | Se usó `qwen3:4b` (256K nativo) y luego `qwen3.5:9b` |
| Rendimiento a 64K | `KV_CACHE_TYPE=q4_0` degrada mucho | Se usa `q8_0` |
| Aviso de `hermes doctor` por proveedor `hermes-soc` | Entrada heredada en config | Cosmético; se omite |
| Puertos A2A pisados | Elegir "A2A" varias veces en un mismo `gateway setup` | Elegir la opción 7 una sola vez y luego "Done", perfil por perfil |
| El perfil no levanta su propio gateway | Limitación de Hermes | `gateway.standalone: true` y `hermes -p <perfil> gateway run` en su ventana |
| `hermes tools` no activaba al dar varios números | La interfaz toma un número por vez | Alternar uno a uno |
| Agent Card y tareas con todos los toolsets | Faltaba entrada `a2a:` en `platform_toolsets` | Añadirla (`a2a: [a2a]`) |
| `qwen3:4b` no logra llamar a `a2a_call` | La herramienta es diferida y exige `tool_call` con lista `calls`; el modelo la arma mal | Se cambió a `qwen3.5:9b` |
| Razonamiento filtrado en las respuestas | Al desactivar el razonamiento | Se resolvió con el modelo 9B |
| Primera llamada muy lenta (hasta 195 s) | Carga del modelo y saludo de bienvenida | `KEEP_ALIVE=-1`; declinar el saludo |
| Saludo de bienvenida de Hermes en perfiles nuevos | Onboarding sin completar | Declinar en `hermes -p <perfil> chat` (`onboarding.seen.profile_build_offered: true`) |
| `a2a_call` expira a 120 s | Límite fijo de Hermes; cada agente tarda 100-200 s | El ejecutor lleva el mensaje de un agente al siguiente (ver §6) |
| Mitigación no llamaba a Documentación | Cadena anidada demasiado lenta y modelo pequeño | Misma solución: relevo por el ejecutor |
| Detección dijo "healthy" sin usar herramientas | Copió las cifras del baseline del prompt | Herramientas obligatorias, baseline marcado como "no medición", texto de disparo explícito y chequeo de evidencia contra una medición real previa |
| Respuesta sin JSON (texto de razonamiento / JSON cortado) | Fallo de formato esporádico del modelo | Extractor tolerante y un reintento por salto, registrado como métrica |
| Mitigación declaró una acción que no ejecutó | Alucinación del modelo | Regla reforzada en el prompt; se mide como "acciones declaradas ≠ ejecutadas" |
| `ModuleNotFoundError: mcp.server.fastmcp` | `mcp` 2.x renombró `FastMCP` a `MCPServer` | Los servidores soportan ambas versiones |
| Scripts de PowerShell | `param` debe ir primero; acentos sin BOM | Reordenado y guardados con BOM |
| Piloto v0: 14 de 40 saltos terminaron con `[agent did not reply in time]` a los 300 s exactos (12 del agente único, 2 de Detección y 1 de Mitigación en multi) | El servidor A2A de Hermes corta la tarea a los 300 s, pero **el agente sigue trabajando**: ejecuta herramientas y ocupa el modelo durante la corrida siguiente | El ejecutor espera a que los agentes queden libres antes de cada corrida (`quiesce`: sin acciones nuevas 60 s y los 4 agentes responden un PING en <60 s) y registra `timed_out`; el límite SÍ es configurable: variable de entorno `A2A_REPLY_TIMEOUT` (por defecto 300; leída en `plugins/platforms/a2a/adapter.py`); `start_agents.ps1` la fija en 1800 |
| Piloto v0: acciones de mitigación en corridas `normal` y sobre IP que no atacaban | Eran del agente de la corrida anterior que había expirado (4 casos, todos justo tras un timeout) | Mismo `quiesce`; la carpeta se conserva como `piloto_v0_contaminado` y no se usa para comparar |
| Métricas de análisis engañosas | Contaba herramientas de consulta como acciones; penalizaba nombrar la IP del cliente legítimo | Se corrigió `analyze.py` |

## 6. Limitaciones y desviaciones respecto al paper
- **Delegación entre agentes**: el paper plantea que los agentes se llamen entre sí. Con el modelo local, `a2a_call` tiene un tope fijo de 120 s y la cadena anidada no cabe, así que el **ejecutor** transporta cada resultado al siguiente agente. Cada salto sigue siendo un mensaje A2A real, pero la decisión de "a quién llamar" no la toma el agente.
- **Mitigación**: sin `scale` (el banco usa nombres e IP fijos). El DDoS es L7 desde 3 contenedores; no hay inundación L4.
- **Medición**: el tiempo hasta la detección (TTD) solo existe en multiagente; en ambas condiciones se mide el tiempo hasta la primera acción real y el MTTR objetivo (monitor cada 5 s, no lo que declaran los agentes).
- **El DDoS actual no genera errores 5xx**, solo sube latencia y CPU.
- Un solo modelo (`qwen3.5:9b`) y temperatura por defecto del perfil; una corrida tarda 2-8 min, por lo que el tamaño de muestra es modesto (piloto de 5 repeticiones por celda; 20 sería ~días de cómputo).
- Todo es local (127.0.0.1, sin tokens A2A); los ataques solo apuntan al objetivo del banco de pruebas.

## 7. Pendiente (retomar mañana)
1. Verificar la respuesta de Mitigación tras reforzar el prompt y revisar la sección "Discrepancias" de `analyze.py` sobre `results/raw/humo` (`fault_multi_00` también marcó discrepancia con 3 acciones reales).
2. **Repetir el piloto** (40 corridas, ~3.5-4 h; renombrar antes `results/raw/piloto` a `results/raw/piloto_v0_contaminado`):
   `python runner/run_experiments.py --scenarios fault,ddos,bruteforce,normal --conditions multi,single --reps 5 --out results/raw/piloto` y luego `python analysis/analyze.py results/raw/piloto`.
3. Restringir toolsets: `mitigacion`, `documentacion` y `unico` solo con A2A (+MCP); Documentación sin herramientas de archivos.
4. Reproducibilidad: desactivar memoria, skills y `session_search` en los perfiles; fijar temperatura.
5. Configurar modelos auxiliares de Hermes con el modelo local (avisos de Nous).
6. Decidir tamaño de muestra final según el piloto (más repeticiones, o más pasos).
7. Rúbrica de calidad del reporte en `docs/` y, opcionalmente, escenario flash crowd y línea base por reglas sin LLM.
8. Antes de GitHub: sin `.env`, tokens ni carpetas de perfiles (la config vive fuera del repo en `%LOCALAPPDATA%\hermes`), elegir LICENSE, completar el README con la reproducción y anotar la versión de Hermes.

## 8. Cómo reproducir (resumen)
```powershell
# 1. Ollama con las variables de §2 y qwen3.5:9b; Hermes instalado; perfiles deteccion/mitigacion/documentacion/unico con A2A (9901-9904)
python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt
cd testbed ; docker compose up -d --build ; docker compose --profile attack up -d ; cd ..
.\scripts\check_testbed.ps1
.\scripts\add_mcp_config.ps1 ; .\scripts\install_souls.ps1 ; .\scripts\start_agents.ps1
python runner/run_experiments.py --reps 5 --out results/raw/piloto
python analysis/analyze.py results/raw/piloto
```
Más detalle del banco de pruebas en `docs/testbed.md`, del formato de mensajes en `docs/a2a_schema.md` y del plan por pasos en `PLAN.md`.
