"""Servidor MCP de Detección (solo lectura). Devuelve resúmenes, no logs crudos.

Registro en Hermes: ver scripts/add_mcp_config.ps1.
"""
import json
import subprocess
from pathlib import Path

from summary import LOG_PATH, summarize

SOC_CONTAINERS = ["soc-target", "soc-redis", "soc-prometheus", "soc-legit"]


def get_traffic_summary(window_s: int = 30) -> dict:
    """Aggregated stats of the monitored web service over the last window_s seconds (5-300):
    requests/s, distinct client IPs, top IPs with their share, HTTP status counts, 5xx rate,
    /login volume and share of 401 responses, p95 latency (ms), memory ratio (0-1) and CPU cores used."""
    return summarize(max(5, min(int(window_s), 300)))


def get_container_status() -> list:
    """State of the testbed containers (running/exited) and health. Use it to spot a stopped dependency."""
    out = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30).stdout
    res = []
    for line in out.splitlines():
        try:
            c = json.loads(line)
        except ValueError:
            continue
        if c.get("Names") in SOC_CONTAINERS:
            res.append({"name": c["Names"], "state": c.get("State"), "status": c.get("Status")})
    return res


def get_log_sample(n: int = 10) -> list:
    """Last n (max 15) raw access-log entries: ts, ip, method, path, status, ms. Use sparingly; prefer get_traffic_summary."""
    n = max(1, min(int(n), 15))
    p = Path(LOG_PATH)
    if not p.exists():
        return []
    with open(p, "rb") as f:
        f.seek(max(0, p.stat().st_size - 200_000))
        lines = f.read().decode("utf-8", errors="ignore").splitlines()[-n:]
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


if __name__ == "__main__":
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server

    mcp = Server("soc-detection")
    for fn in (get_traffic_summary, get_container_status, get_log_sample):
        mcp.tool()(fn)
    mcp.run()
