#!/usr/bin/env python3
"""
Figure for Section 4.3: scaling of the optimization layer with instance size,
for the same formulation solved by Gurobi and three OR-Tools backends.

(a) Median solver time per number of orders (log scale). A series ends at the
    first size where its median reaches the 600 s time limit; beyond that its
    behavior is shown in (b). Filled marker: every instance of that size solved
    to optimality; hollow marker: at least one instance stopped at the limit.
    Markers that coincide at the limit are offset horizontally by a small dodge.
(b) Median remaining optimality gap at termination (0 when solved to
    optimality). Sizes where the solver found no feasible solution within the
    limit in a majority of instances are drawn as "x" in a separate row above
    100%.

Each series has its own marker shape and a legend entry, so identity never
depends on color alone. Palette validated with the dataviz validator (light
mode: all checks pass; aqua and yellow are below 3:1 contrast, relieved by the
legend and marker shapes).

Writes results/fig_a3_scaling.pdf and .png (300 dpi).
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

RES = Path(__file__).parent / "results"
SERIES = [  # fixed categorical order (validated palette, light mode)
    ("gurobi", "a3_solver_scaling.jsonl", "Gurobi", "#2a78d6", "o"),
    ("highs", "a3_solver_scaling_highs.jsonl", "HiGHS", "#eb6834", "s"),
    ("scip", "a3_solver_scaling_scip.jsonl", "SCIP", "#1baf7a", "^"),
    ("cbc", "a3_solver_scaling_cbc.jsonl", "CBC", "#eda100", "D"),
]
DODGE = {"gurobi": -0.45, "highs": -0.15, "scip": 0.15, "cbc": 0.45}
TIME_LIMIT = 600
NO_SOL_Y = 112          # row (in %) for "no feasible solution"
INK, INK2, GRID = "#1f1f1e", "#5f5e5a", "#e4e3dd"
SIZES = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30]


def load(fname):
    p = RES / fname
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def by_size(recs):
    d = defaultdict(list)
    for r in recs:
        if r.get("exp") == "orders" and "grb_runtime_s" in r:
            d[r["n_orders"]].append(r)
    return d


def main():
    plt.rcParams.update({"font.family": "STIXGeneral", "mathtext.fontset": "stix", "font.size": 9,
                         "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                         "ytick.color": INK2, "axes.linewidth": 0.6})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.3))

    for key, fname, label, color, marker in SERIES:
        d = by_size(load(fname))
        if not d:
            continue
        ns = sorted(d)
        # (a) median time, truncated at the first size whose median is at the limit
        xs, ys, filled = [], [], []
        for n in ns:
            m = st.median(r["grb_runtime_s"] for r in d[n])
            capped = m >= TIME_LIMIT * 0.98
            xs.append(n + (DODGE[key] if capped else 0))
            ys.append(min(m, TIME_LIMIT))
            filled.append(all(r["status"] == 2 for r in d[n]))
            if capped:
                break
        ax1.plot(xs, ys, color=color, lw=2, zorder=3)
        for x, y, f in zip(xs, ys, filled):
            ax1.plot(x, y, marker=marker, ms=6, mew=1.3, color=color, mfc=color if f else "white", zorder=4)

        # (b) median remaining gap; majority without incumbent -> "no solution" row
        gx, gy, nx = [], [], []
        for n in ns:
            rs = d[n]
            no_inc = sum(r.get("status") == 9 and not r.get("sol_count") for r in rs)
            if no_inc * 2 > len(rs):
                nx.append(n + DODGE[key])
                continue
            gaps = [0.0 if r["status"] == 2 else 100 * r["mip_gap"] for r in rs if r.get("sol_count")]
            gx.append(n)
            gy.append(st.median(gaps))
        ax2.plot(gx, gy, color=color, lw=2, marker=marker, ms=5.5, mew=1.3, zorder=3, label=label)
        if nx:
            ax2.plot(nx, [NO_SOL_Y] * len(nx), ls="", marker="x", ms=6, mew=1.6, color=color, zorder=4)

    # panel (a) cosmetics
    ax1.axhline(TIME_LIMIT, color=INK2, lw=0.8, ls=(0, (4, 3)), zorder=1)
    ax1.text(30.5, TIME_LIMIT * 0.62, "600 s limit", color=INK2, fontsize=7.5, ha="right", va="top")
    ax1.set_yscale("log")
    ax1.set_ylim(0.02, 1500)
    ax1.set_ylabel("Median solver time (s, log scale)")
    ax1.set_title("(a) Time to optimality", fontsize=9, color=INK, loc="left")
    # panel (b) cosmetics
    ax2.axhline(100, color=GRID, lw=0.6)
    ax2.set_ylim(-4, 120)
    ax2.set_yticks([0, 20, 40, 60, 80, 100, NO_SOL_Y])
    ax2.set_yticklabels(["0", "20", "40", "60", "80", "100", "no sol."])
    ax2.set_ylabel("Median remaining gap at termination (%)")
    ax2.set_title("(b) Remaining optimality gap", fontsize=9, color=INK, loc="left")
    for ax in (ax1, ax2):
        ax.set_xticks(SIZES)
        ax.set_xlim(0, 31.5)
        ax.set_xlabel("Number of orders")
        ax.grid(axis="y", color=GRID, lw=0.6, zorder=0)
        ax.spines[["top", "right"]].set_visible(False)

    handles = [plt.Line2D([], [], color=c, lw=2, marker=mk, ms=5.5, label=lab) for _, _, lab, c, mk in SERIES]
    handles += [plt.Line2D([], [], ls="", marker="o", ms=5.5, color=INK2, label="all instances optimal"),
                plt.Line2D([], [], ls="", marker="o", ms=5.5, mfc="white", mec=INK2, mew=1.2,
                           label="time limit on $\\geq$1 instance"),
                plt.Line2D([], [], ls="", marker="x", ms=5.5, mew=1.5, color=INK2,
                           label="no feasible solution in time limit")]
    fig.legend(handles=handles, loc="lower center", ncol=4, fontsize=7.5, frameon=False,
               bbox_to_anchor=(0.5, -0.01), handlelength=1.8, columnspacing=1.4)
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    for ext in ("pdf", "png"):
        fig.savefig(RES / f"fig_a3_scaling.{ext}", dpi=300)
    print("wrote", RES / "fig_a3_scaling.pdf")


if __name__ == "__main__":
    main()
