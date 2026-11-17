"""Cliente mínimo A2A (JSON-RPC SendMessage, protocolo 1.0) hacia los agentes Hermes locales."""
import json
import time
import urllib.request
import uuid


def send_message(port: int, text: str, timeout: int = 900) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "SendMessage",
        "params": {"message": {"messageId": str(uuid.uuid4()), "role": "ROLE_USER", "parts": [{"text": text}]}},
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except Exception as e:  # timeout, conexión, etc.
        return {"state": "ERROR", "text": "", "error": str(e), "t_start": t0, "t_end": time.time()}
    status = resp.get("result", {}).get("task", {}).get("status", {})
    parts = status.get("message", {}).get("parts", [])
    return {
        "state": status.get("state", "UNKNOWN"),
        "text": "\n".join(p.get("text", "") for p in parts),
        "t_start": t0, "t_end": time.time(),
    }
