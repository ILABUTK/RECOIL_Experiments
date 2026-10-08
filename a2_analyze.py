#!/usr/bin/env python3
"""
Analyze A2 traces (results/a2_stage_latency.jsonl).

Per run it derives:
  - stage times: MCP discovery, LLM (sum over turns), tool calls (client wall),
    solver (server build+solve), end-to-end
  - outcome: 'llm_server_error' (exception, e.g. HTTP 504 from the LLM proxy),
    'no_answer' (turn limit), else answered
  - task success, scored against the prompt's expectations:
      tools_ok   : every expected tool was called (multiset, solve calls counted)
      args_ok    : every expected order set matches one solve_intermodal call
                   (origin/destination by unique prefix, containers, deadline),
                   expected extra arguments match, and no solve call overrides
                   the fleet limits (max_locomotives/max_ships) unless requested
      answer_ok  : for solve prompts, every objective returned by the solver
                   appears in the final answer (within $1)
      success    : tools_ok and args_ok and answer_ok
Writes results/a2_summary_by_prompt.csv, results/a2_summary_by_model.json and
results/tab_a2_latency.tex.
"""
from __future__ import annotations

import csv
import json
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
WAIT_THRESHOLD_S = 5.0
CITIES = ["New York NY", "Orlando FL", "Houston TX", "Los Angeles CA", "Chicago IL", "Seattle WA"]


def city(name: str):
    if name in CITIES:
        return name
    hits = [c for c in CITIES if c.lower().startswith(str(name).strip().lower())]
    return hits[0] if len(hits) == 1 else name


def norm_orders(args: dict):
    orders = args.get("orders", [])
    if isinstance(orders, str):
        try:
            orders = json.loads(orders)
        except json.JSONDecodeError:
            return None
    out = []
    for o in orders:
        out.append((city(o.get("origin")), city(o.get("destination")),
                    int(float(o.get("containers", 200))), float(o.get("deadline_hours", 48))))
    return sorted(out)


def expected_orders(exp_list):
    return [sorted((e["o"], e["d"], int(e["v"]), float(e["T"])) for e in group) for group in exp_list]


def numbers_in(text: str):
    # accept comma or (narrow/no-break) space thousands separators: "52,355.23", "52 355.23"
    text = re.sub(r"(?<=\d)[ \u00a0\u202f\u2009](?=\d{3}(?!\d))", "", text or "")
    return [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.\d+|\d[\d,]{3,}", text)]


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    f, c = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def score(r: dict) -> dict:
    out = {"model": r["model"], "prompt_id": r["prompt_id"], "rep": r["rep"],
           "e2e_s": r.get("end_to_end_s")}
    if "error" in r:
        out["outcome"] = "llm_server_error"
        return out
    steps = r["steps"]
    llm = [s for s in steps if s["stage"] == "llm"]
    tools = [s for s in steps if s["stage"] == "tool"]
    out.update({
        "outcome": "answered" if r.get("completed") else "no_answer",
        "discovery_s": sum(s["wall_s"] for s in steps if s["stage"] == "mcp_discovery"),
        "llm_s": sum(s["wall_s"] for s in llm),
        "llm_load_s": sum(s.get("load_s") or 0 for s in llm),
        "llm_eval_s": sum(s.get("eval_s") or 0 for s in llm),
        # time in LLM calls not spent processing the prompt or generating: model (re)load
        # and queueing on the shared Ollama server; > WAIT_THRESHOLD_S flags contention
        "llm_wait_s": sum(s["wall_s"] - (s.get("prompt_eval_s") or 0) - (s.get("eval_s") or 0) for s in llm),
        "tool_s": sum(s["wall_s"] for s in tools),
        "solver_s": sum((s.get("server_timing") or {}).get("build_and_solve_s", 0) for s in tools),
        "gurobi_s": sum((s.get("server_timing") or {}).get(
            "solver_runtime_s", (s.get("server_timing") or {}).get("gurobi_runtime_s", 0)) for s in tools),
        "n_llm_turns": len(llm), "n_tool_calls": len(tools),
        "output_tokens": sum(s.get("output_tokens") or 0 for s in llm),
        "max_context_chars": max((s.get("context_chars") or 0 for s in llm), default=0),
        "text_tool_calls": any(s.get("tool_calls_from_text") for s in llm),
    })
    # Score the MCP calls that were actually executed. Newer traces record the arguments sent
    # on each tool step: after the host's normalization (weight_tons <= 0 dropped, so the
    # default 14 t/container applies) and with compare_scenarios expanded into one
    # solve_intermodal call per scenario. Older traces: the calls as the LLM wrote them,
    # with normalized_arguments where the host changed them.
    if tools and all("arguments" in s for s in tools):
        calls = [{"name": s["tool"], "arguments": s["arguments"]} for s in tools]
    else:
        calls = [c for s in llm for c in s["tool_calls"]]
        if len(tools) == len(calls):
            calls = [{"name": c["name"], "arguments": s.get("normalized_arguments") or c["arguments"]}
                     for s, c in zip(tools, calls)]
    exp = r["expect"]
    called = Counter(c["name"] for c in calls)
    need = Counter(exp["expect_tools"])
    out["tools_ok"] = all(called[t] >= n for t, n in need.items())
    solve_calls = [norm_orders(c["arguments"]) for c in calls if c["name"] == "solve_intermodal"]
    args_ok = all(e in solve_calls for e in expected_orders(exp.get("expect_orders", [])))
    for k, v in (exp.get("expect_args") or {}).items():
        args_ok &= any(c["arguments"].get(k) == v for c in calls if c["name"] == "solve_intermodal")
    for k in ("max_locomotives", "max_ships"):   # unrequested fleet overrides change the problem
        if k not in (exp.get("expect_args") or {}):
            args_ok &= all(c["arguments"].get(k) in (None, 2) for c in calls if c["name"] == "solve_intermodal")
    # so does an unrequested cargo weight (runs from before the host fix sent weight_tons=0
    # and solved a weightless problem)
    for c in calls:
        if c["name"] != "solve_intermodal":
            continue
        orders = c["arguments"].get("orders", [])
        if isinstance(orders, str):
            try:
                orders = json.loads(orders)
            except json.JSONDecodeError:
                orders = []
        for o in orders if isinstance(orders, list) else []:
            w = o.get("weight_tons") if isinstance(o, dict) else None
            if w is not None:
                args_ok &= abs(float(w) - 14.0 * float(o.get("containers", 200))) < 1e-6
    out["args_ok"] = args_ok
    objs = [s["objective"] for s in tools if s.get("objective") is not None]
    nums = numbers_in(r.get("final_answer"))
    out["answer_ok"] = all(any(abs(n - o) < 1.0 for n in nums) for o in objs) if objs else True
    out["contended"] = out["llm_wait_s"] > WAIT_THRESHOLD_S
    out["success"] = (out["outcome"] == "answered" and out["tools_ok"] and out["args_ok"]
                      and out["answer_ok"])
    return out


def summarize(rows, uncontended_only=False):
    ok = [r for r in rows if r["outcome"] != "llm_server_error"]
    n_contended = sum(bool(r.get("contended")) for r in ok)
    if uncontended_only:
        ok = [r for r in ok if not r.get("contended")]
    def m(key):
        xs = [r[key] for r in ok if r.get(key) is not None]
        return (st.mean(xs) if xs else float("nan"), st.stdev(xs) if len(xs) > 1 else 0.0,
                pct(xs, 0.95))
    return {
        "runs": len(rows), "server_errors": sum(r["outcome"] == "llm_server_error" for r in rows),
        "contended_runs": n_contended, "runs_used": len(ok),
        "success_rate": sum(bool(r.get("success")) for r in ok) / len(ok) if ok else float("nan"),
        "tools_ok_rate": sum(bool(r.get("tools_ok")) for r in ok) / len(ok) if ok else float("nan"),
        "args_ok_rate": sum(bool(r.get("args_ok")) for r in ok) / len(ok) if ok else float("nan"),
        "answer_ok_rate": sum(bool(r.get("answer_ok")) for r in ok) / len(ok) if ok else float("nan"),
        "text_tool_call_rate": sum(bool(r.get("text_tool_calls")) for r in ok) / len(ok) if ok else float("nan"),
        **{f"{k}_{s}": v for k in ("e2e_s", "llm_s", "llm_wait_s", "tool_s", "solver_s", "gurobi_s",
                                   "discovery_s", "n_llm_turns", "n_tool_calls", "output_tokens")
           for s, v in zip(("mean", "std", "p95"), m(k))},
    }


def main():
    import sys
    src = sys.argv[1] if len(sys.argv) > 1 else "a2_stage_latency.jsonl"
    raw = [json.loads(l) for l in (RES / src).read_text().splitlines()]
    rows = [score(r) for r in raw]
    by_mp, by_m = defaultdict(list), defaultdict(list)
    for r in rows:
        by_mp[(r["model"], r["prompt_id"])].append(r)
        by_m[r["model"]].append(r)

    with (RES / "a2_summary_by_prompt.csv").open("w", newline="") as f:
        w = None
        for (model, pid), rs in sorted(by_mp.items()):
            s = {"model": model, "prompt_id": pid, **summarize(rs)}
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(s))
                w.writeheader()
            w.writerow(s)
    summ = {m: summarize(rs) for m, rs in by_m.items()}
    summ.update({f"{m} (uncontended)": summarize(rs, uncontended_only=True) for m, rs in by_m.items()})
    (RES / "a2_summary_by_model.json").write_text(json.dumps(summ, indent=2))

    # LaTeX table: per model, stage means (std) and success
    lines = [r"\begin{tabular}{@{}lrrrrrr@{}}", r"\toprule",
             r"Model & End-to-end (s) & LLM (s) & Tool calls (s) & of which solver (s) & LLM turns & Task success \\",
             r"\midrule"]
    for m, s in summ.items():
        lines.append(
            f"{m} & {s['e2e_s_mean']:.2f} ({s['e2e_s_std']:.2f}) & {s['llm_s_mean']:.2f} ({s['llm_s_std']:.2f}) & "
            f"{s['tool_s_mean']:.3f} & {s['solver_s_mean']:.3f} & {s['n_llm_turns_mean']:.1f} & "
            f"{100 * s['success_rate']:.0f}\\% \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (RES / "tab_a2_latency.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps(summ, indent=1))


if __name__ == "__main__":
    main()
