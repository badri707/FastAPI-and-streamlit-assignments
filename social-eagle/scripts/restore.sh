#!/usr/bin/env bash
# Restores into a separate evaluation folder (data/restore-eval) and verifies; never overwrites live data.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
[[ $# -ge 1 ]] || { echo "usage: scripts/restore.sh data/backups/test-YYYYMMDDTHHMMSSZ.db [--to DIR]"; exit 2; }
"${PY[@]}" -m app.cli restore "$@"
