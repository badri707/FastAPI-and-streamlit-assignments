# Shared helpers for Social Eagle scripts. Sourced, not executed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
PY="$BACKEND/.venv/bin/python"
export UV_SYSTEM_CERTS="${UV_SYSTEM_CERTS:-1}"
unset UV_NATIVE_TLS 2>/dev/null || true

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

need_venv() { [ -x "$PY" ] || die "Backend environment missing. Run: \"$ROOT/scripts/setup\""; }

# Prints a setting resolved exactly as the app resolves it (.env + environment).
setting() { (cd "$BACKEND" && "$PY" -c "from app.config import get_settings as g; print(getattr(g(), '$1'))"); }
