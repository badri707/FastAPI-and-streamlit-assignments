#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
uv sync --frozen --python 3.12
"${PY[@]}" -m app.cli init
echo "Setup complete. Start with: scripts/start.sh"
