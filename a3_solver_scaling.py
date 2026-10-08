#!/usr/bin/env python3
"""
R2 experiment A3 -- solver-layer scaling of the RECOIL intermodal MIP.

Drives the production solver class `Intermodal` (RECOIL_Backend_MotionIntel_AI,
lib/intermodal_base_lib.py) directly, without HTTP, on the 20-node
`intermodal-20` network. The backend code is used read-only; Gurobi parameters
(TimeLimit, Threads, quiet output) are injected by wrapping `Model.optimize`.

Experiments
  ref    : reference Seattle WA -> Orlando FL instance (200 containers, T=48 h),
           repeated --reps times (solver-stage timing for A2).
  sample : the backend's bundled 3-order instance data/sample_instance.json
           (Seattle->Orlando, Houston->New York, Los Angeles->Chicago),
           repeated --reps times.
  uc2    : the manuscript's Use Case 2 request (250 containers, Seattle WA ->
           Orlando FL, 36 h), to reproduce the quoted solution ($75,668.53).
  orders : number of orders n in N_ORDERS, random distinct O-D pairs among the
           6 highway (warehouse) nodes, --seeds instances per n.
  fleet  : fleet size L_max = B_max in FLEET at n in FLEET_N orders.

Output: one JSON line per solve appended to --out (resumable: finished
(exp, key, seed, rep) records are skipped on re-run).

--backend gurobi (default) uses gurobipy. --backend highs|scip|cbc runs the same,
unmodified formulation on Google OR-Tools through the gurobipy-compatible
facade mcp_server/grb_ortools.py (backend branch feat/mcp), so it needs the
recoil-mcp-optimizer image and the feat/mcp worktree mounted at /app.

Must run with the backend repo as the working directory (the solver reads
data/ relatively); see run_a3.sh.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(os.environ.get("BACKEND_DIR", "/app"))
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import lib.intermodal_base_lib as ib  # noqa: E402
from lib.config import OPTIMIZATION_PARAMS  # noqa: E402
from lib.intermodal_base_lib import Intermodal  # noqa: E402

grb = ib.grb  # replaced by the OR-Tools facade for non-Gurobi backends in main()

WAREHOUSES = ["New York NY", "Orlando FL", "Houston TX",
              "Los Angeles CA", "Chicago IL", "Seattle WA"]
OD_PAIRS = [(o, d) for o in WAREHOUSES for d in WAREHOUSES if o != d]  # 30

REF_ORDER = {"i": 1, "o": "Seattle WA", "d": "Orlando FL", "T": 48, "v": 200, "w": 2800}

N_ORDERS = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30]
FLEET = [1, 2, 3, 4, 5, 6]
FLEET_N = [5, 10]

# Gurobi settings injected into every solve (recorded in each output line)
GRB_SETTINGS: dict = {}


def _patch_optimize():
    orig = ib.grb.Model.optimize

    def optimize(self, *args, **kwargs):
        for k, v in GRB_SETTINGS.items():
            self.setParam(k, v)
        return orig(self, *args, **kwargs)

    ib.grb.Model.optimize = optimize


def random_orders(n: int, seed: int) -> list[dict]:
    """n orders on distinct O-D pairs; volume 50-300 containers, deadline 36-72 h."""
    rng = random.Random(seed)
    pairs = rng.sample(OD_PAIRS, n)
    orders = []
    for i, (o, d) in enumerate(pairs, start=1):
        v = rng.randint(50, 300)
        orders.append({"i": i, "o": o, "d": d, "T": rng.choice([36, 48, 60, 72]),
                       "v": v, "w": round(v * 14.0, 1)})  # 14 t/container, as in sample
    return orders


def _bind_backend(backend: str, settings: dict) -> None:
    """Select the solver backend and inject the run settings (also used as the
    process-pool initializer for --workers > 1)."""
    if backend != "gurobi":
        from mcp_server import grb_ortools
        ib.grb = grb_ortools.for_backend(backend.upper())
    GRB_SETTINGS.clear()
    GRB_SETTINGS.update(settings)
    _patch_optimize()


def _solve_job(j: dict) -> dict:
    params = dict(OPTIMIZATION_PARAMS, L_max=j["fleet"], B_max=j["fleet"])
    try:
        return solve_once(j["orders"], params)
    except Exception as e:  # record failures instead of aborting the sweep
        return {"error": repr(e)}


def solve_once(orders: list[dict], params: dict) -> dict:
    t0 = time.perf_counter()
    im = Intermodal("a3", copy.deepcopy(orders), params)
    t1 = time.perf_counter()
    im.solve()
    t2 = time.perf_counter()
    m = im.model
    rec = {
        "init_s": t1 - t0,
        "solve_call_s": t2 - t1,           # model build + optimize + route extraction
        "grb_runtime_s": m.Runtime,         # Gurobi optimize() only
        "status": m.Status,
        "sol_count": m.SolCount,
        "obj": m.ObjVal if m.SolCount else None,
        "obj_bound": m.ObjBound if m.SolCount else None,
        "mip_gap": m.MIPGap if m.SolCount else None,
        "node_count": m.NodeCount,
        "n_vars": m.NumVars,
        "n_bin_vars": m.NumBinVars,
        "n_int_vars": m.NumIntVars,
        "n_constrs": m.NumConstrs,
        "n_nonzeros": m.NumNZs,
    }
    if getattr(m, "extra_stats", None):          # heuristic search statistics
        rec["heuristic"] = m.extra_stats
    m.dispose()
    return rec


def build_jobs(args) -> list[dict]:
    jobs = []
    if "ref" in args.exp:
        for r in range(args.reps):
            jobs.append({"exp": "ref", "key": "seattle_orlando", "seed": 0, "rep": r,
                         "orders": [REF_ORDER], "fleet": OPTIMIZATION_PARAMS["L_max"]})
    if "sample" in args.exp:
        sample = json.loads((BACKEND / "data" / "sample_instance.json").read_text())
        for r in range(args.reps):
            jobs.append({"exp": "sample", "key": "sample_instance", "seed": 0, "rep": r,
                         "orders": sample, "fleet": OPTIMIZATION_PARAMS["L_max"]})
    if "uc2" in args.exp:
        for r in range(args.reps):
            jobs.append({"exp": "uc2", "key": "use_case_2", "seed": 0, "rep": r,
                         "orders": [dict(REF_ORDER, T=36, v=250, w=3500)],
                         "fleet": OPTIMIZATION_PARAMS["L_max"]})
    if "orders" in args.exp:
        for n in N_ORDERS:
            for s in range(args.seeds):
                jobs.append({"exp": "orders", "key": f"n={n}", "seed": s, "rep": 0,
                             "orders": random_orders(n, 1000 * n + s),
                             "fleet": OPTIMIZATION_PARAMS["L_max"]})
    if "fleet" in args.exp:
        for n in FLEET_N:
            for f in FLEET:
                for s in range(args.seeds):
                    jobs.append({"exp": "fleet", "key": f"n={n},fleet={f}", "seed": s,
                                 "rep": 0, "orders": random_orders(n, 1000 * n + s),
                                 "fleet": f})
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", nargs="+", default=["ref", "sample", "orders", "fleet"],
                    choices=["ref", "sample", "uc2", "orders", "fleet"])
    ap.add_argument("--reps", type=int, default=20, help="repetitions for ref and sample")
    ap.add_argument("--seeds", type=int, default=3, help="instances per size")
    ap.add_argument("--time-limit", type=float, default=600)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--warmup", type=int, default=1, help="untimed solves first")
    ap.add_argument("--backend", default="gurobi", choices=["gurobi", "highs", "scip", "cbc", "routes"])
    ap.add_argument("--route-workers", type=int, default=32,
                    help="parallel evaluations for the route-first heuristic (--backend routes)")
    ap.add_argument("--workers", type=int, default=1,
                    help="instances solved in parallel (OR-Tools backends only; Gurobi is license-limited)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.workers > 1 and args.backend == "gurobi":
        ap.error("--workers > 1 is not allowed with Gurobi (concurrent license sessions are limited)")
    settings = {"TimeLimit": args.time_limit, "Threads": args.threads, "OutputFlag": 0}
    if args.backend == "routes":
        settings["RouteWorkers"] = args.route_workers
    _bind_backend(args.backend, settings)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["exp"], r["key"], r["seed"], r["rep"]))

    if args.backend == "gurobi":
        solver_version = ".".join(map(str, ib.grb.gurobi.version()))
    else:
        import ortools
        solver_version = f"ortools {ortools.__version__}"
    env = {"host": platform.node(), "python": platform.python_version(),
           "backend": args.backend, "solver_version": solver_version,
           "gurobi": solver_version if args.backend == "gurobi" else None,
           "cpu_count": os.cpu_count(), "grb_settings": dict(GRB_SETTINGS),
           "parallel_workers": args.workers}
    print(json.dumps(env), flush=True)

    for _ in range(args.warmup):
        solve_once([REF_ORDER], dict(OPTIMIZATION_PARAMS))

    jobs = [j for j in build_jobs(args)
            if (j["exp"], j["key"], j["seed"], j["rep"]) not in done]
    print(f"{len(jobs)} solves to run ({len(done)} already done)", flush=True)
    if args.workers > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        pool = ProcessPoolExecutor(max_workers=args.workers, initializer=_bind_backend,
                                   initargs=(args.backend, settings))
        futs = {pool.submit(_solve_job, j): j for j in jobs}
        results = ((futs[f], f.result()) for f in as_completed(futs))
    else:
        results = ((j, _solve_job(j)) for j in jobs)
    for k, (j, res) in enumerate(results, 1):
        rec = {"exp": j["exp"], "key": j["key"], "seed": j["seed"], "rep": j["rep"],
               "n_orders": len(j["orders"]), "fleet": j["fleet"],
               "total_containers": sum(o["v"] for o in j["orders"]),
               "orders": j["orders"], **res, **env,
               "timestamp": datetime.now(timezone.utc).isoformat()}
        with out.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{k}/{len(jobs)}] {j['exp']} {j['key']} s{j['seed']} r{j['rep']}: "
              f"status={res.get('status')} t={res.get('grb_runtime_s', float('nan')):.2f}s "
              f"gap={res.get('mip_gap')}", flush=True)


if __name__ == "__main__":
    main()
