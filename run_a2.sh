#!/usr/bin/env bash
# Run A2 (per-stage latency of the agent workflow) in a container from the
# feat/mcp image. Requires the MCP server to be up on 127.0.0.1:8200:
#   (cd ../RECOIL_Backend_MotionIntel_AI-mcp && docker compose -f docker-compose.mcp.yml up -d)
#
#   R2/experiments/run_a2.sh --models llama3.1:8b qwen3:8b --reps 20
# AGENT_DIR=<path to agent/> runs that agent host instead of the one baked into
# the image (the MCP server container is not touched).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-recoil-mcp-optimizer:dev}"
OUT="${OUT:-results/a2_stage_latency.jsonl}"
AGENT_MOUNT=()
[[ -n "${AGENT_DIR:-}" ]] && AGENT_MOUNT=(-v "$(cd "$AGENT_DIR" && pwd)":/app/agent:ro)

docker run --rm --name "r2-a2-agent-$$" --network host \
  -v "$HERE":/exp "${AGENT_MOUNT[@]}" \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" \
  python -u /exp/a2_stage_latency.py --out "/exp/$OUT" "$@"
