#!/usr/bin/env python3
"""
R2 experiment A4 -- cost of the orchestration layer versus workflow depth and
context size.

depth   : prompts asking for k shipments to be planned *separately* (one
          optimization run each), k in DEPTHS, so the agent should make k
          solve_intermodal calls. Records the realized number of tool calls,
          LLM turns, and time per stage.
context : the reference Seattle->Orlando request prefixed with c characters of
          domain text (data/context_corpus.txt, the R1 literature review) as
          'retrieved documents', c in CONTEXT_CHARS. Measures LLM time versus
          context size with the workflow fixed.

Runs inside the recoil-mcp-optimizer image (see run_a4.sh); traces appended
to --out, resumable.
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

HERE = Path(__file__).parent
SHIPMENTS = [
    ("Seattle", "Orlando", 200), ("Houston", "New York", 150), ("Los Angeles", "Chicago", 180),
    ("Chicago", "Houston", 100), ("New York", "Los Angeles", 250), ("Orlando", "Seattle", 120),
    ("Houston", "Chicago", 90), ("Los Angeles", "Orlando", 160),
]
DEPTHS = [1, 2, 3, 4, 6, 8]
CONTEXT_CHARS = [0, 2000, 4000, 8000, 16000, 26000]
REF = "I need to ship 200 containers from Seattle to Orlando within 48 hours. What is the cheapest intermodal plan?"


def depth_prompt(k: int) -> str:
    lines = [f"{i + 1}. {v} containers from {o} to {d}, due within 48 hours"
             for i, (o, d, v) in enumerate(SHIPMENTS[:k])]
    return ("Plan each of the following shipments separately, with its own optimization run, "
            "and report the cost and route of each:\n" + "\n".join(lines))


def context_prompt(c: int, corpus: str) -> str:
    if c == 0:
        return REF
    return ("Background documents retrieved from the knowledge base:\n\"\"\"\n" + corpus[:c]
            + "\n\"\"\"\n\nUser request: " + REF)


async def main_async(args):
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            r = json.loads(line)
            done.add((r["model"], r["exp"], r["level"], r["rep"]))
    corpus = (HERE / "data" / "context_corpus.txt").read_text()
    jobs = []
    if "depth" in args.exp:
        jobs += [("depth", k, depth_prompt(k)) for k in DEPTHS]
    if "context" in args.exp:
        jobs += [("context", c, context_prompt(c, corpus)) for c in CONTEXT_CHARS]
    for model in args.models:
        for _ in range(args.warmup):
            try:  # warm-up only; a failure (e.g. LLM gateway timeout) must not abort the run
                await run_agent(REF, model, [args.mcp], num_ctx=args.num_ctx)
            except Exception as e:
                print(f"warm-up failed for {model}: {e!r:.200}", flush=True)
        for rep in range(args.reps):
            for exp, level, prompt in jobs:
                if (model, exp, level, rep) in done:
                    continue
                t0 = time.perf_counter()
                try:
                    trace = await run_agent(prompt, model, [args.mcp], max_turns=args.max_turns,
                                            num_ctx=args.num_ctx)
                except Exception as e:
                    trace = {"error": repr(e), "end_to_end_s": time.perf_counter() - t0,
                             "completed": False}
                rec = {"exp": exp, "level": level, "model": model, "rep": rep,
                       "prompt_chars": len(prompt), "client_host": platform.node(),
                       "timestamp": datetime.now(timezone.utc).isoformat(), **trace}
                with out.open("a") as f:
                    f.write(json.dumps(rec, default=str) + "\n")
                print(f"{model} {exp}={level} r{rep}: {trace.get('end_to_end_s', 0):.2f}s "
                      f"tools={trace.get('n_tool_calls')} ok={trace.get('completed')}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["llama3.1:8b"])
    ap.add_argument("--exp", nargs="+", default=["depth", "context"], choices=["depth", "context"])
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--max-turns", type=int, default=12)
    ap.add_argument("--num-ctx", type=int, default=16384)
    ap.add_argument("--mcp", default="http://localhost:8200/mcp")
    ap.add_argument("--out", required=True)
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
