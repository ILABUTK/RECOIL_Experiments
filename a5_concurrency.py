#!/usr/bin/env python3
"""
R2 experiment A5 -- behavior under concurrent requests.

license : opens k Gurobi environments simultaneously in k processes (k = 1..K)
          and holds them, recording which succeed; establishes how many
          concurrent solver sessions the WLS license permits.
solver  : C concurrent MCP clients (closed loop), each sending --per-client
          solve_intermodal requests with unique random 3-order instances, for C in
          LEVELS, against the Gurobi pool (license-limited) or the HiGHS pool
          (--solver). Records client latency and the server-reported queue wait
          and solve time of every request, and throughput per level.
agent   : C concurrent end-to-end agent runs (LLM on the Ollama server + MCP),
          each a single-order request with a unique volume, for C in AGENT_LEVELS.

Runs inside the recoil-mcp-optimizer image (see run_a5.sh). The MCP server must
not be shared with other experiments while 'solver' or 'agent' runs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")

CITIES = ["New York NY", "Orlando FL", "Houston TX", "Los Angeles CA", "Chicago IL", "Seattle WA"]
LEVELS = [1, 2, 4, 8, 16, 32]
AGENT_LEVELS = [1, 2, 4, 8, 16]


def now():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- license probe
def _hold_env(i: int, hold_s: float, q):
    import gurobipy as grb
    t0 = time.perf_counter()
    try:
        env = grb.Env(params={"OutputFlag": 0})
        m = grb.Model(env=env)
        x = m.addVar()
        m.setObjective(x)
        m.optimize()
        q.put({"proc": i, "ok": True, "start_s": time.perf_counter() - t0})
        time.sleep(hold_s)
        m.dispose()
        env.dispose()
    except Exception as e:  # license refusal surfaces here
        q.put({"proc": i, "ok": False, "start_s": time.perf_counter() - t0, "error": repr(e)})


def run_license(args, out):
    for k in range(1, args.max_sessions + 1):
        q = mp.Queue()
        procs = [mp.Process(target=_hold_env, args=(i, args.hold, q)) for i in range(k)]
        for p in procs:
            p.start()
        res = [q.get() for _ in procs]
        for p in procs:
            p.join()
        rec = {"exp": "license", "k": k, "n_ok": sum(r["ok"] for r in res), "procs": res,
               "timestamp": now()}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        print(f"license k={k}: {rec['n_ok']}/{k} sessions ok", flush=True)


# ---------------------------------------------------------------- solver load
def random_instance(rng: random.Random, n: int = 3):
    pairs = rng.sample([(o, d) for o in CITIES for d in CITIES if o != d], n)
    return [{"origin": o, "destination": d, "containers": rng.randint(50, 300),
             "deadline_hours": rng.choice([36, 48, 60, 72])} for o, d in pairs]


async def _solver_client(url, cid, n_req, seed, results, solver="gurobi"):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    rng = random.Random(seed)
    async with streamablehttp_client(url, timeout=600, sse_read_timeout=1200) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            for j in range(n_req):
                orders = random_instance(rng)
                t0 = time.perf_counter()
                res = await s.call_tool("solve_intermodal", {"orders": orders, "solver": solver})
                lat = time.perf_counter() - t0
                payload = res.structuredContent or {}
                if set(payload) == {"result"}:
                    payload = payload["result"]
                if not payload:
                    payload = json.loads(res.content[0].text)
                results.append({"client": cid, "req": j, "latency_s": lat, "t_end": time.perf_counter(),
                                "status": payload.get("status"), "error": payload.get("error"),
                                "is_error": bool(res.isError), **(payload.get("timing") or {}),
                                "n_bin_vars": (payload.get("model") or {}).get("n_bin_vars")})


async def run_solver(args, out):
    for c in args.levels:
        results = []
        t0 = time.perf_counter()
        await asyncio.gather(*[_solver_client(args.mcp, i, args.per_client, 10_000 * c + i, results,
                                              args.solver) for i in range(c)])
        makespan = time.perf_counter() - t0
        rec = {"exp": "solver", "solver": args.solver, "concurrency": c, "per_client": args.per_client,
               "n_requests": len(results), "makespan_s": makespan,
               "throughput_rps": len(results) / makespan, "requests": results, "timestamp": now()}
        out.write(json.dumps(rec) + "\n")
        out.flush()
        lats = sorted(r["latency_s"] for r in results)
        print(f"solver[{args.solver}] C={c}: n={len(results)} p50={lats[len(lats) // 2]:.2f}s "
              f"max={lats[-1]:.2f}s thr={rec['throughput_rps']:.2f}/s", flush=True)


# ---------------------------------------------------------------- agent load
async def run_agent_load(args, out):
    from agent.host import run_agent
    rng = random.Random(7)
    for _ in range(args.agent_warmup):   # load the model on the LLM server; not recorded
        try:
            await run_agent("I need to ship 200 containers from Seattle to Orlando within 48 hours. "
                            "What is the cheapest intermodal plan?", args.model, [args.mcp], num_ctx=8192)
        except Exception as e:
            print(f"warm-up failed: {e!r:.200}", flush=True)
    for c in args.agent_levels:
        prompts = [f"I need to ship {rng.randint(100, 300)} containers from Seattle to Orlando within "
                   f"48 hours. What is the cheapest intermodal plan?" for _ in range(c)]
        t0 = time.perf_counter()

        async def one(p):
            s = time.perf_counter()
            try:
                tr = await run_agent(p, args.model, [args.mcp], num_ctx=8192)
            except Exception as e:
                tr = {"error": repr(e), "completed": False}
            tr["client_latency_s"] = time.perf_counter() - s
            return tr

        traces = await asyncio.gather(*[one(p) for p in prompts])
        makespan = time.perf_counter() - t0
        rec = {"exp": "agent", "concurrency": c, "model": args.model, "makespan_s": makespan,
               "throughput_rps": c / makespan, "runs": traces, "timestamp": now()}
        out.write(json.dumps(rec, default=str) + "\n")
        out.flush()
        lats = sorted(t["client_latency_s"] for t in traces)
        print(f"agent C={c}: p50={lats[len(lats) // 2]:.2f}s max={lats[-1]:.2f}s "
              f"errors={sum('error' in t for t in traces)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", nargs="+", default=["solver"], choices=["license", "solver", "agent"])
    ap.add_argument("--max-sessions", type=int, default=6)
    ap.add_argument("--hold", type=float, default=15.0)
    ap.add_argument("--levels", type=int, nargs="+", default=LEVELS)
    ap.add_argument("--per-client", type=int, default=5)
    ap.add_argument("--agent-levels", type=int, nargs="+", default=AGENT_LEVELS)
    ap.add_argument("--agent-warmup", type=int, default=1)
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--solver", default="gurobi", choices=["gurobi", "highs"])
    ap.add_argument("--mcp", default="http://localhost:8200/mcp")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("a") as out:
        out.write(json.dumps({"exp": "env", "client_host": platform.node(), "args": vars(args), "ollama_base_url": os.getenv("OLLAMA_BASE_URL", "default (lib.config)"),
                              "timestamp": now()}) + "\n")
        if "license" in args.exp:
            run_license(args, out)
        if "solver" in args.exp:
            asyncio.run(run_solver(args, out))
        if "agent" in args.exp:
            asyncio.run(run_agent_load(args, out))


if __name__ == "__main__":
    main()
