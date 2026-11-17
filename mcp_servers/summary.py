"""Resúmenes compactos del estado del objetivo (base de las herramientas de Detección).

Devuelve cifras agregadas, no logs crudos, para no saturar el contexto del modelo.
  python mcp_servers/summary.py --window 30
"""
import argparse
import json
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "testbed" / "logs" / "access.jsonl"
PROM = "http://localhost:9090"
TAIL_BYTES = 32 * 1024 * 1024


def _tail_entries(path, since):
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        data = f.read().decode("utf-8", errors="ignore")
    out = []
    for line in data.splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("ts", 0) >= since:
            out.append(e)
    return out


def prom_query(q):
    url = f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": q})
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            res = json.load(r)["data"]["result"]
        return float(res[0]["value"][1]) if res else None
    except Exception:
        return None


def summarize(window_s=30, log_path=LOG_PATH, now=None):
    now = now or time.time()
    es = _tail_entries(Path(log_path), now - window_s) if Path(log_path).exists() else []
    n = len(es)
    ips = Counter(e["ip"] for e in es)
    status = Counter(f"{e['status'] // 100}xx" for e in es)
    login = [e for e in es if e["path"] == "/login"]
    lat = sorted(e["ms"] for e in es)
    mem = prom_query("soc_target_memory_usage_bytes")
    lim = prom_query("soc_target_memory_limit_bytes")
    return {
        "window_s": window_s,
        "requests": n,
        "rps": round(n / window_s, 1),
        "unique_ips": len(ips),
        "top_ips": [{"ip": ip, "count": c, "share": round(c / n, 2)} for ip, c in ips.most_common(5)] if n else [],
        "status_counts": dict(status),
        "error_5xx_rate": round(status.get("5xx", 0) / n, 3) if n else 0.0,
        "login_requests": len(login),
        "login_401_rate": round(sum(1 for e in login if e["status"] == 401) / len(login), 3) if login else 0.0,
        "p95_latency_ms": round(lat[int(0.95 * (n - 1))], 1) if n else None,
        "memory_ratio": round(mem / lim, 2) if mem and lim else None,
        "cpu_cores_30s": (lambda v: round(v, 2) if v is not None else None)(prom_query("rate(soc_target_cpu_usage_seconds[30s])")),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=30)
    print(json.dumps(summarize(ap.parse_args().window), indent=2))
