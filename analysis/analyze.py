"""Análisis de resultados (solo librería estándar).
  python analysis/analyze.py results/raw/piloto      -> imprime y guarda results/raw/piloto/resumen.md
Tabla I: precisión de clasificación, MTTR (IC bootstrap 95 %), recuperación, falsos positivos, calidad del reporte,
más fiabilidad (JSON válido, reintentos, acciones declaradas vs. reales) y matrices de confusión.
"""
import csv
import json
import random
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REQ_HEADINGS = ["## Qué ocurrió", "## Cómo se detectó", "## Acción tomada", "## Prevención"]
IP_RE = re.compile(r"172\.28\.0\.\d+")
INFRA_IPS = {"172.28.0.1", "172.28.0.10", "172.28.0.11", "172.28.0.20", "172.28.0.30", "172.28.0.50"}
MUTATING = {"restart_service", "block_ip", "rate_limit_ip"}
CJK_RE = re.compile(r"[぀-ヿ㐀-鿿]")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def boot_ci(vals, n=4000, seed=1):
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return None
    rng = random.Random(seed)
    m = sorted(statistics.fmean(rng.choices(vals, k=len(vals))) for _ in range(n))
    return m[int(0.025 * n)], m[int(0.975 * n) - 1]


def fmt(vals, d=1):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "-"
    ci = boot_ci(vals)
    base = f"{statistics.fmean(vals):.{d}f}"
    return base + (f" [{ci[0]:.{d}f}-{ci[1]:.{d}f}]" if ci else "") + f" (n={len(vals)})"


def pct(flags):
    return f"{100 * sum(flags) / len(flags):.0f} %" if flags else "-"


def report_quality(run):
    rep = (run["chain"].get("report") or "")
    src = set(run["ground_truth"].get("sources", []))
    ips = set(IP_RE.findall(rep))
    return {
        "complete": all(h in rep for h in REQ_HEADINGS),
        "ips_ok": ips <= (src | INFRA_IPS),
        "cjk_leak": bool(CJK_RE.search(rep)),
    }


def _key(a):
    args = a.get("args") or {}
    return (str(a.get("tool", "")).split("__")[-1], args.get("ip") or args.get("service"))


def actions_mismatch(run):
    claimed = (run["chain"].get("mitigation") or {}).get("actions") or []
    claimed = Counter(_key(a) for a in claimed if isinstance(a, dict) and _key(a)[0] in MUTATING)
    actual = Counter(_key(a) for a in run["actions"] if _key(a)[0] in MUTATING)
    return claimed != actual


def evidence_ok(run):
    """True si el rps que reporta Detección es coherente con la medición real previa (descarta cifras inventadas)."""
    det = run["chain"].get("detection") or {}
    snap = run["chain"].get("snapshot_before") or {}
    rep = (det.get("evidence") or {}).get("rps")
    real = snap.get("rps")
    if rep is None or real is None:
        return False
    try:
        rep = float(rep)
    except (TypeError, ValueError):
        return False
    return abs(rep - real) <= max(3.0, 0.35 * real)


def main(d):
    d = Path(d)
    rows = list(csv.DictReader(open(d / "summary.csv", encoding="utf-8")))
    runs = {}
    for r in rows:
        p = d / r["run_id"] / "run.json"
        if p.exists():
            runs[r["run_id"]] = json.loads(p.read_text(encoding="utf-8"))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["scenario"], r["condition"])].append(r)

    out = [f"# Resumen de resultados: {d.name}\n", f"{len(rows)} corridas. Media [IC bootstrap 95 %] (n).\n",
           "## Tabla I por escenario y condición\n",
           "| Escenario | Cond. | Corridas | Clase OK | Subtipo OK | JSON válido | Reintentos | TTD (s) | 1ª acción (s) | MTTR (s) | Sano al final | Acc. IP errónea | Acc. declaradas≠reales | Evidencia coherente | Reporte completo | IP correctas | Texto CJK |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (sc, cond), rs in sorted(groups.items()):
        rq = [report_quality(runs[r["run_id"]]) for r in rs if r["run_id"] in runs and runs[r["run_id"]]["chain"].get("report")]
        mism = [actions_mismatch(runs[r["run_id"]]) for r in rs if r["run_id"] in runs]
        evid = [evidence_ok(runs[r["run_id"]]) for r in rs if r["run_id"] in runs]
        out.append("| " + " | ".join([
            sc, cond, str(len(rs)),
            pct([r["class_ok"] == "True" for r in rs]), pct([r["subtype_ok"] == "True" for r in rs]),
            pct([r["detection_parsed"] == "True" for r in rs]),
            f"{sum(num(r['retries']) or 0 for r in rs):.0f}",
            fmt([num(r["t_detect_s"]) for r in rs]), fmt([num(r["t_first_action_s"]) for r in rs]),
            fmt([num(r["mttr_s"]) for r in rs]),
            pct([r["healthy_at_end"] == "True" for r in rs if r["healthy_at_end"] != ""]),
            str(sum(int(r["wrong_ip_actions"]) for r in rs)), pct(mism), pct(evid),
            pct([q["complete"] for q in rq]), pct([q["ips_ok"] for q in rq]), pct([q["cjk_leak"] for q in rq]),
        ]) + " |")

    out.append("\n## Matrices de confusión (subtipo real -> predicho)\n")
    for cond in sorted({r["condition"] for r in rows}):
        c = Counter((r["subtype_true"], r["pred_subtype"] or "(sin dato)") for r in rows if r["condition"] == cond)
        trues = sorted({t for t, _ in c})
        preds = sorted({p for _, p in c})
        out.append(f"**{cond}**\n\n| real \\ predicho | " + " | ".join(preds) + " |\n|---|" + "---|" * len(preds))
        for t in trues:
            out.append(f"| {t} | " + " | ".join(str(c.get((t, p), 0)) for p in preds) + " |")
        out.append("")

    mis = []
    for r in rows:
        run = runs.get(r["run_id"])
        if run and actions_mismatch(run):
            cl = (run["chain"].get("mitigation") or {}).get("actions") or []
            cl = sorted(str(_key(a)) for a in cl if isinstance(a, dict) and _key(a)[0] in MUTATING)
            ac = sorted(str(_key(a)) for a in run["actions"] if _key(a)[0] in MUTATING)
            mis.append(f"- {r['run_id']}: declaró {cl or 'ninguna'}; ejecutó {ac or 'ninguna'}")
    if mis:
        out.append("## Discrepancias entre acciones declaradas y ejecutadas\n")
        out += mis
        out.append("")

    fp = [r for r in rows if r["scenario"] == "normal"]
    if fp:
        out.append("## Falsos positivos (escenario normal)\n")
        for cond in sorted({r["condition"] for r in fp}):
            rs = [r for r in fp if r["condition"] == cond]
            bad = [r["pred_class"] != "healthy" or int(r["unneeded_actions"]) > 0 for r in rs]
            out.append(f"- {cond}: {sum(bad)}/{len(rs)} corridas con falsa alarma o acción innecesaria")
    text = "\n".join(out)
    (d / "resumen.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/raw/piloto")
