#!/usr/bin/env bash
# A5 follow-up (2026-10-07): the license probe accepted 4 of 4 concurrent Gurobi
# sessions, so (1) probe up to 8 sessions with the MCP server stopped, and
# (2) repeat the Gurobi solver-load test with a pool of 4, to compare pool 2 vs 4.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
MCP_DIR="${MCP_DIR:-$HOME/projects/RECOIL_Backend_MotionIntel_AI-mcp}"
export OUT="${OUT:-results/a5_concurrency.jsonl}"

echo "[$(date -u +%T)] stopping MCP server"
(cd "$MCP_DIR" && docker compose -f docker-compose.mcp.yml stop)
echo "[$(date -u +%T)] license probe up to 8"
"$HERE/run_a5.sh" --exp license --max-sessions 8 --hold 15

echo "[$(date -u +%T)] starting MCP server (Gurobi pool 4, HiGHS pool 16)"
(cd "$MCP_DIR" && SOLVER_POOL_SIZE=4 OPEN_SOLVER_POOL_SIZE=16 docker compose -f docker-compose.mcp.yml up -d --force-recreate)
until curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8200/mcp | grep -qv 000; do sleep 2; done
echo "[$(date -u +%T)] solver load: gurobi pool 4"
"$HERE/run_a5.sh" --exp solver --solver gurobi --levels 1 2 4 8 16 32 --per-client 5
echo "[$(date -u +%T)] A5 pool-4 follow-up done"
