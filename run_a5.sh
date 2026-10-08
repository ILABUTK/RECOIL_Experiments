#!/usr/bin/env bash
# Run A5 (concurrency) in a container from the feat/mcp image.
# 'license' needs the Gurobi license (mounted from the backend config);
# 'solver'/'agent' need the MCP server on 127.0.0.1:8200 with SOLVER_POOL_SIZE=4
# and no other experiment holding Gurobi sessions.
#
#   R2/experiments/run_a5.sh --exp license
#   R2/experiments/run_a5.sh --exp solver agent
# AGENT_DIR=<path to agent/> runs that agent host instead of the one in the image.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${BACKEND:-$HOME/projects/RECOIL_Backend_MotionIntel_AI-mcp}"
IMAGE="${IMAGE:-recoil-mcp-optimizer:dev}"
AGENT_MOUNT=()
[[ -n "${AGENT_DIR:-}" ]] && AGENT_MOUNT=(-v "$(cd "$AGENT_DIR" && pwd)":/app/agent:ro)
OUT="${OUT:-results/a5_concurrency.jsonl}"

docker run --rm --name "r2-a5-load-$$" --network host \
  -v "$HERE":/exp "${AGENT_MOUNT[@]}" \
  -v "$BACKEND/config":/app/config:ro \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PYTHONDONTWRITEBYTECODE=1 ${OLLAMA_BASE_URL:+-e OLLAMA_BASE_URL="$OLLAMA_BASE_URL"} \
  "$IMAGE" \
  python -u /exp/a5_concurrency.py --out "/exp/$OUT" "$@"
