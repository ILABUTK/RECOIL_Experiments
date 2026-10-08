# RECOIL agentic digital twin: performance and scalability experiments

Scripts and raw traces behind Section 4.3 ("System Performance and Scalability Analysis") of

> *Towards Autonomous Freight Intermodal Optimization via Generative AI and Agentic Digital
> Twins*, submitted to Computers & Industrial Engineering (revision 2).

Every run is recorded as one JSON line in `results/`; the analysis scripts read only these
files, so all numbers in the paper's tables can be recomputed without re-running anything.

## Experiments

| ID | Paper | What is measured | Run | Analyze | Main traces |
|---|---|---|---|---|---|
| A2 | §4.3.2, Table 4 | Per-stage latency (tool discovery, LLM turns, MCP calls, Gurobi) and task success of the agent, 10 requests × 20 reps per model; development and held-out requests × 10 reps | `run_a2_v4.sh` → `a2_stage_latency.py` | `a2_analyze.py` | `results/a2_v4_*.jsonl` |
| A3 | §4.3.3, Table 5, Figure 8 | Solver time and gap vs. number of orders and fleet size; Gurobi, HiGHS, SCIP, CBC | `run_a3.sh` → `a3_solver_scaling.py` | `a3_analyze.py`, `fig_a3_scaling.py` | `results/a3_solver_scaling*.jsonl` |
| A4 | §4.3.4 | Orchestration cost vs. context size and workflow depth | `run_r2_agent_rerun.sh` / `run_a4.sh` → `a4_depth_context.py` | `a4_analyze.py` | `results/a4_v2_depth_context.jsonl` |
| A5 | §4.3.5, Table 6 | Concurrent requests: MCP solver service (Gurobi pool 2 and 4, HiGHS pool 16) and complete agent requests on a dedicated LLM server (1 and 4 parallel slots) | `run_a5_all.sh`, `run_a5_pool4.sh`, `run_a5_v2_agent.sh` → `a5_concurrency.py` | `a5_analyze.py` | `results/a5_concurrency.jsonl`, `results/a5_v2_agent_local_par{1,4}.jsonl` |

`status.py` reports the progress of running experiments. `make_context_corpus.py` builds the
A4 context text (`data/context_corpus.txt`); `network_stats.py` counts nodes and arcs of the
20-node network.

Earlier and diagnostic runs are kept for transparency and are named accordingly:
`*_smoke_*`, `*_recheck_*`, `*_superseded_*`, `*_contended_*` (runs affected by other users of
the shared LLM server), `*_FAILED_*` (an Ollama image incompatible with the GPU driver), and
the `a2_v2`/`a2_v3` iterations that preceded the final `a2_v4` runs. The header of each
`run_*.sh` script states what changed relative to the previous run.

## Reproducing the tables

```bash
python3 a2_analyze.py     # Table 4
python3 a3_analyze.py     # Table 5  -> results/tab_a3_scaling.tex
python3 fig_a3_scaling.py # Figure 8 -> results/fig_a3_scaling.pdf
python3 a4_analyze.py     # Section 4.3.4
python3 a5_analyze.py     # Table 6  -> results/tab_a5_concurrency.tex
```

Requires Python 3.10+ and only the standard library (plus matplotlib for the figure).

## Re-running the experiments

The `run_*.sh` scripts start Docker containers against the RECOIL MCP server and agent host
(RECOIL backend, branch `feat/mcp`, not public; the commits used are given in each script
header), an Ollama server, and a Gurobi license, none of which are part of this repository.
The Ollama endpoint is read from `OLLAMA_BASE_URL`, and the path to the backend checkout from
the `BACKEND`, `MCP_DIR` or `AGENT_DIR` variable at the top of each script. The endpoints of the
language-model servers used in the study are not published; their specifications are given
below.

## Hardware and software

| Component | Specification |
|---|---|
| Solver and MCP host | 2 × Intel Xeon Platinum 8462Y+ (64 cores, 128 threads), 503 GB RAM |
| Exact solvers | Gurobi 11.0.3 (16 threads); HiGHS 1.11, SCIP and CBC through Google OR-Tools 9.14; relative gap 1e-4; time limit 600 s |
| MCP | Official MCP Python SDK 1.12.4, streamable HTTP; Gurobi pool of 2 (and 4) processes; HiGHS pool of 16 |
| LLM server, A2 and A4 | Ollama 0.30.6 on 2 × NVIDIA L40S (48 GB each), 128 CPU cores; shared with other users. Runs with more than 5 s of waiting (model loading or queueing caused by other users) are reported separately (`*_contended_*`). |
| LLM server, A5 agent load | Dedicated Ollama 0.24.0 container on the solver host, 1 × NVIDIA L4 (24 GB), driver 535 / CUDA 12.2; `OLLAMA_NUM_PARALLEL` = 1 and 4; `OLLAMA_KEEP_ALIVE=-1` |
| Language models | `llama3.1:8b` (Q4_K_M, Ollama manifest digest `46e0c10c039e`) and `gpt-oss:20b` (MXFP4, digest `17052f91a42e`), identical files on both servers; temperature 0; context window 8,192 tokens |
| Network | 20 nodes (6 highway, 8 rail, 6 waterway), 418 directed arcs |

## Trace format

Each line is one JSON object. Agent runs hold the prompt, model,
the ordered `steps` (`mcp_discovery`, `llm` turns with server-side timings and token counts,
`tool` calls with arguments, results and solver time; A5 groups the runs of one load level under `"exp": "agent"`), the final answer, and
`end_to_end_s`. Solver runs (A3, `exp` = `ref`, `orders`, `fleet`, ...) hold the instance (`n_orders`, `fleet`, `seed`), Gurobi or
OR-Tools status, runtime, objective, bound and gap. Lines with `"exp": "env"` record the
configuration of the run.

## License

Apache License 2.0 (see `LICENSE`).
