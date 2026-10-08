#!/usr/bin/env bash
# A2 v3: final runs with agent host feat/mcp 34c2d0a (agent/ mounted into the client container;
# MCP server unchanged). Changes since v2 (8780fde): compare_scenarios takes flat
# single-shipment scenarios; JSON-text arguments parsed tolerantly. Both models, main set
# (20 reps), development prompts H01-H05 and held-out prompts H06-H10 (10 reps each).
# Models run one after the other so they do not evict each other on the Ollama server.
set -euo pipefail
cd "$(dirname "$0")"
export AGENT_DIR=../../../RECOIL_Backend_MotionIntel_AI-mcp/agent

for m in llama3.1:8b gpt-oss:20b; do
  tag=${m%%[:.]*}; tag=${tag/gpt-oss/gptoss}
  OUT=results/a2_v3_${tag}_main.jsonl     ./run_a2.sh --models "$m" --reps 20
  OUT=results/a2_v3_${tag}_dev.jsonl      ./run_a2.sh --models "$m" --reps 10 --warmup 0 --prompt-set heldout
  OUT=results/a2_v3_${tag}_heldout2.jsonl ./run_a2.sh --models "$m" --reps 10 --warmup 0 --prompt-set heldout2
done
