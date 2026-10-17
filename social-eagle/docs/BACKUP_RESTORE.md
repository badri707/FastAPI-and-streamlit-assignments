# Backup and restore

- **What:** `app.db` and `simulator.db`, copied with SQLite's online backup API (safe while the app is writing — never a raw file copy),
  plus `manifest.json` with SHA-256 checksums, integrity-check result and row counts.
- **When:** nightly at 02:00 IST while the worker runs, on demand from *Import & backups*, or `scripts/backup [dest-dir]`.
- **Where:** `data/backups/` by default. To use the external SSD, first verify its mount path and filesystem, then set
  `BACKUP_DIR=/Volumes/<name>/social-eagle/backups` in `.env`. The app never requires the SSD to start.
- Backups refuse to run when free space is below `MIN_FREE_DISK_MB` (default 500 MB).

## Verify a backup without touching live data
`scripts/restore data/backups/backup-<stamp>-<label>` → restores into `data/restore-check/<name>`, re-verifies checksums,
runs `PRAGMA integrity_check`, compares row counts. The UI "Test restore" button does the same.

## Replace live data
```
scripts/stop
scripts/restore data/backups/backup-<stamp>-<label> --replace-live   # asks you to type REPLACE; makes a safety backup first
scripts/start
```
