"""Ejecutor de experimentos: escenario x condición x repeticiones (reanudable).

  python runner/run_experiments.py --reps 5 --out results/raw/piloto
  python runner/run_experiments.py --scenarios ddos --conditions multi --reps 1 --out results/raw/prueba
  python runner/run_experiments.py --reps 5 --dry-run        # solo muestra el plan

Por corrida: reset del entorno -> tráfico base -> inyección (t_inject) -> cadena de agentes ->
monitor objetivo cada 5 s (MTTR, recuperación) -> acciones reales (actions.jsonl) -> run.json + fila en summary.csv.
Escenarios: fault (variante rota latency/memory/redis_down por repetición), ddos, bruteforce, normal (sin inyección, para falsos positivos).
Condiciones: multi (3 agentes) y single (1 agente). Si una corrida ya tiene run.json se salta.
"""
import argparse
import csv
import json
import random
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("injectors", "mcp_servers", "runner"):
    sys.path.insert(0, str(ROOT / sub))
import chain as ch  # noqa: E402
import inject as inj  # noqa: E402
from summary import summarize  # noqa: E402

ACTION_LOG = ROOT / "results" / "raw" / "actions.jsonl"
FAULT_VARIANTS = ["latency", "memory", "redis_down"]
TRUE_SUBTYPE = {"latency": "latency", "memory": "memory", "redis_down": "dependency",
                "ddos": "ddos", "bruteforce": "bruteforce", "normal": "none"}
CSV_FIELDS = ["run_id", "scenario", "variant", "condition", "rep", "label_true", "subtype_true",
              "pred_class", "pred_subtype", "class_ok", "subtype_ok", "detection_parsed", "report_present",
              "t_detect_s", "t_first_action_s", "mttr_s", "healthy_at_end", "n_actions", "wrong_ip_actions",
              "unneeded_actions", "claimed_actions", "retries", "timed_out", "quiesce_s", "chain_s", "hop_states"]


def judge(s):
    """Criterio objetivo: (valid, healthy). valid=False si hay poco tráfico para juzgar."""
    if s["requests"] < 15:
        return False, False
    bad = ((s["p95_latency_ms"] or 0) > 100 or s["error_5xx_rate"] > 0.02 or (s["memory_ratio"] or 0) > 0.8
           or s["rps"] > 100 or (s["login_requests"] > 20 and s["login_401_rate"] > 0.5))
    return True, not bad


class Monitor(threading.Thread):
    def __init__(self, interval=5, window=10):
        super().__init__(daemon=True)
        self.interval, self.window, self.series, self._stop_ev = interval, window, [], threading.Event()

    def run(self):
        while not self._stop_ev.is_set():
            try:
                s = summarize(self.window)
                valid, ok = judge(s)
                self.series.append({"t": time.time(), "valid": valid, "healthy": ok, "rps": s["rps"],
                                    "p95": s["p95_latency_ms"], "err5xx": s["error_5xx_rate"],
                                    "mem": s["memory_ratio"], "ips": s["unique_ips"]})
            except Exception:
                pass
            self._stop_ev.wait(self.interval)

    def stop(self):
        self._stop_ev.set()
        self.join(timeout=10)


def mttr(series, t_inject):
    """Segundos desde t_inject hasta 2 mediciones sanas seguidas tras haber visto el servicio mal."""
    seen_bad, streak, first = False, 0, None
    for p in series:
        if p["t"] < t_inject or not p["valid"]:
            continue
        if not p["healthy"]:
            seen_bad, streak, first = True, 0, None
        elif seen_bad:
            streak += 1
            first = first or p["t"]
            if streak >= 2:
                return round(first - t_inject, 1)
    return None


def read_actions(t_from, t_to):
    if not ACTION_LOG.exists():
        return []
    out = []
    for line in ACTION_LOG.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        if t_from <= a["ts"] <= t_to and not a.get("dry_run"):
            out.append(a)
    return out


def agent_names(conditions):
    return (["deteccion", "mitigacion", "documentacion"] if "multi" in conditions else []) + (["unico"] if "single" in conditions else [])


def last_action_ts():
    if not ACTION_LOG.exists():
        return 0.0
    for line in reversed(ACTION_LOG.read_text(encoding="utf-8").splitlines()[-20:]):
        try:
            return float(json.loads(line)["ts"])
        except (ValueError, KeyError):
            continue
    return 0.0


def quiesce(names, max_wait=1800, quiet_s=60, ping_s=60):
    """Espera a que ningún agente siga trabajando en una corrida anterior.
    Un salto que expira (300 s en el servidor A2A de Hermes) NO detiene al agente: sigue ejecutando herramientas y
    ocupando el modelo, lo que contamina la corrida siguiente. Se espera a que (1) no haya acciones nuevas en
    `quiet_s` s y (2) todos los agentes respondan un PING en menos de `ping_s` s. Devuelve los s esperados o None."""
    t0 = time.time()
    while time.time() - t0 < max_wait:
        if time.time() - last_action_ts() < quiet_s:
            time.sleep(10)
            continue
        ok = True
        for n in names:
            r = ch.send_message(ch.PORTS[n], "Responde exactamente: PONG", ping_s)
            if r["state"] != "TASK_STATE_COMPLETED" or "PONG" not in r["text"].upper():
                ok = False
                break
        if ok:
            return round(time.time() - t0, 1)
        time.sleep(10)
    return None


def ensure_agents(conditions):
    names = agent_names(conditions)
    down = []
    for n in names:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{ch.PORTS[n]}/.well-known/agent-card.json", timeout=5)
        except Exception:
            down.append(f"{n} ({ch.PORTS[n]})")
    if down:
        sys.exit("Agentes sin responder: " + ", ".join(down) + ". Ejecuta scripts\\start_agents.ps1")


def run_one(sc, cond, rep, out, a):
    rid = f"{sc}_{cond}_{rep:02d}"
    rdir = out / rid
    if (rdir / "run.json").exists():
        print(f"[salto] {rid}")
        return
    rdir.mkdir(parents=True, exist_ok=True)
    print(f"[inicio] {rid}", flush=True)
    q = quiesce(a.agents, a.quiesce_max)
    if q is None:
        sys.exit("Los agentes no se calmaron a tiempo: revisa las ventanas de los agentes y reanuda.")
    inj.reset_env()
    time.sleep(a.baseline)
    mon = Monitor()
    mon.start()
    try:
        t_inject = time.time()
        if sc == "fault":
            gt = inj.inject_fault(FAULT_VARIANTS[rep % 3], a.attack_seconds)
        elif sc in ("ddos", "bruteforce"):
            gt = inj.inject_attack(sc, a.attack_seconds, 100 if sc == "ddos" else 20)
        else:
            gt = {"scenario": "normal", "label": "healthy", "variant": "normal", "params": {}, "sources": []}
        gt["t_inject"] = t_inject
        time.sleep(a.settle)
        t0 = time.time()
        res = ch.run_chain(a.timeout) if cond == "multi" else ch.run_single(a.timeout)
        t1 = time.time()
        time.sleep(a.tail)
    finally:
        mon.stop()

    key = gt["variant"] if sc == "fault" else sc
    sub_true = TRUE_SUBTYPE[key]
    det = res.get("detection") or {}
    mit = res.get("mitigation") or {}
    acts = read_actions(t0 - 1, t1 + a.tail)
    ips_true = set(gt.get("sources", []))
    wrong_ip = [x for x in acts if x["tool"] in ("block_ip", "rate_limit_ip") and x["args"].get("ip") not in ips_true]
    valid_tail = [p for p in mon.series if p["t"] > t1 and p["valid"]]
    claimed = [x for x in (mit.get("actions") if isinstance(mit.get("actions"), list) else [])
               if isinstance(x, dict) and str(x.get("tool", "")).split("__")[-1] in ("restart_service", "block_ip", "rate_limit_ip")]
    pc, ps = str(det.get("class", "")).lower(), str(det.get("subtype", "")).lower()
    row = {
        "run_id": rid, "scenario": sc, "variant": gt["variant"], "condition": cond, "rep": rep,
        "label_true": gt["label"], "subtype_true": sub_true, "pred_class": pc or None, "pred_subtype": ps or None,
        "class_ok": pc == gt["label"], "subtype_ok": ps == sub_true, "detection_parsed": bool(det),
        "report_present": bool(res.get("report")),
        "t_detect_s": round(res["detect_end"] - t_inject, 1) if res.get("detect_end") and sc != "normal" else None,
        "t_first_action_s": round(min(x["ts"] for x in acts) - t_inject, 1) if acts and sc != "normal" else None,
        "mttr_s": mttr(mon.series, t_inject) if sc != "normal" else None,
        "healthy_at_end": all(p["healthy"] for p in valid_tail[-2:]) if valid_tail else None,
        "n_actions": len(acts), "wrong_ip_actions": len(wrong_ip),
        "unneeded_actions": len(acts) if sc == "normal" else 0, "claimed_actions": len(claimed), "retries": res.get("retries", 0),
        "timed_out": any(h["state"] != "TASK_STATE_COMPLETED" for h in res["hops"]), "quiesce_s": q,
        "chain_s": round(t1 - t0, 1), "hop_states": "|".join(h["state"] for h in res["hops"]),
    }
    (rdir / "run.json").write_text(json.dumps({"row": row, "ground_truth": gt, "chain": res, "actions": acts,
                                               "series": mon.series}, indent=2, ensure_ascii=False), encoding="utf-8")
    if res.get("report"):
        (rdir / "report.md").write_text(res["report"], encoding="utf-8")
    csv_path = out / "summary.csv"
    new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    print(f"[fin] {rid}: clase={pc} subtipo={ps} ok={row['class_ok']} mttr={row['mttr_s']} acciones={len(acts)} cadena={row['chain_s']}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="fault,ddos,bruteforce")
    ap.add_argument("--conditions", default="multi,single")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out", default="results/raw/piloto")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--baseline", type=int, default=15, help="s de tráfico base antes de inyectar")
    ap.add_argument("--settle", type=int, default=20, help="s entre la inyección y el inicio de los agentes")
    ap.add_argument("--tail", type=int, default=15, help="s de monitoreo tras terminar la cadena")
    ap.add_argument("--attack-seconds", type=int, default=900)
    ap.add_argument("--timeout", type=int, default=900, help="timeout por salto A2A (s)")
    ap.add_argument("--quiesce-max", type=int, default=1800, help="máx. s de espera a que los agentes queden libres entre corridas")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    scs, conds = a.scenarios.split(","), a.conditions.split(",")
    rng = random.Random(a.seed)
    plan = []
    for rep in range(a.reps):  # repeticiones en bloques y orden aleatorio dentro de cada bloque
        block = [(s, c, rep) for s in scs for c in conds]
        rng.shuffle(block)
        plan += block
    out = ROOT / a.out if not Path(a.out).is_absolute() else Path(a.out)
    print(f"{len(plan)} corridas -> {out}  (~{len(plan) * 5 // 60} h a ~5 min por corrida)")
    if a.dry_run:
        for s, c, r in plan:
            print(" ", s, c, r)
        return
    a.agents = agent_names(conds)
    ensure_agents(conds)
    out.mkdir(parents=True, exist_ok=True)
    try:
        for s, c, r in plan:
            run_one(s, c, r, out, a)
    finally:
        inj.reset_env()


if __name__ == "__main__":
    main()
