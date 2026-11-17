"""Servicio objetivo del banco de pruebas Hermes-SOC.

Endpoints: / , /health , /api/data (depende de Redis), /login (costoso en CPU), /metrics.
Escribe un log de acceso JSON por línea y expone métricas Prometheus.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
LOG_PATH = os.getenv("LOG_PATH", "/logs/access.jsonl")
USERNAME = "admin"
SALT = b"hermes-soc-testbed"
PASSWORD_HASH = hashlib.pbkdf2_hmac(
    "sha256", os.getenv("ADMIN_PASSWORD", "S3cret-testbed").encode(), SALT, 100_000
)
KNOWN_PATHS = {"/", "/health", "/api/data", "/login", "/metrics"}
QUIET_PATHS = {"/health", "/metrics"}  # no se registran en el log ni en las métricas

REQS = Counter("http_requests_total", "Peticiones HTTP", ["method", "path", "status"])
LAT = Histogram(
    "http_request_duration_seconds", "Latencia de peticiones", ["path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
LOGINS = Counter("login_attempts_total", "Intentos de login", ["result"])


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _mem_current():
    v = _read("/sys/fs/cgroup/memory.current")
    return float(v) if v else 0.0


def _mem_limit():
    v = _read("/sys/fs/cgroup/memory.max")
    return float(v) if v and v != "max" else 0.0


def _cpu_seconds():
    v = _read("/sys/fs/cgroup/cpu.stat")
    for line in (v or "").splitlines():
        if line.startswith("usage_usec"):
            return float(line.split()[1]) / 1e6
    return 0.0


# Métricas del propio contenedor (cgroup v2), así no dependemos de cAdvisor
Gauge("soc_target_memory_usage_bytes", "Memoria usada por el contenedor").set_function(_mem_current)
Gauge("soc_target_memory_limit_bytes", "Límite de memoria del contenedor").set_function(_mem_limit)
Gauge("soc_target_cpu_usage_seconds", "CPU acumulada del contenedor (s)").set_function(_cpu_seconds)

app = FastAPI(title="soc-target")
_redis = aioredis.Redis(host=REDIS_HOST, socket_timeout=1, socket_connect_timeout=1)
_log_file = None


def _log(entry: dict) -> None:
    global _log_file
    if _log_file is None:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        _log_file = open(LOG_PATH, "a", buffering=1, encoding="utf-8")
    _log_file.write(json.dumps(entry) + "\n")


@app.middleware("http")
async def observe(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        if request.url.path not in QUIET_PATHS:
            dur = time.perf_counter() - start
            path = request.url.path if request.url.path in KNOWN_PATHS else "other"
            REQS.labels(request.method, path, str(status)).inc()
            LAT.labels(path).observe(dur)
            _log({
                "ts": round(time.time(), 3),
                "ip": request.client.host if request.client else "?",
                "method": request.method,
                "path": request.url.path,
                "status": status,
                "ms": round(dur * 1000, 1),
            })


class Login(BaseModel):
    username: str
    password: str


@app.get("/")
async def index():
    return {"service": "target", "status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/data")
async def data():
    try:
        hits = await _redis.incr("hits")
    except Exception:
        return JSONResponse({"error": "dependency unavailable"}, status_code=503)
    return {"hits": hits}


@app.post("/login")
async def login(body: Login):
    digest = await asyncio.to_thread(
        hashlib.pbkdf2_hmac, "sha256", body.password.encode(), SALT, 100_000
    )
    if body.username == USERNAME and hmac.compare_digest(digest, PASSWORD_HASH):
        LOGINS.labels("ok").inc()
        return {"token": "demo-token"}
    LOGINS.labels("fail").inc()
    return JSONResponse({"error": "invalid credentials"}, status_code=401)


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
