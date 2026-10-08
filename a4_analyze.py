#!/usr/bin/env python3
"""
Analyze A4 traces (results/a4_depth_context.jsonl).

depth   : per model and requested k, the realized number of successful
          solve_intermodal calls (and whether it equals k), calls rejected by the
          tool schema (self-corrected by the agent), LLM turns, and end-to-end / LLM / tool
          time; plus a linear fit of end-to-end time on the realized number of
          tool calls across all completed depth runs.
context : per model and context size c, end-to-end and LLM time, and a linear
          fit of LLM time on prompt characters (slope per 1,000 characters, R^2).
Writes results/a4_summary.json, or results/a4_summary<suffix>.json for
    python3 a4_analyze.py <traces.jsonl> <suffix>
"""
from __future__ import annotations

import json
import statistics as st
from collections import defaultdict
from pathlib import Path

RES = Path(__file__).parent / "results"


def linfit(xs, ys):
    """Ordinary least squares y = a + b x; returns (a, b, r2, n)."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = st.mean(xs), st.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_res = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    return {"intercept": a, "slope": b, "r2": 1 - ss_res / ss_tot if ss_tot else float("nan"), "n": n}


def ms(xs):
    return {"mean": st.mean(xs), "std": st.stdev(xs) if len(xs) > 1 else 0.0, "n": len(xs)} if xs else None


def per_run(r):
    steps = r.get("steps", [])
    llm = [s for s in steps if s["stage"] == "llm"]
    tools = [s for s in steps if s["stage"] == "tool"]
    return {
        "e2e": r.get("end_to_end_s"),
        "llm": sum(s["wall_s"] for s in llm),
        "tool": sum(s["wall_s"] for s in tools),
        "turns": len(llm),
        "solves": sum(s["tool"] == "solve_intermodal" and not s.get("is_error") for s in tools),
        "rejected": sum(bool(s.get("is_error")) for s in tools),     # e.g. misnamed fields, self-corrected
        "tool_calls": len(tools),
        "prompt_tokens_first": llm[0].get("prompt_tokens") if llm else None,
    }


def main():
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "a4_depth_context.jsonl"
    suffix = sys.argv[2] if len(sys.argv) > 2 else ""
    raw = [json.loads(l) for l in (RES / src).read_text().splitlines()]
    out = {"depth": {}, "context": {}, "errors": defaultdict(int)}
    groups = defaultdict(list)
    for r in raw:
        if "error" in r or not r.get("completed"):
            out["errors"][f"{r['model']}|{r['exp']}={r['level']}|{'error' if 'error' in r else 'no_answer'}"] += 1
            continue
        groups[(r["model"], r["exp"], r["level"], r["prompt_chars"])].append(per_run(r))

    by_model_depth = defaultdict(list)
    by_model_ctx = defaultdict(list)
    for (model, exp, level, chars), runs in sorted(groups.items()):
        row = {"n": len(runs),
               "e2e_s": ms([x["e2e"] for x in runs]), "llm_s": ms([x["llm"] for x in runs]),
               "tool_s": ms([x["tool"] for x in runs]), "turns": ms([x["turns"] for x in runs]),
               "prompt_tokens_first": ms([x["prompt_tokens_first"] for x in runs if x["prompt_tokens_first"]])}
        if exp == "depth":
            row["solves"] = ms([x["solves"] for x in runs])
            row["frac_solves_eq_k"] = sum(x["solves"] == level for x in runs) / len(runs)
            row["frac_no_solve"] = sum(x["solves"] == 0 for x in runs) / len(runs)
            row["rejected_calls"] = ms([x["rejected"] for x in runs])
            by_model_depth[model] += runs
        else:
            row["prompt_chars"] = chars
            by_model_ctx[model] += [dict(x, chars=chars) for x in runs]
        out[exp].setdefault(model, {})[str(level)] = row

    out["fits"] = {}
    for model, runs in by_model_depth.items():
        out["fits"][f"{model}|e2e_vs_tool_calls"] = linfit([x["tool_calls"] for x in runs],
                                                           [x["e2e"] for x in runs])
        out["fits"][f"{model}|e2e_vs_llm_turns"] = linfit([x["turns"] for x in runs],
                                                          [x["e2e"] for x in runs])
    for model, runs in by_model_ctx.items():
        f = linfit([x["chars"] / 1000 for x in runs], [x["llm"] for x in runs])
        out["fits"][f"{model}|llm_s_vs_kchars"] = f
    out["errors"] = dict(out["errors"])
    (RES / f"a4_summary{suffix}.json").write_text(json.dumps(out, indent=1))

    for model, rows in out["depth"].items():
        for k, r in rows.items():
            print(f"{model:12s} depth k={k:>2}: solves={r['solves']['mean']:.1f} =k:{r['frac_solves_eq_k']:.0%} "
                  f"rejected={r['rejected_calls']['mean']:.1f} "
                  f"none:{r['frac_no_solve']:.0%} e2e={r['e2e_s']['mean']:.1f}s turns={r['turns']['mean']:.1f} n={r['n']}")
    for model, rows in out["context"].items():
        for c, r in rows.items():
            print(f"{model:12s} ctx c={c:>5}: llm={r['llm_s']['mean']:.2f}±{r['llm_s']['std']:.2f}s "
                  f"e2e={r['e2e_s']['mean']:.2f}s first-turn tokens={r['prompt_tokens_first']['mean'] if r['prompt_tokens_first'] else None}")
    for k, f in out["fits"].items():
        if f:
            print(f"fit {k}: slope={f['slope']:.3f} intercept={f['intercept']:.2f} R2={f['r2']:.3f} n={f['n']}")
    print("errors:", out["errors"])


if __name__ == "__main__":
    main()
