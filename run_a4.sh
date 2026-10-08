#!/usr/bin/env bash
# Run A4 (orchestration cost vs workflow depth and context size) in a container from the
# feat/mcp image. Requires the MCP server to be up on 127.0.0.1:8200:
#   (cd ../RECOIL_Backend_MotionIntel_AI-mcp && docker compose -f docker-compose.mcp.yml up -d)
#
#   R2/experiments/run_a2.sh --models llama3.1:8b qwen3:8b --reps 10
# AGENT_DIR=<path to agent/> runs that agent host instead of the one in the image.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-recoil-mcp-optimizer:dev}"
AGENT_MOUNT=()
[[ -n "${AGENT_DIR:-}" ]] && AGENT_MOUNT=(-v "$(cd "$AGENT_DIR" && pwd)":/app/agent:ro)
OUT="${OUT:-results/a4_depth_context.jsonl}"

docker run --rm --name "r2-a4-agent-$$" --network host \
  -v "$HERE":/exp "${AGENT_MOUNT[@]}" \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PYTHONDONTWRITEBYTECODE=1 \
  "$IMAGE" \
  python -u /exp/a4_depth_context.py --out "/exp/$OUT" "$@"
