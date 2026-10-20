#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
if is_ours "$RUN/web.pid"; then echo "Web already running (pid $(cat "$RUN/web.pid"))"; else
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then echo "Port $PORT is in use by another program. Set SE_PORT=... and retry." >&2; exit 1; fi
  nohup "${PY[@]}" -m app.cli serve >>"$RUN/web.log" 2>&1 & echo $! >"$RUN/web.pid"
fi
if is_ours "$RUN/worker.pid"; then echo "Worker already running (pid $(cat "$RUN/worker.pid"))"; else
  nohup "${PY[@]}" -m app.cli worker >>"$RUN/worker.log" 2>&1 & echo $! >"$RUN/worker.pid"
fi
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then break; fi; sleep 0.5
done
if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
  echo "Web:    http://127.0.0.1:$PORT  (sign in with the token in data/admin_token)"
else echo "Web did not become healthy — see $RUN/web.log" >&2; exit 1; fi
is_ours "$RUN/worker.pid" && echo "Worker: running (pid $(cat "$RUN/worker.pid")), log $RUN/worker.log"
echo "Note: jobs stop while this computer sleeps; missed reports are caught up on wake."
