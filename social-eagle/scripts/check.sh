#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
echo "== lint";      uv run --frozen ruff check app tests
echo "== typecheck"; uv run --frozen mypy app
echo "== tests";     uv run --frozen pytest
