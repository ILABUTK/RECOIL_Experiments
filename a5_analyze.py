#!/usr/bin/env python3
"""
Analyze A5 (concurrency) results.

Solver and license records come from results/a5_concurrency.jsonl. Agent records come
from the rerun on the dedicated local Ollama server (run_a5_v2_agent.sh), one file per
number of parallel slots: results/a5_v2_agent_local_par{1,4}.jsonl. The agent records in
a5_concurrency.jsonl (shared LLM server) are superseded and not used.

license : number of concurrent Gurobi sessions opened successfully per k.
solver  : per solver, pool size and concurrency C: median and p95 client
          latency, median server-side queue wait and solve time, throughput.
          The pool size is taken from the server-reported timing.
agent   : per model, parallel slots and concurrency C: median and p95 end-to-end
          latency, throughput, errors, and task completion.
Writes results/a5_summary.json and results/tab_a5_concurrency.tex.
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

RES = Path(__file__).parent / "results"
AGENT_SLOTS = (1, 4)  # OLLAMA_NUM_PARALLEL of the dedicated server


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def main():
    recs = [json.loads(l) for l in (RES / "a5_concurrency.jsonl").read_text().splitlines() if l.strip()]
    out = {"license": {}, "solver": defaultdict(dict), "agent": defaultdict(dict)}
    for r in recs:
        if r["exp"] == "license":
            out["license"][r["k"]] = max(out["license"].get(r["k"], 0), r["n_ok"])
        elif r["exp"] == "solver":
            reqs = [q for q in r["requests"] if not q.get("is_error") and not q.get("error")]
            pool = st.mode([q.get("pool_size") for q in reqs]) if reqs else None
            key = f"{r['solver']} pool {pool}"
            out["solver"][key][r["concurrency"]] = {
                "n": len(r["requests"]), "errors": len(r["requests"]) - len(reqs),
                "p50_s": st.median(q["latency_s"] for q in reqs),
                "p95_s": pct([q["latency_s"] for q in reqs], 0.95),
                "queue_wait_p50_s": st.median(q.get("queue_wait_s", 0) for q in reqs),
                "solve_p50_s": st.median(q.get("build_and_solve_s", 0) for q in reqs),
                "throughput_per_s": r["throughput_rps"]}
    for slots in AGENT_SLOTS:
        for r in (json.loads(l) for l in (RES / f"a5_v2_agent_local_par{slots}.jsonl").read_text().splitlines() if l.strip()):
            if r["exp"] != "agent":
                continue
            runs = r["runs"]
            lat = [t["client_latency_s"] for t in runs if "error" not in t]
            out["agent"][f"{r['model']} par {slots}"][r["concurrency"]] = {
                    "n": len(runs), "errors": sum("error" in t for t in runs),
                    "completed": sum(bool(t.get("completed")) for t in runs),
                    "p50_s": st.median(lat) if lat else None, "p95_s": pct(lat, 0.95),
                    "throughput_per_min": 60 * len(runs) / r["makespan_s"]}
    (RES / "a5_summary.json").write_text(json.dumps(out, indent=1, default=dict))

    print("license:", out["license"])
    for key, rows in out["solver"].items():
        for c, s in sorted(rows.items()):
            print(f"solver {key:16s} C={c:>2}: p50 {s['p50_s']:6.2f}s p95 {s['p95_s']:6.2f}s "
                  f"wait {s['queue_wait_p50_s']:6.2f}s solve {s['solve_p50_s']:5.2f}s "
                  f"thr {s['throughput_per_s']:.2f}/s err {s['errors']}")
    for m, rows in out["agent"].items():
        for c, s in sorted(rows.items()):
            print(f"agent {m:18s} C={c:>2}: p50 {s['p50_s']:6.1f}s p95 {s['p95_s']:6.1f}s "
                  f"thr {s['throughput_per_min']:.1f}/min completed {s['completed']}/{s['n']} err {s['errors']}")

    # LaTeX: solver-only throughput/latency and agent latency by concurrency
    levels = sorted({c for rows in out["solver"].values() for c in rows})
    lines = [r"\begin{tabular}{@{}l" + "r" * len(levels) + "@{}}", r"\toprule",
             "Concurrent clients & " + " & ".join(map(str, levels)) + r" \\", r"\midrule",
             r"\multicolumn{" + str(len(levels) + 1) + r"}{@{}l}{\textit{Solver only: median latency (s) / throughput (solves/s)}} \\"]
    def order(key):
        solver, _, pool = key.split()
        return (solver != "gurobi", int(pool))
    for key in sorted(out["solver"], key=order):
        rows = out["solver"][key]
        solver, _, pool = key.split()
        lab = f"Gurobi, {pool} sessions" if solver == "gurobi" else f"HiGHS, {pool} processes"
        lines.append(lab + " & " + " & ".join(
            f"{rows[c]['p50_s']:.1f} / {rows[c]['throughput_per_s']:.1f}" if c in rows else "--" for c in levels) + r" \\")
    lines += [r"\midrule", r"\multicolumn{" + str(len(levels) + 1) + r"}{@{}l}{\textit{Complete agent requests (dedicated LLM server): "
              r"median end-to-end latency (s) / throughput (requests/min)}} \\"]
    for key in sorted(out["agent"], key=lambda k: (not k.startswith("llama"), int(k.split()[-1]))):
        rows = out["agent"][key]
        model, slots = key.split()[0], int(key.split()[-1])
        lab = r"\texttt{" + model + "}, " + (f"{slots} parallel slot" if slots == 1 else f"{slots} parallel slots")
        lines.append(lab + " & " + " & ".join(
            f"{rows[c]['p50_s']:.1f} / {rows[c]['throughput_per_min']:.1f}" if c in rows else "--" for c in levels) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (RES / "tab_a5_concurrency.tex").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
