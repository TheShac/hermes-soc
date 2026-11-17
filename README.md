# Hermes-SOC

Framework multiagente (Detección, Mitigación, Documentación) sobre Hermes Agent,
comunicado por A2A, para clasificar y tratar fallas operativas vs. ataques en servicios.

> Uso solo en el banco de pruebas local (contenedores). Los scripts de ataque
> apuntan únicamente a los contenedores definidos en `docker-compose.yml`.

## Requisitos
- Windows con Docker Desktop (WSL2), Python 3.11+
- Hermes Agent y Ollama (modelo `qwen3:8b`)

## Estructura
Ver `PLAN.md` para el plan de trabajo y el estado de cada paso.

Bitácora de lo implementado (qué funciona y qué no): [docs/BITACORA.md](docs/BITACORA.md).

Notas metodológicas para el paper/taller: [docs/NOTAS_PARA_EL_PAPER.md](docs/NOTAS_PARA_EL_PAPER.md).
