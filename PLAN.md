# Plan de trabajo Hermes-SOC

Alcance: resumen, contexto y problema, solución propuesta y metodología de validación.
(Trabajos Relacionados = solo texto del paper, no se implementa.)

## Decisiones fijadas
- Modelo: `qwen3.5:9b` en Ollama con contexto 64000 (Hermes exige >= 64K reales; `qwen3:8b` solo admite 40960). `qwen3:4b` NO sirve: no logra armar la llamada diferida `tool_call`/`a2a_call` (bucle de 5 errores). Temperatura fija, mismo modelo en los 3 agentes y en el agente único. El código no depende del modelo: se puede cambiar al final.
- Escenarios: (1) falla operativa, (2) DDoS con varios contenedores atacantes, (3) fuerza bruta.
- Condiciones: multiagente vs. agente único (opcional: reglas sin LLM; escenario flash crowd).
- Repeticiones: piloto 5 por escenario, luego 20.
- Mejoras mínimas: atacantes múltiples, allowlist + dry-run en mitigación, estado de Hermes reiniciado entre corridas, herramientas de Detección devuelven resúmenes (no logs crudos).
- Entorno: Windows; banco de pruebas en Docker Desktop; agentes y scripts en Windows.

## Pasos
### Paso 0: Hermes + Ollama
- [x] `ollama serve` activo con `OLLAMA_CONTEXT_LENGTH=64000`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_NUM_PARALLEL=1`; `ollama ps` muestra CONTEXT 64000
- [x] `hermes model` -> custom endpoint `http://localhost:11434/v1`, modelo `qwen3:4b`, contexto 64000
- [x] `hermes chat -q "Responde exactamente: MODEL_OK"` y `hermes doctor`
- [x] `hermes doctor --fix` no corrige el aviso del proveedor `hermes-soc` (requiere edición manual de config.yaml; es cosmético, se omite por ahora)
- [x] Crear perfiles: `deteccion`, `mitigacion`, `documentacion` (`hermes profile create <perfil> --clone`)
- [x] Configurar cada perfil (mismo modelo `qwen3.5:9b`)
- [x] Activar A2A con `hermes -p <perfil> gateway setup` (opción 7, UNA vez, luego 28 Done): deteccion 9901, mitigacion 9902, documentacion 9903; sin tokens (solo 127.0.0.1)
- [x] `hermes -p <perfil> config set gateway.standalone true` y levantar cada gateway en su terminal: `hermes -p <perfil> gateway run` (3 terminales). Agent Card en `http://127.0.0.1:<puerto>/.well-known/agent-card.json` (JSONRPC, protocolo 1.0)
- [ ] Restringir toolsets por perfil (`hermes -p <perfil> tools`): quitar browser, discord, spotify, video, etc. (menos contexto y mínimo privilegio)
- [x] Llamada A2A directa (JSON-RPC `SendMessage` a 9901): respuesta PONG, estado TASK_STATE_COMPLETED, ~24 s (`scripts/send_a2a.ps1`)
- [x] Probar entre agentes: deteccion -> mitigacion con `a2a_call` (OK con `qwen3.5:9b`, 28,9 s; con `qwen3:4b` falló)
- [ ] Configurar modelos auxiliares para que usen el modelo local (`hermes model` -> Configure auxiliary models)
- [ ] Anotar la versión exacta de Hermes en README (v0.21.5+4108.g105568c al iniciar)
- [x] Comparación `qwen3.5:9b` vs `qwen3:4b`: 9b = 7.8 GB, 30%/70% CPU/GPU, PONG en ~4-5 s (warm), a2a_call OK; 4b falla en a2a_call

### Paso 1: banco de pruebas (Docker)
- [x] (escrito, por verificar) `testbed/docker-compose.yml`: objetivo FastAPI (`/login` + Redis), Prometheus, cAdvisor opcional, log JSON en `testbed/logs/`
- [x] (escrito, por verificar) Tráfico legítimo `soc-legit` + 3 atacantes `soc-attacker1..3` (perfil `attack`)
- [x] Banco levantado y `scripts\check_testbed.ps1` pasa las 12 comprobaciones (incluye tc, iptables, stress-ng); detalles en `docs/testbed.md`

### Paso 2: inyectores (`injectors/`)
- [x] (escrito, por verificar) Falla: `latency` (tc netem), `memory` (stress-ng), `redis_down` -> `injectors/inject.py fault --variant ...`
- [x] (escrito, por verificar) DDoS: inundación L7 desde 3 atacantes (`inject.py ddos`); L4 queda fuera por ahora
- [x] (escrito, por verificar) Fuerza bruta contra `/login` desde 1 atacante (`inject.py bruteforce`)
- [x] Cada uno escribe `ground_truth.json` (`t_inject`, etiqueta, parámetros); `inject.py reset` limpia el entorno
- [x] Verificados con `mcp_servers/summary.py`: base 4.5 rps/1 IP/p95 0.6 ms; latency p95 813 ms; DDoS 1145 rps/4 IP/p95 243 ms/CPU 0.5; bruteforce 80 rps/94% de una IP/401=99.7%/CPU 1.0
- [x] Verificados `memory` (mem 0.89, CPU 1.0, p95 11 ms) y `redis_down` (5xx 16%, p95 15 s)
- Nota (mcp 2.x): el SDK 2 renombró `FastMCP` a `MCPServer`; los servidores soportan ambos.
- Nota: el DDoS actual no produce 5xx (solo sube p95 y CPU); si hace falta más impacto subir `--concurrency` a 200-300

### Paso 3: agentes y herramientas MCP
- [x] (escrito, por verificar) `mcp_servers/detection_tools.py`: `get_traffic_summary`, `get_container_status`, `get_log_sample`
- [x] (escrito, por verificar) `mcp_servers/mitigation_tools.py`: `restart_service`, `block_ip`, `rate_limit_ip`, `list_firewall_rules`, `verify_recovery`; allowlist, dry-run y `results/raw/actions.jsonl`. Sin `scale` (nombres/IP fijos; documentar como limitación)
- [ ] Crear `.venv` e instalar `requirements.txt` (`mcp[cli]`), probar con `scripts/test_tools.py` y registrar con `scripts/add_mcp_config.ps1`
- [x] Esquema JSON de mensajes A2A en `docs/a2a_schema.md`
- [x] (escrito, por verificar) `hermes_profiles/<perfil>/SOUL.md` de los 3 agentes; instalar con `scripts/install_souls.ps1`
- [x] Prueba anidada con `a2a_call`: Detección OK y Mitigación ejecutó 3 `block_ip`, pero `a2a_call` expira a 120 s (fijo) y Mitigación no llamó a Documentación -> cadena llevada por el ejecutor (`runner/chain.py`, `runner/a2a_client.py`)
- [x] `python runner/chain.py` con DDoS OK: Detección 18 s + Mitigación 82 s + Documentación 30 s; 3 `block_ip` reales; primer bloqueo a ~73 s de la inyección
- [x] DDoS en ambas condiciones OK (single: MTTR 110 s, cadena 166 s; multi: MTTR 175 s, cadena 307 s); onboarding de Hermes desactivado con `onboarding.seen.profile_build_offered: true` (declinar en `hermes -p <perfil> chat`)
- [x] Reintento de formato (máx. 1 por salto, igual en ambas condiciones; se registra en `retries`)
- [ ] Humo de fuerza bruta, fallas y `normal` (`--scenarios fault,bruteforce,normal --reps 1`)
- [x] (escrito, por crear el perfil) Variante de agente único: perfil `unico` (puerto 9904) con `hermes_profiles/unico/SOUL.md`

### Paso 4: ejecutor (`runner/`)
- [x] (escrito, por probar) `runner/run_experiments.py`: bucle escenario x condición x rep, reanudable; guarda `run.json`, `report.md` y `summary.csv`; escenario extra `normal` para falsos positivos
- [ ] Piloto de 5 corridas por escenario; luego 20

### Paso 5: análisis (`analysis/`)
- [x] (escrito, por probar) `analysis/analyze.py`: Tabla I por escenario/condición con IC bootstrap, fiabilidad, calidad automática del reporte, matrices de confusión y falsos positivos
- [x] (incluido en analyze.py) matriz de confusión e IC bootstrap
- [ ] Rúbrica del reporte en `docs/`

## Antes de subir a GitHub
- [ ] Sin `.env`, tokens ni carpetas de perfiles con estado en el repo
- [ ] LICENSE elegida; README con cómo reproducir

## Notas de entorno
- Config de Hermes en Windows: `C:\Users\leo\AppData\Local\hermes` (NUNCA subir al repo: .env, sesiones, memoria).
- Hermes rechaza modelos con menos de 64K de contexto real; Ollama recorta al contexto de entrenamiento del modelo.
- Hermes usa ~14K tokens de contexto del sistema por turno.
- No usar `OLLAMA_KV_CACHE_TYPE=q4_0` (degrada el rendimiento a 64K).
- `hermes doctor` marca `a2a (system dependency not met)`: se resuelve en el Paso 0-D.
- Pendiente de reproducibilidad: desactivar memoria/skills/session_search en los perfiles (cada tarea A2A ya abre sesión nueva).
- Medición: TTD solo en multiagente (hop de Detección); en ambas condiciones se mide tiempo hasta la primera acción real y MTTR objetivo (monitor cada 5 s).
- Antes del piloto: congelar los prompts (`hermes_profiles/`) y anotar el commit/hash en `docs/NOTAS_PARA_EL_PAPER.md` §2.
