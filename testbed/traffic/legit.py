"""Tráfico legítimo de fondo. Cada 5 s imprime una línea JSON con ok/err/p95 (útil para medir efectividad)."""
import asyncio
import json
import os
import random
import time

import aiohttp

TARGET = os.getenv("TARGET_URL", "http://target:8000")
RATE = float(os.getenv("RATE", "5"))  # peticiones por segundo (proceso de Poisson)
USER = os.getenv("LOGIN_USER", "admin")
PASSWORD = os.getenv("LOGIN_PASSWORD", "S3cret-testbed")

window = {"ok": 0, "err": 0, "lat": []}


async def one(session: aiohttp.ClientSession) -> None:
    r = random.random()
    start = time.perf_counter()
    try:
        if r < 0.70:
            ctx = session.get(f"{TARGET}/")
        elif r < 0.95:
            ctx = session.get(f"{TARGET}/api/data")
        else:
            ctx = session.post(f"{TARGET}/login", json={"username": USER, "password": PASSWORD})
        async with ctx as resp:
            await resp.read()
            good = resp.status < 400
    except Exception:
        good = False
    window["ok" if good else "err"] += 1
    window["lat"].append((time.perf_counter() - start) * 1000)


async def reporter() -> None:
    while True:
        await asyncio.sleep(5)
        lat = sorted(window["lat"])
        p95 = round(lat[int(0.95 * (len(lat) - 1))], 1) if lat else None
        print(json.dumps({"ts": round(time.time(), 3), "ok": window["ok"], "err": window["err"], "p95_ms": p95}), flush=True)
        window.update(ok=0, err=0, lat=[])


async def main() -> None:
    tasks = set()
    asyncio.create_task(reporter())
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        while True:
            t = asyncio.create_task(one(session))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            await asyncio.sleep(random.expovariate(RATE))


if __name__ == "__main__":
    asyncio.run(main())
