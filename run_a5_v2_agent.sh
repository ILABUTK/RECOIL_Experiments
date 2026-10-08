#!/usr/bin/env bash
# A5 agent load with the A2 v4 agent host (feat/mcp 34c2d0a, agent/ mounted) and MCP server
# image from feat/mcp 6c98bf6 (Gurobi pool 2), one untimed warm-up request per model.
# LLM: dedicated local Ollama container on the solver host's NVIDIA L4 (driver 535 / CUDA 12.2),
# same model digests as the shared server; Ollama 0.24.0, the newest image that runs on this
# driver (0.30.x fails with "device kernel image is invalid"). The shared LLM server was loaded
# by other users. Run with OLLAMA_NUM_PARALLEL = 1 and 4 (LLM-side capacity parameter).
set -euo pipefail
cd "$(dirname "$0")"
export AGENT_DIR=../../../RECOIL_Backend_MotionIntel_AI-mcp/agent
export OLLAMA_BASE_URL=http://127.0.0.1:11435
for par in 1 4; do
  docker rm -f r2-ollama >/dev/null 2>&1 || true
  docker run -d --name r2-ollama --gpus all -p 127.0.0.1:11435:11434 -v r2-ollama:/root/.ollama \
    -e OLLAMA_KEEP_ALIVE=-1 -e OLLAMA_NUM_PARALLEL=$par ollama/ollama:0.24.0 >/dev/null
  until curl -s -o /dev/null $OLLAMA_BASE_URL/api/version; do sleep 1; done
  for model in llama3.1:8b gpt-oss:20b; do
    echo "[$(date -u +%T)] A5 agent load $model, OLLAMA_NUM_PARALLEL=$par"
    OUT=results/a5_v2_agent_local_par$par.jsonl ./run_a5.sh --exp agent --model "$model" --agent-levels 1 2 4 8 16
  done
done
echo "[$(date -u +%T)] A5 agent rerun done"
