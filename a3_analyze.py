#!/usr/bin/env python3
"""
Analyze A3 solver scaling across backends.

Inputs (results/): a3_solver_scaling.jsonl (Gurobi), a3_solver_scaling_{highs,
scip,cbc}.jsonl (OR-Tools). Instances are identical across backends (same
seeds, same unmodified formulation).

Per backend and experiment group it reports: number of instances, number
solved to optimality (status 2, within the 1e-4 relative gap), number stopped
at the 600 s limit (status 9), median and max solver runtime, and the median
remaining gap of time-limited instances, and how many time-limited instances
ended without any feasible solution (no incumbent). It also checks that objectives agree
across backends where both report optimality (relative difference <= 1e-4).

Writes results/a3_summary.json and results/tab_a3_scaling.tex.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

RES = Path(__file__).parent / "results"
BACKENDS = {"gurobi": "a3_solver_scaling.jsonl", "highs": "a3_solver_scaling_highs.jsonl",
            "scip": "a3_solver_scaling_scip.jsonl", "cbc": "a3_solver_scaling_cbc.jsonl"}
HEURISTIC = "a3_solver_scaling_routes.jsonl"
LABEL = {"gurobi": "Gurobi", "highs": "HiGHS", "scip": "SCIP", "cbc": "CBC", "routes": "Route heuristic"}


def load(fname):
    p = RES / fname
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def group_key(r):
    if r["exp"] == "orders":
        return f"orders n={r['n_orders']}"
    if r["exp"] == "fleet":
        return f"fleet n={r['n_orders']} f={r['fleet']}"
    return r["exp"]


def summarize(recs):
    t = [r["grb_runtime_s"] for r in recs if "grb_runtime_s" in r]
    opt = [r for r in recs if r.get("status") == 2]
    tl = [r for r in recs if r.get("status") == 9]
    no_inc = [r for r in tl if not r.get("sol_count")]
    gaps = [r["mip_gap"] for r in tl if r.get("mip_gap") is not None]
    return {"n": len(recs), "optimal": len(opt), "time_limit": len(tl),
            "no_incumbent": len(no_inc), "other": len(recs) - len(opt) - len(tl),
            "median_s": st.median(t) if t else None, "max_s": max(t) if t else None,
            "median_gap_tl": st.median(gaps) if gaps else None,
            "n_bin_vars": st.median([r["n_bin_vars"] for r in recs]) if recs else None}


def main():
    data = {b: load(f) for b, f in BACKENDS.items()}
    summary = defaultdict(dict)
    for b, recs in data.items():
        groups = defaultdict(list)
        for r in recs:
            if "error" not in r:
                groups[group_key(r)].append(r)
        for g, rs in groups.items():
            summary[g][b] = summarize(rs)

    # objective agreement where both backends are optimal
    agree = defaultdict(lambda: [0, 0])
    idx = {b: {(r["exp"], r["key"], r["seed"], r["rep"]): r for r in recs} for b, recs in data.items()}
    for b in ("highs", "scip", "cbc"):
        for k, r in idx[b].items():
            g = idx["gurobi"].get(k)
            if g and g.get("status") == 2 and r.get("status") == 2:
                rel = abs(r["obj"] - g["obj"]) / max(abs(g["obj"]), 1e-9)
                agree[b][0] += rel <= 1e-4 + 1e-9
                agree[b][1] += 1
    out = {"groups": summary, "objective_agreement_with_gurobi": {b: {"agree": a, "compared": n}
                                                                 for b, (a, n) in agree.items()}}

    # route heuristic: gap to the best plan found by any exact solver (and to Gurobi's bound)
    heur = load(HEURISTIC)
    best_ub, best_lb = {}, {}
    for b, recs in data.items():
        for r in recs:
            k = (r["exp"], r["key"], r["seed"])
            if r.get("obj") is not None:
                best_ub[k] = min(best_ub.get(k, float("inf")), r["obj"])
            if b == "gurobi" and r.get("obj_bound") is not None:
                best_lb[k] = max(best_lb.get(k, float("-inf")), r["obj_bound"])
    hg = defaultdict(list)
    for r in heur:
        k = (r["exp"], r["key"], r["seed"])
        if "error" in r or k not in best_ub:
            continue
        hg[group_key(r)].append({"gap_to_best_pct": 100 * (r["obj"] - best_ub[k]) / best_ub[k],
                                 "gap_to_bound_pct": 100 * (r["obj"] - best_lb[k]) / r["obj"] if k in best_lb else None,
                                 "time_s": r["grb_runtime_s"]})
    out["route_heuristic"] = {g: {"n": len(v),
                                  "median_gap_to_best_pct": st.median(x["gap_to_best_pct"] for x in v),
                                  "max_gap_to_best_pct": max(x["gap_to_best_pct"] for x in v),
                                  "median_gap_to_bound_pct": st.median(x["gap_to_bound_pct"] for x in v if x["gap_to_bound_pct"] is not None),
                                  "median_time_s": st.median(x["time_s"] for x in v),
                                  "max_time_s": max(x["time_s"] for x in v)} for g, v in hg.items()}
    (RES / "a3_summary.json").write_text(json.dumps(out, indent=1))

    # LaTeX table: order scaling, median runtime and solved/total per backend
    sizes = sorted({int(g.split("=")[1]) for g in summary if g.startswith("orders")})
    bks = [b for b in BACKENDS if data[b]]
    cols = "".join("rr" for _ in bks)
    lines = [rf"\begin{{tabular}}{{@{{}}rr{cols}@{{}}}}", r"\toprule",
             r"Orders & Binary vars & " + " & ".join(rf"\multicolumn{{2}}{{c}}{{{LABEL[b]}}}" for b in bks) + r" \\",
             " & & " + " & ".join(r"Median (s) & Opt." for _ in bks) + r" \\", r"\midrule"]
    for n in sizes:
        g = summary[f"orders n={n}"]
        nb = next((g[b]["n_bin_vars"] for b in bks if b in g), None)
        cells = []
        for b in bks:
            s = g.get(b)
            if not s:
                cells += ["--", "--"]
                continue
            med = f"{s['median_s']:.2f}" if s["median_s"] < 10 else f"{s['median_s']:.0f}"
            cells += [med, f"{s['optimal']}/{s['n']}"]
        lines.append(f"{n} & {int(nb):,} & " + " & ".join(cells) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (RES / "tab_a3_scaling.tex").write_text("\n".join(lines) + "\n")

    for g in sorted(summary, key=lambda x: (x.split()[0], int(x.split("=")[1].split()[0]) if "=" in x else 0)):
        row = " | ".join(f"{b}: {s['optimal']}/{s['n']} opt, med {s['median_s']:.2f}s, max {s['max_s']:.0f}s"
                         + (f", gap {s['median_gap_tl']:.3f}" if s['median_gap_tl'] is not None else "")
                         + (f", NO SOLUTION {s['no_incumbent']}" if s['no_incumbent'] else "")
                         for b, s in summary[g].items())
        print(f"{g:18s} {row}")
    print("objective agreement:", out["objective_agreement_with_gurobi"])
    for g, h in sorted(out["route_heuristic"].items(), key=lambda kv: (kv[0].split()[0], int(kv[0].split("=")[1]) if "=" in kv[0] else 0)):
        print(f"heuristic {g:14s} n={h['n']} gap to best plan: median {h['median_gap_to_best_pct']:+.1f}% "
              f"max {h['max_gap_to_best_pct']:+.1f}% | to Gurobi bound {h['median_gap_to_bound_pct']:.1f}% "
              f"| time median {h['median_time_s']:.0f}s max {h['max_time_s']:.0f}s")


if __name__ == "__main__":
    main()
