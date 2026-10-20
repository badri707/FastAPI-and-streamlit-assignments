#!/usr/bin/env bash
# Shared helpers. Quote every path: the project may live in a folder with spaces.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN="$ROOT/data/run"
mkdir -p "$RUN"
cd "$ROOT"
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required: https://docs.astral.sh/uv/getting-started/installation/ (brew install uv)" >&2
  exit 1
fi
PY=(uv run --frozen python)
PORT="${SE_PORT:-8765}"
is_ours() {  # pidfile → running process of this project?
  local f="$1"; [[ -f "$f" ]] || return 1
  local pid; pid="$(cat "$f")"
  kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= | grep -q "app.cli"
}
