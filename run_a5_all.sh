#!/usr/bin/env bash
# Full A5 sequence (concurrency). Run only when no other experiment uses the
# MCP server, Gurobi, or the LLM server.
#   1. stop the MCP server so it holds no Gurobi session; license probe
#   2. restart the MCP server with a Gurobi pool of 2 (license) and HiGHS pool of 16
#   3. solver-only load: Gurobi pool, then HiGHS pool (unique 3-order instances)
#   4. end-to-end agent load (llama3.1:8b, then gpt-oss:20b)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MCP_DIR="${MCP_DIR:-$HOME/projects/RECOIL_Backend_MotionIntel_AI-mcp}"
OUT="${OUT:-results/a5_concurrency.jsonl}"
export OUT

echo "[$(date -u +%T)] stopping MCP server"
(cd "$MCP_DIR" && docker compose -f docker-compose.mcp.yml stop)

echo "[$(date -u +%T)] license probe"
"$HERE/run_a5.sh" --exp license --max-sessions 4 --hold 15

echo "[$(date -u +%T)] starting MCP server (Gurobi pool 2, HiGHS pool 16)"
(cd "$MCP_DIR" && SOLVER_POOL_SIZE=2 OPEN_SOLVER_POOL_SIZE=16 docker compose -f docker-compose.mcp.yml up -d --force-recreate)
until curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8200/mcp | grep -qv 000; do sleep 2; done

echo "[$(date -u +%T)] solver load: gurobi"
"$HERE/run_a5.sh" --exp solver --solver gurobi --levels 1 2 4 8 16 32 --per-client 5
echo "[$(date -u +%T)] solver load: highs"
"$HERE/run_a5.sh" --exp solver --solver highs --levels 1 2 4 8 16 32 --per-client 5

for model in llama3.1:8b gpt-oss:20b; do
  echo "[$(date -u +%T)] agent load: $model"
  "$HERE/run_a5.sh" --exp agent --model "$model" --agent-levels 1 2 4 8 16
done
echo "[$(date -u +%T)] A5 done"
