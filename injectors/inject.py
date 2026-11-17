"""Inyectores de escenarios del banco de pruebas Hermes-SOC (se ejecutan en Windows, usan la CLI de docker).

  python injectors/inject.py fault --variant latency|memory|redis_down [--out DIR]
  python injectors/inject.py ddos [--duration 300] [--concurrency 100] [--out DIR]
  python injectors/inject.py bruteforce [--duration 300] [--concurrency 20] [--out DIR]
  python injectors/inject.py reset

Las fallas persisten hasta que se corrigen (o se hace reset): eso permite medir el MTTR.
Cada inyección escribe DIR/ground_truth.json con t_inject (epoch s), etiqueta y parámetros.
"""
import argparse
import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

TARGET = "soc-target"
REDIS = "soc-redis"
ATTACKERS = {"soc-attacker1": "172.28.0.101", "soc-attacker2": "172.28.0.102", "soc-attacker3": "172.28.0.103"}
ROOT = Path(__file__).resolve().parent.parent


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def wait_healthy(timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        r = docker("inspect", "-f", "{{.State.Health.Status}}", TARGET, check=False)
        if r.stdout.strip() == "healthy":
            return
        time.sleep(1)
    raise RuntimeError("soc-target no llegó a 'healthy'")


def reset_env():
    """Deja el entorno limpio: sin ataques ni fallas, reglas de red limpias y log vacío."""
    docker("restart", "-t", "1", *ATTACKERS, check=False)
    docker("start", REDIS, check=False)
    docker("restart", "-t", "2", REDIS, TARGET)
    wait_healthy()
    docker("exec", TARGET, "sh", "-c", ": > /logs/access.jsonl")


def inject_fault(variant, duration):
    if variant == "latency":
        docker("exec", TARGET, "tc", "qdisc", "replace", "dev", "eth0", "root", "netem", "delay", "800ms", "100ms")
        params = {"delay_ms": 800, "jitter_ms": 100}
    elif variant == "memory":
        docker("exec", "-d", TARGET, "stress-ng", "--vm", "1", "--vm-bytes", "400M", "--vm-keep", "--timeout", f"{duration}s")
        params = {"vm_bytes": "400M", "timeout_s": duration}
    elif variant == "redis_down":
        docker("stop", "-t", "1", REDIS)
        params = {"stopped": REDIS}
    else:
        raise SystemExit(f"variante desconocida: {variant}")
    return {"scenario": "fault", "label": "fault", "variant": variant, "params": params, "sources": []}


def inject_attack(kind, duration, concurrency):
    mode, names = ("flood", list(ATTACKERS)) if kind == "ddos" else ("bruteforce", ["soc-attacker1"])
    for n in names:
        docker("exec", "-d", n, "python", "/injectors/attack_http.py", "--mode", mode,
               "--concurrency", str(concurrency), "--duration", str(duration))
    return {"scenario": kind, "label": "attack", "variant": mode,
            "params": {"duration_s": duration, "concurrency_per_source": concurrency},
            "sources": [ATTACKERS[n] for n in names]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", choices=["fault", "ddos", "bruteforce", "reset"])
    ap.add_argument("--variant", default="latency")
    ap.add_argument("--duration", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    if a.scenario == "reset":
        reset_env()
        print("entorno limpio")
        return

    t0 = time.time()
    if a.scenario == "fault":
        gt = inject_fault(a.variant, a.duration)
    else:
        conc = a.concurrency or (100 if a.scenario == "ddos" else 20)
        gt = inject_attack(a.scenario, a.duration, conc)
    gt["t_inject"] = t0
    gt["t_inject_iso"] = datetime.datetime.fromtimestamp(t0).isoformat(timespec="seconds")

    out = Path(a.out) if a.out else ROOT / "results" / "raw" / f"manual_{int(t0)}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ground_truth.json").write_text(json.dumps(gt, indent=2), encoding="utf-8")
    print(json.dumps(gt, indent=2))


if __name__ == "__main__":
    sys.exit(main())
