"""Prueba las herramientas MCP sin Hermes (llamando a las funciones directamente).
  python scripts/test_tools.py          # solo lectura + dry-run (no cambia nada)
  python scripts/test_tools.py --real   # además bloquea y desbloquea una IP de atacante
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_servers"))
import detection_tools as d  # noqa: E402
import mitigation_tools as m  # noqa: E402


def show(title, obj):
    print(f"\n== {title}\n{json.dumps(obj, indent=2, ensure_ascii=False)}")


show("get_traffic_summary", d.get_traffic_summary(20))
show("get_container_status", d.get_container_status())
show("get_log_sample(3)", d.get_log_sample(3))
show("restart_service dry-run", m.restart_service("target", dry_run=True))
show("restart_service inválido", m.restart_service("prometheus"))
show("block_ip IP protegida (debe rechazar)", m.block_ip("172.28.0.50"))
show("block_ip fuera de red (debe rechazar)", m.block_ip("8.8.8.8"))
show("block_ip dry-run", m.block_ip("172.28.0.101", dry_run=True))
if "--real" in sys.argv:
    show("block_ip real", m.block_ip("172.28.0.101"))
    show("list_firewall_rules", m.list_firewall_rules())
    show("rate_limit_ip real", m.rate_limit_ip("172.28.0.102", 50))
    show("list_firewall_rules", m.list_firewall_rules())
    subprocess.run(["docker", "exec", "soc-target", "iptables", "-F", "INPUT"])
    print("\n(reglas de prueba eliminadas)")
