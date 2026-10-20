#!/usr/bin/env bash
# Loads the fixed SYNTHETIC scenarios into data/test.db only. Pass --yes to discard an existing test workspace.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
"${PY[@]}" -m app.cli seed-evaluation "$@"
