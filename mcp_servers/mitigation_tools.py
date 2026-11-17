"""Servidor MCP de Mitigación. Acciones acotadas: allowlist de objetivos, dry-run y registro de auditoría.

- Solo se pueden reiniciar los servicios `target` y `redis`.
- Solo se pueden bloquear/limitar IP del rango de atacantes/clientes; nunca las IP protegidas
  (objetivo, Redis, Prometheus, tráfico legítimo, puerta de enlace).
- MITIGATION_DRY_RUN=1 (o dry_run=true) simula sin ejecutar.
- Cada acción se anota en results/raw/actions.jsonl (sirve para calcular el MTTR).
"""
import ipaddress
import json
import os
import subprocess
import time
from pathlib import Path

from summary import summarize

ROOT = Path(__file__).resolve().parent.parent
ACTION_LOG = Path(os.getenv("SOC_ACTION_LOG", ROOT / "results" / "raw" / "actions.jsonl"))
SERVICES = {"target": "soc-target", "redis": "soc-redis"}
NETWORK = ipaddress.ip_network("172.28.0.0/24")
PROTECTED = {ipaddress.ip_address(x) for x in
             ("172.28.0.1", "172.28.0.10", "172.28.0.11", "172.28.0.20", "172.28.0.30", "172.28.0.50")}
TARGET = "soc-target"


def _check_ip(ip: str):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None, "invalid IP address"
    if addr not in NETWORK:
        return None, "IP outside the monitored network"
    if addr in PROTECTED:
        return None, "IP is protected (infrastructure or legitimate clients); refusing"
    return str(addr), None


def _run(cmd, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()[-300:]


def _act(tool, args, cmds, dry_run):
    dry = bool(dry_run) or os.getenv("MITIGATION_DRY_RUN", "0") == "1"
    results = []
    for c in cmds:
        if dry:
            results.append({"cmd": " ".join(c), "dry_run": True})
        else:
            rc, out = _run(c)
            results.append({"cmd": " ".join(c), "rc": rc, "out": out})
    ok = dry or all(r["rc"] == 0 for r in results)
    rec = {"ts": round(time.time(), 3), "tool": tool, "args": args, "dry_run": dry, "ok": ok}
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ACTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return {"ok": ok, "dry_run": dry, "results": results}


def restart_service(service: str, dry_run: bool = False) -> dict:
    """Restart one service container. service must be 'target' (the web service; clears
    network rules and stress/latency faults) or 'redis' (its dependency)."""
    if service not in SERVICES:
        return {"ok": False, "error": f"service must be one of {sorted(SERVICES)}"}
    return _act("restart_service", {"service": service}, [["docker", "restart", "-t", "2", SERVICES[service]]], dry_run)


def block_ip(ip: str, dry_run: bool = False) -> dict:
    """Drop all traffic from one source IP at the target (iptables). Use for confirmed attack sources only."""
    addr, err = _check_ip(ip)
    if err:
        return {"ok": False, "error": err}
    rc, _ = _run(["docker", "exec", TARGET, "iptables", "-C", "INPUT", "-s", addr, "-j", "DROP"])
    if rc == 0:
        return {"ok": True, "note": "already blocked"}
    return _act("block_ip", {"ip": addr}, [["docker", "exec", TARGET, "iptables", "-I", "INPUT", "1", "-s", addr, "-j", "DROP"]], dry_run)


def rate_limit_ip(ip: str, max_packets_per_second: int = 50, dry_run: bool = False) -> dict:
    """Limit one source IP to max_packets_per_second (10-1000) instead of blocking it; excess packets are dropped."""
    addr, err = _check_ip(ip)
    if err:
        return {"ok": False, "error": err}
    n = max(10, min(int(max_packets_per_second), 1000))
    cmds = [
        ["docker", "exec", TARGET, "iptables", "-I", "INPUT", "1", "-s", addr, "-j", "DROP"],
        ["docker", "exec", TARGET, "iptables", "-I", "INPUT", "1", "-s", addr, "-m", "limit",
         "--limit", f"{n}/second", "--limit-burst", str(n * 2), "-j", "ACCEPT"],
    ]
    return _act("rate_limit_ip", {"ip": addr, "pps": n}, cmds, dry_run)


def list_firewall_rules() -> dict:
    """Show the current INPUT firewall rules at the target (what is already blocked or limited)."""
    rc, out = _run(["docker", "exec", TARGET, "iptables", "-S", "INPUT"])
    return {"ok": rc == 0, "rules": out.splitlines()}


def verify_recovery(wait_s: int = 15) -> dict:
    """Wait wait_s seconds (5-30), then check whether the service looks healthy using only the traffic
    seen during that wait. Returns healthy (bool), the reasons it is not, and the summary."""
    w = max(5, min(int(wait_s), 30))
    time.sleep(w)
    s = summarize(w)
    reasons = []
    if s["requests"] < 20:
        reasons.append("insufficient traffic to judge")
    if s["p95_latency_ms"] is not None and s["p95_latency_ms"] > 100:
        reasons.append(f"p95 latency {s['p95_latency_ms']} ms > 100")
    if s["error_5xx_rate"] > 0.02:
        reasons.append(f"5xx rate {s['error_5xx_rate']} > 0.02")
    if s["memory_ratio"] is not None and s["memory_ratio"] > 0.8:
        reasons.append(f"memory ratio {s['memory_ratio']} > 0.8")
    if s["rps"] > 100:
        reasons.append(f"traffic {s['rps']} rps still high")
    if s["login_requests"] > 20 and s["login_401_rate"] > 0.5:
        reasons.append("many failed logins still arriving")
    return {"healthy": not reasons, "reasons": reasons, "summary": s}


if __name__ == "__main__":
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server

    mcp = Server("soc-mitigation")
    for fn in (restart_service, block_ip, rate_limit_ip, list_firewall_rules, verify_recovery):
        mcp.tool()(fn)
    mcp.run()
