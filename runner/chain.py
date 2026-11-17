"""Cadenas de agentes. Cada salto es un mensaje A2A real; el ejecutor lleva el resultado de un agente al siguiente
(a2a_call de Hermes tiene un límite fijo de 120 s, menor que lo que tarda cada agente con un modelo local).

  python runner/chain.py [--out DIR]          # condición multiagente sobre el estado actual
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from a2a_client import send_message

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mcp_servers"))
from summary import summarize  # noqa: E402

PORTS = {"deteccion": 9901, "mitigacion": 9902, "documentacion": 9903, "unico": 9904}
TRIGGER = ("Analiza el estado actual del servicio siguiendo tu procedimiento: llama primero a tus herramientas "
           "de monitoreo y responde con tu detection_result JSON.")
SINGLE_TRIGGER = ("Analiza el estado actual del servicio y gestiona el incidente completo siguiendo tu procedimiento: "
                  "llama primero a tus herramientas de monitoreo, mitiga, verifica y responde con el JSON y el reporte.")
OK = "TASK_STATE_COMPLETED"


def extract_json(text: str):
    """Primer objeto JSON decodificable del texto que tenga la clave "type" (tolera texto y ```json alrededor)."""
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = dec.raw_decode(text[m.start():])
        except ValueError:
            continue
        if isinstance(obj, dict) and "type" in obj:
            return obj
    return None


def hop(name: str, text: str, timeout: int) -> dict:
    r = send_message(PORTS[name], text, timeout)
    r["agent"] = name
    return r


def hop_json(name: str, text: str, timeout: int, retries: int = 1):
    """Envía el mensaje; si la respuesta no trae JSON legible, repite (máx. `retries` veces). Devuelve (intentos, objeto)."""
    attempts = []
    while True:
        r = hop(name, text, timeout)
        attempts.append(r)
        obj = extract_json(r["text"])
        if obj is not None or len(attempts) > retries or r["state"] != OK:
            return attempts, obj


def run_chain(timeout: int = 900) -> dict:
    """Condición multiagente: Detección -> Mitigación -> Documentación."""
    snapshot = summarize(30)  # medición real previa, para contrastar con lo que reporte Detección
    hops = []
    att, det = hop_json("deteccion", TRIGGER, timeout)
    hops += att
    result = {"snapshot_before": snapshot, "hops": hops, "detection": det, "mitigation": None, "report": None,
              "detect_end": att[-1]["t_end"], "retries": len(att) - 1}
    if det is None or det.get("class") == "healthy":
        return result

    att, mit = hop_json("mitigacion", "detection_result:\n" + json.dumps(det), timeout)
    hops += att
    result["mitigation"] = mit
    result["retries"] += len(att) - 1

    payload = json.dumps(mit) if mit is not None else att[-1]["text"]
    r = hop("documentacion", "mitigation_result:\n" + payload, timeout)
    hops.append(r)
    result["report"] = r["text"]
    return result


def run_single(timeout: int = 900) -> dict:
    """Condición de agente único: un solo agente hace detección, mitigación y reporte."""
    snapshot = summarize(30)
    att, obj = hop_json("unico", SINGLE_TRIGGER, timeout)
    r = att[-1]
    i = r["text"].find("## Qué ocurrió")
    det = obj.get("detection") if obj else None
    mit = {k: v for k, v in obj.items() if k != "detection"} if obj else None
    return {"snapshot_before": snapshot, "hops": att, "detection": det, "mitigation": mit,
            "report": r["text"][i:] if i >= 0 else None, "detect_end": None, "retries": len(att) - 1}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()
    t0 = time.time()
    res = run_chain(a.timeout)
    res["t_total_s"] = round(time.time() - t0, 1)
    for h in res["hops"]:
        print(f"[{h['agent']}] {h['state']} {h['t_end'] - h['t_start']:.1f} s")
    if res["detection"] is None:
        print("\n[!] No se pudo leer el JSON de Detección. Respuesta cruda:\n" + res["hops"][-1]["text"])
    print("\ndetection :", json.dumps(res["detection"], ensure_ascii=False))
    print("mitigation:", json.dumps(res["mitigation"], ensure_ascii=False))
    print("\n--- REPORTE ---\n" + (res["report"] or "(sin reporte)"))
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "chain.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
