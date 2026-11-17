# Banco de pruebas

Red Docker fija `172.28.0.0/24` (compose en `testbed/docker-compose.yml`).

| Contenedor | IP | Rol |
|---|---|---|
| soc-target | 172.28.0.10 | Servicio FastAPI: `/`, `/health`, `/api/data` (Redis), `/login`, `/metrics` |
| soc-redis | 172.28.0.11 | Dependencia del objetivo |
| soc-prometheus | 172.28.0.20 | Métricas (scrape cada 5 s), UI en http://localhost:9090 |
| soc-legit | 172.28.0.50 | Tráfico legítimo (5 req/s por defecto) |
| soc-attacker1..3 | 172.28.0.101-103 | Atacantes (perfil `attack`, inactivos hasta que un inyector los use) |
| soc-cadvisor | 172.28.0.30 | Opcional (perfil `cadvisor`) |

Credencial legítima del objetivo: `admin` / `S3cret-testbed` (solo del banco de pruebas).

## Datos que consumirá Detección
- Log de acceso JSON (una línea por petición): `testbed/logs/access.jsonl` con `ts, ip, method, path, status, ms`.
- Prometheus: `http_requests_total`, `http_request_duration_seconds`, `login_attempts_total`, `soc_target_memory_usage_bytes`, `soc_target_memory_limit_bytes`, `soc_target_cpu_usage_seconds`.
- El tráfico legítimo imprime cada 5 s `{"ok","err","p95_ms"}` (`docker logs soc-legit`), útil para medir efectividad.

## Uso
```powershell
cd testbed
docker compose up -d --build
docker compose --profile attack up -d      # atacantes (Paso 2)
cd ..
.\scripts\check_testbed.ps1
docker compose -f testbed/docker-compose.yml down   # apagar
```

## Inyectores y resumen
```powershell
python injectors/inject.py reset                       # entorno limpio
python injectors/inject.py fault --variant latency     # o memory | redis_down
python injectors/inject.py ddos
python injectors/inject.py bruteforce
python mcp_servers/summary.py --window 30              # lo que verá Detección
```
Las fallas persisten hasta corregirlas (o `reset`); los ataques duran `--duration` s (300 por defecto).
Cada inyección guarda `results/raw/manual_<t>/ground_truth.json`.
