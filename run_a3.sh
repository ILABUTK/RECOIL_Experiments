#!/usr/bin/env bash
# Run A3 (solver scaling) in a throwaway container built from the backend's
# production image (Gurobi 11.0.3 + WLS license). Does not touch the running
# prod container. The backend repo is mounted read-only.
#
#   R2/experiments/run_a3.sh --exp ref --reps 20
#   R2/experiments/run_a3.sh                      # all experiments
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${BACKEND:-$HOME/projects/RECOIL_Backend_MotionIntel_AI}"
IMAGE="${IMAGE:-mi_backend-fastapi-prod}"
OUT="${OUT:-results/a3_solver_scaling.jsonl}"

docker run --rm --name "r2-a3-solver-$$" \
  -v "$BACKEND":/app:ro \
  -v "$HERE":/exp \
  -e GRB_LICENSE_FILE=/app/config/gurobi.lic \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -w /app \
  "$IMAGE" \
  python -u /exp/a3_solver_scaling.py --out "/exp/$OUT" "$@"
