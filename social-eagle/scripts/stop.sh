#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
for name in web worker; do
  f="$RUN/$name.pid"
  if is_ours "$f"; then kill "$(cat "$f")" && echo "Stopped $name"; else echo "$name not running"; fi
  rm -f "$f"
done
