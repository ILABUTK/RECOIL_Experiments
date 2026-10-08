#!/usr/bin/env bash
# A2 v2: rerun with the revised agent host (feat/mcp working tree, agent/ mounted into the
# client container; MCP server unchanged):
#   - llama3.1: tool list rendered TypeScript-style in the system prompt on every turn and
#     JSON calls parsed by the host (Ollama's llama3.1 template drops tools after the first
#     tool result; its parser mislabels a second call)
#   - tool results: costs pre-formatted with thousands separators, other floats rounded
#   - weight_tons <= 0 dropped so the default weight applies
#   - host-side compare_scenarios tool (one solve_intermodal call per scenario)
#   - native tool calling (gpt-oss): defaults and nested order fields added to descriptions
# Host version: feat/mcp 8780fde.
# Models run one after the other so they do not evict each other on the Ollama server.
set -euo pipefail
cd "$(dirname "$0")"
export AGENT_DIR=../../../RECOIL_Backend_MotionIntel_AI-mcp/agent

OUT=results/a2_v2_llama_main.jsonl   ./run_a2.sh --models llama3.1:8b --reps 20
OUT=results/a2_v2_gptoss_main.jsonl  ./run_a2.sh --models gpt-oss:20b --reps 20
OUT=results/a2_v2_llama_heldout.jsonl  ./run_a2.sh --models llama3.1:8b --reps 10 --prompt-set heldout
OUT=results/a2_v2_gptoss_heldout.jsonl ./run_a2.sh --models gpt-oss:20b --reps 10 --prompt-set heldout
