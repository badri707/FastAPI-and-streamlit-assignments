# Troubleshooting

Run `scripts/doctor` first — it checks Python/Node/uv, RAM and memory pressure, disk space, database migration, worker heartbeat,
port, Ollama and the configured model, and the optional SSD.

| Symptom | Likely cause / fix |
|---|---|
| "Port 8787 is already in use" | Another program uses it. Set `PORT=8790` in `.env`, then `scripts/start`. |
| "Already running" but UI unreachable | `scripts/stop`, check `data/logs/supervisor.log` and `api.out.log`, then `scripts/start`. |
| Banner: worker *unresponsive / never started* | Worker not running (sleep, crash). `scripts/stop && scripts/start`. Logs: `data/logs/worker.log`. |
| AI shows *unreachable* / *model_missing* | Start the Ollama app; `ollama list` should show the model in `.env` (`OLLAMA_MODEL`). See `docs/AI_MODEL.md`. Everything except AI keeps working. |
| AI answers are slow | CPU-only machines take 10–60 s per answer. On an 8 GB Mac close other heavy apps; keep `AI_NUM_CTX=4096`; or switch to the 1.7B model (draft-only is recommended for it). |
| Auto-replies stay "queued" | Quiet hours (default 23:00–07:00 IST), global pause, or hourly/daily limits. Check *Automation rules* and *System*. |
| Action shows *unknown outcome* / *held* | A send timed out; the worker reconciles automatically. If the target cannot be checked it is held for review — open it in the review queue. |
| "Community connection problem" | Sync failure (or injected fault in the Lab). Data is stale, not empty. Clear faults in the Lab; the next sync recovers. |
| Login says "Too many attempts" | Rate limit (5/minute). Wait a minute. |
| Lost admin password | Stop the app, back up, then `cd backend && .venv/bin/python -c "import sqlite3;c=sqlite3.connect('../data/app.db');c.execute('delete from users');c.commit()"`, start again and enroll with the new token. |
| After the Mac slept | Jobs past their expiry are expired (not sent late); a notification explains it. |
