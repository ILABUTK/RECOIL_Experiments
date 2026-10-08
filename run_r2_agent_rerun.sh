#!/usr/bin/env bash
# Rerun the agent experiments A4 (depth/context) and A5 (agent load) with the revised agent
# host and MCP server used for A2 v4 (host feat/mcp 34c2d0a, agent/ mounted into the client
# containers; server image from feat/mcp 6c98bf6). Run it after
# run_a2_v4.sh has finished. The MCP server is recreated with the default Gurobi pool of 2
# (same image, as in run_a5_all.sh). The A5 solver-only and license tests do not involve the
# agent and are not repeated.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
MCP_DIR="${MCP_DIR:-$HOME/projects/RECOIL_Backend_MotionIntel_AI-mcp}"
export AGENT_DIR=../../../RECOIL_Backend_MotionIntel_AI-mcp/agent


echo "[$(date -u +%T)] recreating MCP server (Gurobi pool 2, HiGHS pool 16)"
(cd "$MCP_DIR" && SOLVER_POOL_SIZE=2 OPEN_SOLVER_POOL_SIZE=16 docker compose -f docker-compose.mcp.yml up -d --force-recreate)
until curl -s -o /dev/null -w '%{http_code}' -X POST http://127.0.0.1:8200/mcp | grep -qv 000; do sleep 2; done

for model in llama3.1:8b gpt-oss:20b; do
  echo "[$(date -u +%T)] A4 $model"
  OUT=results/a4_v2_depth_context.jsonl ./run_a4.sh --models "$model" --reps 10
done
for model in llama3.1:8b gpt-oss:20b; do
  echo "[$(date -u +%T)] A5 agent load $model"
  OUT=results/a5_v2_agent.jsonl ./run_a5.sh --exp agent --model "$model" --agent-levels 1 2 4 8 16
done
echo "[$(date -u +%T)] A4/A5 agent rerun done"
