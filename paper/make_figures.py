#!/usr/bin/env python3
"""Genera las figuras del articulo a partir del summary.csv del ejecutor.

Uso:
    pip install matplotlib
    python paper/make_figures.py results/raw/piloto/summary.csv

Salidas (vectoriales, ancho de una columna IEEE):
    fig/desenlace.pdf        Fig. 2: desenlace de cada corrida por escenario y condicion
    fig/mttr_breakdown.pdf   Fig. 3: tiempo hasta la primera accion y recuperacion
"""
import csv
import os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ETIQ = {"fault": "Falla", "ddos": "DDoS", "bruteforce": "F. bruta", "normal": "Normal"}
ORDEN_DESENLACE = ["fault", "ddos", "bruteforce", "normal"]
ORDEN_MTTR = ["fault", "ddos", "bruteforce"]
COND = [("single", "Agente único", ""), ("multi", "Multiagente", "///")]


def leer(paths):
    filas = []
    for p in paths:
        with open(p, newline="", encoding="utf-8") as fh:
            filas.extend(r for r in csv.DictReader(fh) if r.get("run_id"))
    return filas


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def bl(v):
    return str(v).strip().lower() == "true"


def fig_desenlace(filas):
    """Composicion del desenlace: correcta / respondio y erro / sin respuesta."""
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    ancho = 0.36
    for ci, (cond, lab, hatch) in enumerate(COND):
        pos, ok, mal, sin = [], [], [], []
        for i, esc in enumerate(ORDEN_DESENLACE):
            s = [r for r in filas if r["scenario"] == esc and r["condition"] == cond]
            n_ok = sum(bl(r["class_ok"]) for r in s)
            n_par = sum(bl(r["detection_parsed"]) for r in s)
            pos.append(i + (ci - 0.5) * ancho)
            ok.append(n_ok)
            mal.append(n_par - n_ok)
            sin.append(len(s) - n_par)
        base = [0] * len(pos)
        ax.bar(pos, ok, ancho, color="#4C72B0", edgecolor="black", linewidth=0.5,
               hatch=hatch, label=lab if ci == 0 else lab)
        ax.bar(pos, mal, ancho, bottom=ok, color="#BBBBBB", edgecolor="black",
               linewidth=0.5, hatch=hatch)
        base = [a + b for a, b in zip(ok, mal)]
        ax.bar(pos, sin, ancho, bottom=base, color="white", edgecolor="black",
               linewidth=0.5, hatch=hatch)

    ax.set_xticks(range(len(ORDEN_DESENLACE)))
    ax.set_xticklabels([ETIQ[e] for e in ORDEN_DESENLACE])
    ax.set_ylabel("Corridas (de 5)")
    ax.set_xlabel("Escenario inyectado")
    ax.set_ylim(0, 6.4)
    ax.set_yticks(range(0, 6))
    ax.yaxis.grid(True, linewidth=0.4, alpha=0.5)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)

    leyenda = [
        plt.Rectangle((0, 0), 1, 1, facecolor="#4C72B0", edgecolor="black", linewidth=0.5),
        plt.Rectangle((0, 0), 1, 1, facecolor="#BBBBBB", edgecolor="black", linewidth=0.5),
        plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="black", linewidth=0.5),
        plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="black", linewidth=0.5,
                      hatch="///"),
    ]
    ax.legend(leyenda,
              ["Clasificación correcta", "Respondió y erró", "Sin respuesta",
               "Trama: multiagente"],
              fontsize=5.4, frameon=False, loc="upper center", ncol=2,
              handlelength=1.3, borderpad=0.1, labelspacing=0.25, columnspacing=0.8)
    fig.tight_layout(pad=0.3)
    guardar(fig, "desenlace")


def fig_mttr(filas):
    """Tiempo hasta la primera accion y recuperacion posterior (media por celda)."""
    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    ancho = 0.36
    for ci, (cond, lab, hatch) in enumerate(COND):
        pos, p_first, p_rec = [], [], []
        for i, esc in enumerate(ORDEN_MTTR):
            s = [r for r in filas if r["scenario"] == esc and r["condition"] == cond]
            par = [(num(r["t_first_action_s"]), num(r["mttr_s"])) for r in s]
            par = [(a, m) for a, m in par if a is not None and m is not None]
            pos.append(i + (ci - 0.5) * ancho)
            if par:
                a = sum(x for x, _ in par) / len(par)
                m = sum(y for _, y in par) / len(par)
                p_first.append(a)
                p_rec.append(max(m - a, 0.0))
                ax.text(pos[-1], m + 4, f"n={len(par)}", ha="center", fontsize=5.2,
                        color="#444444")
            else:
                p_first.append(0.0)
                p_rec.append(0.0)
        ax.bar(pos, p_first, ancho, color="#4C72B0", edgecolor="black", linewidth=0.5,
               hatch=hatch, label=lab)
        ax.bar(pos, p_rec, ancho, bottom=p_first, color="white", edgecolor="black",
               linewidth=0.5, hatch=hatch)

    ax.set_xticks(range(len(ORDEN_MTTR)))
    ax.set_xticklabels([ETIQ[e] for e in ORDEN_MTTR])
    ax.set_ylabel("Tiempo desde la inyección (s)")
    ax.set_xlabel("Escenario inyectado")
    ax.set_ylim(0, 175)
    ax.yaxis.grid(True, linewidth=0.4, alpha=0.5)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    h, l = ax.get_legend_handles_labels()
    extra = plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="black", linewidth=0.5)
    ax.legend(h + [extra], l + ["Recuperación tras la acción"], fontsize=5.6,
              frameon=False, loc="upper left", handlelength=1.3, borderpad=0.15,
              labelspacing=0.3)
    fig.tight_layout(pad=0.3)
    guardar(fig, "mttr_breakdown")


def guardar(fig, nombre):
    os.makedirs("fig", exist_ok=True)
    fig.savefig(f"fig/{nombre}.pdf", bbox_inches="tight")
    fig.savefig(f"fig/{nombre}.png", dpi=600, bbox_inches="tight")
    print(f"escrito fig/{nombre}.pdf")


if __name__ == "__main__":
    plt.rcParams.update({
        "font.size": 7, "axes.labelsize": 7.5, "xtick.labelsize": 6.8,
        "ytick.labelsize": 6.8, "font.family": "serif",
        "font.serif": ["DejaVu Serif"], "pdf.fonttype": 42,
    })
    paths = sys.argv[1:] or ["/mnt/user-data/uploads/0993a181-summary.csv"]
    filas = leer(paths)
    fig_desenlace(filas)
    fig_mttr(filas)
