#!/usr/bin/env bash
# A2 v4 (final): agent host feat/mcp 34c2d0a (agent/ mounted into the client container) and MCP
# server image built from feat/mcp 6c98bf6 (fleet defaults max_locomotives/max_ships = 2 shown
# in the tool schema), Gurobi pool 2. Both models: main set (20 reps); development prompts
# H01-H05 and H06-H10, held-out prompts H11-H15 (10 reps each).
# Models run one after the other so they do not evict each other on the Ollama server.
set -euo pipefail
cd "$(dirname "$0")"
export AGENT_DIR=../../../RECOIL_Backend_MotionIntel_AI-mcp/agent

for m in llama3.1:8b gpt-oss:20b; do
  tag=${m%%[:.]*}; tag=${tag/gpt-oss/gptoss}
  OUT=results/a2_v4_${tag}_main.jsonl      ./run_a2.sh --models "$m" --reps 20
  for set in heldout heldout2 heldout3; do
    OUT=results/a2_v4_${tag}_${set}.jsonl ./run_a2.sh --models "$m" --reps 10 --warmup 0 --prompt-set $set
  done
done
