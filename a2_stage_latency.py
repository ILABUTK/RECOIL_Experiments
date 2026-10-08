#!/usr/bin/env python3
"""
R2 experiment A2 -- per-stage latency of the agentic workflow.

Runs the RECOIL agent host (backend branch feat/mcp, agent/host.py) on a fixed
set of natural-language prompts, sequentially, and stores the full per-stage
trace of every run: MCP tool discovery, each LLM turn (wall time, Ollama
load / prompt-eval / generation durations, token counts), and each MCP tool
call (client wall time, server-side queue wait and solve time).

Each prompt carries the tools and orders a correct agent should use, so task
success can be scored afterwards from the trace.

Runs inside the recoil-mcp-optimizer image; see run_a2.sh.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app")
from agent.host import run_agent  # noqa: E402

SO = {"o": "Seattle WA", "d": "Orlando FL", "v": 200, "T": 48}
PROMPTS = [
    {"id": "P01_reference",
     "text": "I need to ship 200 containers from Seattle to Orlando within 48 hours. "
             "What is the cheapest intermodal plan?",
     "expect_tools": ["solve_intermodal"], "expect_orders": [[SO]]},
    {"id": "P02_defaults",
     "text": "Plan a freight shipment from Seattle to Orlando.",
     "expect_tools": ["solve_intermodal"], "expect_orders": [[SO]]},
    {"id": "P03_houston_ny",
     "text": "Move 200 containers from Houston to New York; they must arrive within 36 hours.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Houston TX", "d": "New York NY", "v": 200, "T": 36}]]},
    {"id": "P04_la_chicago",
     "text": "What does it cost to send 150 containers from Los Angeles to Chicago with a "
             "60-hour deadline, and which modes are used?",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Los Angeles CA", "d": "Chicago IL", "v": 150, "T": 60}]]},
    {"id": "P05_sample3",
     "text": "Plan these three shipments together, 200 containers each, all due within 48 "
             "hours: Seattle to Orlando, Houston to New York, and Los Angeles to Chicago.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[SO, {"o": "Houston TX", "d": "New York NY", "v": 200, "T": 48},
                        {"o": "Los Angeles CA", "d": "Chicago IL", "v": 200, "T": 48}]]},
    {"id": "P06_network",
     "text": "Which cities can I ship between, and which transport modes does the network include?",
     "expect_tools": ["list_network"], "expect_orders": []},
    {"id": "P07_parameters",
     "text": "What capacity do trains and ships have in the model, and what carbon tax is assumed?",
     "expect_tools": ["get_model_parameters"], "expect_orders": []},
    {"id": "P08_one_locomotive",
     "text": "Ship 200 containers from Seattle to Orlando within 48 hours, but we only have "
             "one locomotive available. What is the best plan?",
     "expect_tools": ["solve_intermodal"], "expect_orders": [[SO]],
     "expect_args": {"max_locomotives": 1}},
    {"id": "P09_deadline_compare",
     "text": "Compare the total cost of shipping 200 containers from Seattle to Orlando with "
             "a 36-hour deadline versus a 72-hour deadline.",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[dict(SO, T=36)], [dict(SO, T=72)]]},
    {"id": "P10_two_orders",
     "text": "We have two orders due in 48 hours: 100 containers from Chicago to Houston and "
             "250 containers from New York to Los Angeles. Plan both.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Chicago IL", "d": "Houston TX", "v": 100, "T": 48},
                        {"o": "New York NY", "d": "Los Angeles CA", "v": 250, "T": 48}]]},
]


# Held-out prompts, written after the harness fixes of 2026-10-07 (tool rendering, number
# formatting, weight normalization, compare_scenarios) and never used to develop them; they
# check that the fixes generalize beyond P01-P10.
HELDOUT = [
    {"id": "H01_deadline_delta",
     "text": "How much more does it cost to ship 200 containers from Houston to New York if they "
             "must arrive in 24 hours instead of 60 hours?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Houston TX", "d": "New York NY", "v": 200, "T": 24}],
                       [{"o": "Houston TX", "d": "New York NY", "v": 200, "T": 60}]]},
    {"id": "H02_fleet_compare",
     "text": "Compare shipping 150 containers from Los Angeles to Chicago within 48 hours with one "
             "locomotive versus two locomotives.",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Los Angeles CA", "d": "Chicago IL", "v": 150, "T": 48}]],
     "expect_args": {"max_locomotives": 1}},
    {"id": "H03_three_orders",
     "text": "Plan three shipments due in 72 hours: 120 containers from Seattle to Chicago, 80 "
             "containers from Orlando to Houston, and 200 containers from New York to Los Angeles.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Seattle WA", "d": "Chicago IL", "v": 120, "T": 72},
                        {"o": "Orlando FL", "d": "Houston TX", "v": 80, "T": 72},
                        {"o": "New York NY", "d": "Los Angeles CA", "v": 200, "T": 72}]]},
    {"id": "H04_defaults",
     "text": "Ship 300 containers from Chicago to Orlando.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Chicago IL", "d": "Orlando FL", "v": 300, "T": 48}]]},
    {"id": "H05_origin_compare",
     "text": "Which is cheaper: sending 200 containers to Houston from Seattle or from Los Angeles, "
             "both within 48 hours?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Seattle WA", "d": "Houston TX", "v": 200, "T": 48}],
                       [{"o": "Los Angeles CA", "d": "Houston TX", "v": 200, "T": 48}]]},
]


# Second held-out set, written (and committed) on 2026-10-08 after H01-H05 had shown that
# llama3.1:8b failed scenario comparisons and *before* the agent-host changes made in
# response; H01-H05 thereby became development prompts. Reported as the held-out result.
HELDOUT2 = [
    {"id": "H06_deadline_choice",
     "text": "Is it cheaper to ship 120 containers from Chicago to New York with a 30-hour or a "
             "54-hour deadline?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Chicago IL", "d": "New York NY", "v": 120, "T": 30}],
                       [{"o": "Chicago IL", "d": "New York NY", "v": 120, "T": 54}]]},
    {"id": "H07_one_ship",
     "text": "What happens to the cost of moving 200 containers from Orlando to Chicago within 48 "
             "hours if we have only one ship available instead of two?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Orlando FL", "d": "Chicago IL", "v": 200, "T": 48}]],
     "expect_args": {"max_ships": 1}},
    {"id": "H08_volume_compare",
     "text": "Compare sending 100 containers versus 300 containers from Seattle to Los Angeles, "
             "both due within 48 hours.",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Seattle WA", "d": "Los Angeles CA", "v": 100, "T": 48}],
                       [{"o": "Seattle WA", "d": "Los Angeles CA", "v": 300, "T": 48}]]},
    {"id": "H09_origin_choice",
     "text": "We need to deliver 180 containers to New York within 40 hours. Should they come from "
             "Chicago or from Houston?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Chicago IL", "d": "New York NY", "v": 180, "T": 40}],
                       [{"o": "Houston TX", "d": "New York NY", "v": 180, "T": 40}]]},
    {"id": "H10_two_joint",
     "text": "Plan two shipments due within 60 hours: 150 containers from Houston to Seattle and "
             "90 containers from Los Angeles to Orlando.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Houston TX", "d": "Seattle WA", "v": 150, "T": 60},
                        {"o": "Los Angeles CA", "d": "Orlando FL", "v": 90, "T": 60}]]},
]


# Third held-out set, written (and committed) on 2026-10-08 before the MCP server change that
# exposes the fleet defaults (max_locomotives/max_ships = 2) in the tool schema, made in
# response to H02; H06-H10 had already been run with the earlier host and became development
# prompts as well. Reported as the held-out result.
HELDOUT3 = [
    {"id": "H11_ship_saving",
     "text": "How much would we save on 250 containers from New York to Houston due in 48 hours "
             "if two ships were available instead of one?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "New York NY", "d": "Houston TX", "v": 250, "T": 48}]],
     "expect_args": {"max_ships": 1}},
    {"id": "H12_one_locomotive",
     "text": "Ship 160 containers from Los Angeles to New York within 50 hours using at most one "
             "locomotive.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Los Angeles CA", "d": "New York NY", "v": 160, "T": 50}]],
     "expect_args": {"max_locomotives": 1}},
    {"id": "H13_deadline_choice",
     "text": "Should 220 containers from Seattle reach Chicago in 36 hours or in 72 hours to keep "
             "costs down?",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Seattle WA", "d": "Chicago IL", "v": 220, "T": 36}],
                       [{"o": "Seattle WA", "d": "Chicago IL", "v": 220, "T": 72}]]},
    {"id": "H14_two_joint",
     "text": "Plan 90 containers from Orlando to Los Angeles and 140 containers from Chicago to "
             "Seattle, both due within 48 hours.",
     "expect_tools": ["solve_intermodal"],
     "expect_orders": [[{"o": "Orlando FL", "d": "Los Angeles CA", "v": 90, "T": 48},
                        {"o": "Chicago IL", "d": "Seattle WA", "v": 140, "T": 48}]]},
    {"id": "H15_destination_compare",
     "text": "Compare the cost of sending 200 containers from Houston to Orlando versus from "
             "Houston to Chicago, both within 48 hours.",
     "expect_tools": ["solve_intermodal", "solve_intermodal"],
     "expect_orders": [[{"o": "Houston TX", "d": "Orlando FL", "v": 200, "T": 48}],
                       [{"o": "Houston TX", "d": "Chicago IL", "v": 200, "T": 48}]]},
]


async def main_async(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["model"], r["prompt_id"], r["rep"]))
    pool = {"main": PROMPTS, "heldout": HELDOUT, "heldout2": HELDOUT2, "heldout3": HELDOUT3}[args.prompt_set]
    prompts = [p for p in pool if not args.prompts or p["id"] in args.prompts]
    for model in args.models:
        # warm-up: load the model on the Ollama server; not recorded
        for _ in range(args.warmup):
            try:  # warm-up only; a failure (e.g. LLM gateway timeout) must not abort the run
                await run_agent(PROMPTS[0]["text"], model, args.mcp.split(","), num_ctx=args.num_ctx)
            except Exception as e:
                print(f"warm-up failed for {model}: {e!r:.200}", flush=True)
        for rep in range(args.reps):
            for p in prompts:
                if (model, p["id"], rep) in done:
                    continue
                t0 = time.perf_counter()
                try:
                    trace = await run_agent(p["text"], model, args.mcp.split(","),
                                            max_turns=args.max_turns, num_ctx=args.num_ctx)
                except Exception as e:  # record failures instead of aborting
                    trace = {"error": repr(e), "end_to_end_s": time.perf_counter() - t0,
                             "completed": False}
                rec = {"exp": "a2", "model": model, "prompt_id": p["id"], "rep": rep,
                       "expect": {k: v for k, v in p.items() if k.startswith("expect")},
                       "client_host": platform.node(),
                       "timestamp": datetime.now(timezone.utc).isoformat(), **trace}
                with out.open("a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
                print(f"{model} {p['id']} r{rep}: {trace.get('end_to_end_s', 0):.2f}s "
                      f"llm={trace.get('n_llm_turns')} tools={trace.get('n_tool_calls')} "
                      f"ok={trace.get('completed')}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["llama3.1:8b"])
    ap.add_argument("--prompts", nargs="*", help="prompt ids (default: all)")
    ap.add_argument("--prompt-set", choices=["main", "heldout", "heldout2", "heldout3"], default="main")
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--mcp", default="http://localhost:8200/mcp")
    ap.add_argument("--out", required=True)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
