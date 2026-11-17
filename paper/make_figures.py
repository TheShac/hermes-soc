#!/usr/bin/env python3
"""Genera la Fig. 1 del articulo a partir de los summary.csv del ejecutor.

Uso:
    python make_figures.py results/raw/humo/summary.csv results/raw/prueba2/summary.csv

Salida: fig/mttr_breakdown.pdf (vectorial, ancho de una columna IEEE).
"""
import csv
import sys
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ETIQUETAS = {"fault": "Falla (latencia)", "ddos": "DDoS", "bruteforce": "Fuerza bruta"}
ORDEN = ["fault", "ddos", "bruteforce"]


def leer(paths):
    filas = []
    for p in paths:
        with open(p, newline="", encoding="utf-8") as fh:
            filas.extend(csv.DictReader(fh))
    return filas


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def agregar(filas):
    """Promedia por (escenario, condicion) las corridas que si mitigaron."""
    acc = {}
    for f in filas:
        esc, cond = f["scenario"], f["condition"]
        if esc not in ORDEN:
            continue
        acc.setdefault((esc, cond), {"first": [], "mttr": [], "n": 0, "mitigo": 0})
        a = acc[(esc, cond)]
        a["n"] += 1
        fa, mt = num(f.get("t_first_action_s")), num(f.get("mttr_s"))
        if fa is not None and mt is not None:
            a["first"].append(fa)
            a["mttr"].append(mt)
            a["mitigo"] += 1
    return acc


def main(paths):
    acc = agregar(leer(paths))

    fig, ax = plt.subplots(figsize=(3.5, 2.35))
    ancho, x = 0.36, range(len(ORDEN))
    # Relleno y trama distintos por serie: la figura debe seguir siendo
    # legible en escala de grises (impresion en blanco y negro).
    estilos = {
        "single": dict(off=-ancho / 2, color="#4C72B0", hatch="", label="Agente único"),
        "multi": dict(off=ancho / 2, color="#DD8452", hatch="///", label="Multiagente"),
    }

    for cond, st in estilos.items():
        p_first, p_rec, pos = [], [], []
        for i, esc in enumerate(ORDEN):
            a = acc.get((esc, cond))
            pos.append(i + st["off"])
            if a and a["mitigo"]:
                f = sum(a["first"]) / len(a["first"])
                m = sum(a["mttr"]) / len(a["mttr"])
                p_first.append(f)
                p_rec.append(max(m - f, 0.0))
            else:
                p_first.append(0.0)
                p_rec.append(0.0)
                ax.text(i + st["off"], 3, "sin\nmitigación", ha="center", va="bottom",
                        fontsize=5.5, rotation=90, color="#555555")
        ax.bar(pos, p_first, ancho, color=st["color"], label=st["label"],
               edgecolor="black", linewidth=0.5, hatch=st["hatch"])
        ax.bar(pos, p_rec, ancho, bottom=p_first, color="white",
               edgecolor="black", linewidth=0.5, hatch=st["hatch"])

    ax.set_xticks(list(x))
    ax.set_xticklabels([ETIQUETAS[e] for e in ORDEN])
    ax.set_ylabel("Tiempo desde la inyección (s)")
    ax.set_xlabel("Escenario inyectado")
    ax.set_ylim(0, 200)
    ax.set_xlim(-0.62, len(ORDEN) - 1 + 0.62)
    ax.yaxis.grid(True, linewidth=0.4, alpha=0.5)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)

    h, l = ax.get_legend_handles_labels()
    extra = plt.Rectangle((0, 0), 1, 1, facecolor="white",
                          edgecolor="black", linewidth=0.5)
    ax.legend(h + [extra], l + ["Recuperación tras la acción"],
              fontsize=5.8, frameon=False, loc="upper left", ncol=1,
              handlelength=1.4, borderpad=0.2, labelspacing=0.3)

    fig.tight_layout(pad=0.3)
    os.makedirs("fig", exist_ok=True)
    fig.savefig("fig/mttr_breakdown.pdf", bbox_inches="tight")
    fig.savefig("fig/mttr_breakdown.png", dpi=600, bbox_inches="tight")
    print("escrito fig/mttr_breakdown.pdf")


if __name__ == "__main__":
    plt.rcParams.update({
        "font.size": 7, "axes.labelsize": 7.5, "xtick.labelsize": 6.8,
        "ytick.labelsize": 6.8, "font.family": "serif",
        "font.serif": ["DejaVu Serif"], "pdf.fonttype": 42,
    })
    main(sys.argv[1:] or [
        "/mnt/user-data/uploads/hermes-soc/results/raw/humo/summary.csv",
        "/mnt/user-data/uploads/hermes-soc/results/raw/prueba2/summary.csv",
    ])
