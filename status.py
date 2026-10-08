#!/usr/bin/env python3
"""
Progress and health of the R2 experiment runs.

For every experiment it reports records done / expected, failed records, time
since the last record, whether a container is still writing the file, the
recent completion rate, and an ETA. States:

  queued   file not created yet (e.g. A4 waits for A2 in the same job)
  running  a container is writing the file and records keep arriving
  STALLED  a container is alive but no record for longer than `stall_s`
           (each experiment's threshold exceeds its longest legitimate solve/run)
  DEAD     no container writes the file and it is incomplete
  RERUN    incomplete because records were set aside for a rerun
           (a results/<stem>_contended_*.jsonl archive exists); not a failure
  done     all expected records written

    python3 R2/experiments/status.py            # table
    python3 R2/experiments/status.py --watch    # one line per change (for monitoring)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

RES = Path(__file__).parent / "results"

# name, file, expected records, stall threshold (s), worst case per record (s), parallel workers
# A3: 600 s time limit per solve; A2/A4: one agent run is at most a few minutes.
# The rate-based ETA extrapolates the last 15 records and is optimistic when the
# remaining records are harder; "max" is the worst-case bound remaining x worst / workers.
EXPERIMENTS = [
    ("A3 gurobi", "a3_solver_scaling.jsonl", 126, 1500, 600, 1),
    ("A3 highs", "a3_solver_scaling_highs.jsonl", 90, 1500, 600, 8),
    ("A3 cbc", "a3_solver_scaling_cbc.jsonl", 90, 1500, 600, 8),
    ("A3 scip", "a3_solver_scaling_scip.jsonl", 90, 1500, 600, 1),
    ("A2 llama+oss", "a2_stage_latency.jsonl", 400, 900, None, 1),
    ("A4 llama+oss", "a4_depth_context.jsonl", 240, 900, None, 1),
    # A5: one record per load level plus one env line per invocation (5 + 4 + 2x6 + 2x5)
    ("A5 load", "a5_concurrency.jsonl", 47, 1800, None, 1),  # + follow-up: 2 env + 8 license + 6 solver
]


def writers() -> dict:
    """Map result file name -> (running container name, start time), from docker container args."""
    out = {}
    try:
        names = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True,
                               text=True, timeout=20).stdout.split()
        for n in names:
            if not n.startswith("r2-"):
                continue
            info = subprocess.run(["docker", "inspect", n, "--format",
                                   "{{.State.StartedAt}}|{{join .Args \" \"}}"],
                                  capture_output=True, text=True, timeout=20).stdout
            started, _, args = info.partition("|")
            t0 = datetime.fromisoformat(started.strip()[:26].rstrip("Z") + "+00:00").timestamp()
            for tok in args.split():
                if tok.startswith("/exp/results/"):
                    out[Path(tok).name] = (n, t0)
    except Exception:
        pass
    return out


def is_failure(r: dict) -> bool:
    if "error" in r:
        return True
    if "status" in r and isinstance(r["status"], int):     # A3: 2 optimal, 9 time limit
        return r["status"] not in (2, 9)
    return r.get("completed") is False


def stat(name, fname, total, stall_s, worst_s, workers, live):
    p = RES / fname
    if not p.exists():
        return {"name": name, "state": "queued", "done": 0, "total": total}
    recs = []
    for line in p.read_text().splitlines():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass                                          # partially written last line
    ts = sorted(datetime.fromisoformat(r["timestamp"]).timestamp() for r in recs if "timestamp" in r)
    now = time.time()
    age = now - ts[-1] if ts else now - p.stat().st_mtime
    recent = [t for t in ts[-15:] if now - t < 1800]   # ignore gaps before a resumed run
    rate = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 2 and recent[-1] > recent[0] else None
    done = len(recs)
    eta = (total - done) / rate if rate else None
    eta_max = -(-(total - done) // workers) * worst_s if worst_s else None
    container, started = live.get(fname, (None, None))
    if started is not None:                       # a resumed run: measure from its start
        age = min(age, now - started)
    if done >= total:
        state = "done"
    elif container is None and list(RES.glob(f"{Path(fname).stem}_contended_*.jsonl")):
        state = "RERUN"
    elif container is None:
        state = "DEAD"
    elif age > stall_s:
        state = "STALLED"
    else:
        state = "running"
    return {"name": name, "state": state, "done": done, "total": total,
            "failed": sum(is_failure(r) for r in recs), "age_s": age, "eta_s": eta, "eta_max_s": eta_max,
            "container": container}


def fmt_t(s):
    if s is None:
        return "-"
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


def line(st):
    if st["state"] == "queued":
        return f"{st['name']:13s} queued"
    return (f"{st['name']:13s} {st['state']:8s} {st['done']:>4}/{st['total']:<4} "
            f"failed={st['failed']:<3} last={fmt_t(st['age_s']):>7} ago  eta={fmt_t(st['eta_s'])}"
            + (f" (max {fmt_t(st['eta_max_s'])})" if st.get("eta_max_s") is not None and st["state"] != "done" else ""))


def snapshot():
    live = writers()
    return [stat(*e, live) for e in EXPERIMENTS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--summary-every", type=int, default=900, help="seconds between summary lines in --watch")
    args = ap.parse_args()
    if not args.watch:
        print(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
        for st in snapshot():
            print(line(st))
        return
    prev, last_summary = {}, 0.0
    while True:
        snap = snapshot()
        for st in snap:
            key = st["name"]
            old = prev.get(key)
            changed = old is None and st["state"] in ("DEAD", "STALLED") or (
                old is not None and (old["state"] != st["state"] or st.get("failed", 0) > old.get("failed", 0)))
            if changed:
                print("ALERT " if st["state"] in ("DEAD", "STALLED") else "EVENT ", line(st), flush=True)
            prev[key] = st
        if time.time() - last_summary >= args.summary_every:
            print("SUMMARY " + " | ".join(f"{s['name']} {s['done']}/{s['total']} {s['state']}" for s in snap),
                  flush=True)
            last_summary = time.time()
        if all(s["state"] == "done" for s in snap):
            print("ALL DONE", flush=True)
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
